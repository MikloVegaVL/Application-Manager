"""API-Router für das Bewerbungsmail-Protokoll (`SentEmail`) - Übersicht,
Filterung und PDF-Export (siehe docs/plans/2026-09-14-001-feat-application-
email-log-plan.md)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.db.database import get_db
from app.models.sent_email import SentEmail
from app.schemas.sent_email import SentEmailFilter, SentEmailRead

router = APIRouter(prefix="/sent-emails", tags=["Sent Emails"])


def _apply_filters(query: Query, filters: SentEmailFilter) -> Query:
    """Wendet den gemeinsamen Filter-Vertrag von Liste und Export an (KTD4) -
    alle gesetzten Filter kombinieren sich mit UND."""
    if filters.company:
        query = query.filter(SentEmail.company == filters.company)
    if filters.sender_email:
        query = query.filter(SentEmail.sender_email == filters.sender_email)
    if filters.date_from:
        query = query.filter(func.date(SentEmail.sent_at) >= filters.date_from)
    if filters.date_to:
        query = query.filter(func.date(SentEmail.sent_at) <= filters.date_to)
    return query


def _query_entries(db: Session, filters: SentEmailFilter) -> list[SentEmail]:
    query = db.query(SentEmail).order_by(SentEmail.sent_at.desc())
    return _apply_filters(query, filters).all()


@router.get("", response_model=list[SentEmailRead])
def list_sent_emails(
    filters: SentEmailFilter = Depends(), db: Session = Depends(get_db)
) -> list[SentEmail]:
    """Listet alle protokollierten Bewerbungsmail-Versände, neueste zuerst,
    optional gefiltert nach Firma, Absender-Account und Zeitraum (R4/R7)."""
    return _query_entries(db, filters)
