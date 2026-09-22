"""API-Router für das Bewerbungsmail-Protokoll (`SentEmail`) - Übersicht,
Filterung und PDF-Export (siehe docs/plans/2026-09-14-001-feat-application-
email-log-plan.md)."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session, contains_eager, joinedload

from app.db.database import get_db
from app.models.application import Application, ApplicationStatus
from app.models.sent_email import SentEmail
from app.schemas.sent_email import SentEmailFilter, SentEmailRead
from app.services.pdf_service import PdfRenderError, render_sent_emails_pdf

router = APIRouter(prefix="/sent-emails", tags=["Sent Emails"])


def _apply_filters(query: Query, filters: SentEmailFilter) -> Query:
    """Wendet den gemeinsamen Filter-Vertrag von Liste und Export an (KTD4) -
    alle gesetzten Filter kombinieren sich mit UND. `company` ist ein
    case-insensitiver Teilstring-Treffer (nicht exakt) - Firmennamen kommen
    aus gescrapten Stellenangeboten (`JobOffer.company`) mit uneinheitlicher
    Schreibweise, ein exakter Treffer würde ein Freitextfeld zur
    Ratespiel-Falle machen."""
    if filters.company:
        query = query.filter(SentEmail.company.ilike(f"%{filters.company}%"))
    if filters.sender_email:
        query = query.filter(SentEmail.sender_email == filters.sender_email)
    if filters.date_from:
        query = query.filter(func.date(SentEmail.sent_at) >= filters.date_from)
    if filters.date_to:
        query = query.filter(func.date(SentEmail.sent_at) <= filters.date_to)
    if filters.outcome:
        # Outer join (KTD3): an inner join would silently drop "pending because
        # the application was deleted" rows (`application_id IS NULL`) from the
        # Pending filter option. Applies to both list and export queries (KTD2)
        # via this shared function - only the rendered PDF column stays out (R6).
        query = query.outerjoin(Application, SentEmail.application_id == Application.id)
        if filters.outcome == "offer":
            query = query.filter(Application.status == ApplicationStatus.ACCEPTED)
        elif filters.outcome == "rejection":
            query = query.filter(Application.status == ApplicationStatus.REJECTED)
        else:
            query = query.filter(
                or_(
                    Application.status.is_(None),
                    Application.status.notin_([ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED]),
                )
            )
    return query


def _base_query(db: Session, filters: SentEmailFilter) -> Query:
    query = db.query(SentEmail).order_by(SentEmail.sent_at.desc())
    return _apply_filters(query, filters)


def _query_entries_for_list(db: Session, filters: SentEmailFilter) -> list[SentEmail]:
    # `SentEmailRead.job_offer_id`/`ad_url`/`outcome` lesen `entry.application`
    # (siehe die gleichnamigen `SentEmail`-Properties) - ohne Eager-Load würde
    # das pro Zeile eigene Nachlade-Queries auslösen (N+1). Nur hier nötig: die
    # PDF-Exports (`_query_entries_for_export`) lesen das nie, der Join würde
    # dort nur unnötig mitlaufen.
    #
    # `contains_eager` statt `joinedload` wenn `filters.outcome` gesetzt ist:
    # `_apply_filters` hat dann bereits einen `outerjoin(Application, ...)`
    # für den WHERE-Filter hinzugefügt (KTD3) - `contains_eager` liest die
    # Application-Spalten aus genau diesem bestehenden Join statt einen
    # zweiten, redundanten JOIN auf dieselbe Tabelle zu erzeugen.
    query = _base_query(db, filters)
    if filters.outcome:
        query = query.options(contains_eager(SentEmail.application).joinedload(Application.job_offer))
    else:
        query = query.options(joinedload(SentEmail.application).joinedload(Application.job_offer))
    return query.all()


def _query_entries_for_export(db: Session, filters: SentEmailFilter) -> list[SentEmail]:
    return _base_query(db, filters).all()


@router.get("", response_model=list[SentEmailRead])
def list_sent_emails(
    filters: SentEmailFilter = Depends(), db: Session = Depends(get_db)
) -> list[SentEmail]:
    """Listet alle protokollierten Bewerbungsmail-Versände, neueste zuerst,
    optional gefiltert nach Firma, Absender-Account, Zeitraum (R4/R7) und
    Outcome (R5) - Outcome wird live über die verknüpfte Application ermittelt,
    nicht aus einer Spalte auf `SentEmail`."""
    return _query_entries_for_list(db, filters)


def _pdf_response(entries: list[SentEmail], *, filtered: bool, filename: str) -> StreamingResponse:
    # Gleiche Fehlerbehandlung wie `cv_builder.py`s Export-Endpunkte (Review-
    # Fund) - ohne diesen Catch hätte ein WeasyPrint-Fehler hier eine andere
    # Fehlerform (500 mit Traceback statt konsistentem JSON-`detail`) geliefert
    # als der Rest der API.
    try:
        pdf_bytes = render_sent_emails_pdf(entries, filtered=filtered)
    except PdfRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate the sent-emails PDF: {exc}",
        ) from exc
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
def export_sent_emails(
    filters: SentEmailFilter = Depends(), db: Session = Depends(get_db)
) -> StreamingResponse:
    """Exportiert die aktuell gefilterte Ansicht als PDF (R8) - nutzt exakt
    denselben Filter-Vertrag wie `GET /sent-emails` (KTD4), damit "Export der
    aktuellen Ansicht" wirklich die angezeigte Ansicht exportiert."""
    entries = _query_entries_for_export(db, filters)
    return _pdf_response(entries, filtered=True, filename="sent-emails-filtered.pdf")


@router.get("/export/all")
def export_all_sent_emails(db: Session = Depends(get_db)) -> StreamingResponse:
    """Exportiert das vollständige Protokoll als PDF, unabhängig von einer
    ggf. aktiven Filterung im Frontend (R9)."""
    entries = _query_entries_for_export(db, SentEmailFilter())
    return _pdf_response(entries, filtered=False, filename="sent-emails-full-log.pdf")


@router.delete("/{sent_email_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sent_email(sent_email_id: int, db: Session = Depends(get_db)) -> None:
    """Löscht einen einzelnen Protokoll-Eintrag (nur den Log-Eintrag, nicht
    die verknüpfte Application/JobOffer)."""
    entry = db.get(SentEmail, sent_email_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log-Eintrag wurde nicht gefunden.")
    db.delete(entry)
    db.commit()
