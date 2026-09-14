"""API-Router für das Bewerbungsmail-Protokoll (`SentEmail`) - Übersicht,
Filterung und PDF-Export (siehe docs/plans/2026-09-14-001-feat-application-
email-log-plan.md)."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Query, Session, joinedload

from app.db.database import get_db
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
    return query


def _base_query(db: Session, filters: SentEmailFilter) -> Query:
    query = db.query(SentEmail).order_by(SentEmail.sent_at.desc())
    return _apply_filters(query, filters)


def _query_entries_for_list(db: Session, filters: SentEmailFilter) -> list[SentEmail]:
    # `joinedload`: `SentEmailRead.job_offer_id` liest `entry.application.
    # job_offer_id` (siehe `SentEmail.job_offer_id`-Property) - ohne Eager-
    # Load würde das pro Zeile eine eigene Nachlade-Query auslösen (N+1).
    # Nur hier nötig: die PDF-Exports (`_query_entries_for_export`) lesen
    # `job_offer_id` nie, der Join würde dort nur unnötig mitlaufen.
    return _base_query(db, filters).options(joinedload(SentEmail.application)).all()


def _query_entries_for_export(db: Session, filters: SentEmailFilter) -> list[SentEmail]:
    return _base_query(db, filters).all()


@router.get("", response_model=list[SentEmailRead])
def list_sent_emails(
    filters: SentEmailFilter = Depends(), db: Session = Depends(get_db)
) -> list[SentEmail]:
    """Listet alle protokollierten Bewerbungsmail-Versände, neueste zuerst,
    optional gefiltert nach Firma, Absender-Account und Zeitraum (R4/R7)."""
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
