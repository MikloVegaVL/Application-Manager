"""Pydantic-Schemas für protokollierte Bewerbungsmail-Versände (`SentEmail`)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["SentEmailRead"]


class SentEmailRead(BaseModel):
    """Antwortmodell für `GET /sent-emails` und die PDF-Export-Endpunkte.

    `company`/`job_title` stammen aus dem zum Versandzeitpunkt gespeicherten
    Snapshot (siehe `app.models.sent_email.SentEmail`), nicht aus einem
    Live-Join - bleiben daher auch erhalten, wenn `application_id` später
    `None` wird (gelöschte Application, KTD7 des Plans). `job_offer_id` ist
    dagegen KEIN Snapshot - er kommt live über die `application`-Beziehung
    und wird `None`, sobald die Application (und damit die Zielseite für den
    Link-through, R5) nicht mehr existiert."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None
    job_offer_id: int | None
    ad_url: str | None
    company: str | None
    job_title: str | None
    source_platform: str | None
    recipient_email: str
    sent_at: datetime
    sender_email: str | None
    subject: str | None
    attachment_filename: str | None


class SentEmailFilter(BaseModel):
    """Query-Parameter, die `GET /sent-emails` und die Export-Endpunkte
    (außer `/export/all`) gemeinsam nutzen (KTD4 des Plans) - dieselben
    Filter müssen exakt dieselbe Ergebnismenge liefern, damit "Export der
    aktuellen Ansicht" wirklich die angezeigte Ansicht exportiert."""

    company: str | None = None
    sender_email: str | None = None
    date_from: date | None = None
    date_to: date | None = None
