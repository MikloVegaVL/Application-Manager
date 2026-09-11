"""Pydantic-Schemas für Bewerbungen (`Application`)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.application import ApplicationStatus
from app.schemas.job_offer import JobOfferRead

# Enum aus dem ORM-Modell wiederverwendet, damit API und DB immer denselben
# Satz gültiger Status-Werte kennen
# ('draft', 'sent', 'rejected', 'accepted', 'interview').
__all__ = [
    "ApplicationStatus",
    "ApplicationBase",
    "ApplicationCreate",
    "ApplicationUpdate",
    "ApplicationRead",
    "ApplicationGenerateRequest",
    "ApplicationSendRequest",
]


class ApplicationBase(BaseModel):
    """Gemeinsame Felder einer Bewerbung."""

    job_offer_id: int
    cover_letter_text: str | None = None
    status: ApplicationStatus = ApplicationStatus.DRAFT


class ApplicationCreate(ApplicationBase):
    """Payload zum Anlegen einer neuen Bewerbung zu einem Stellenangebot."""


class ApplicationUpdate(BaseModel):
    """Payload für ein partielles Update - alle Felder sind optional.

    `job_offer_id` ist absichtlich ausgenommen: eine Bewerbung wird nicht
    nachträglich einem anderen Stellenangebot zugeordnet.
    """

    cover_letter_text: str | None = None
    status: ApplicationStatus | None = None
    sent_at: datetime | None = None


class ApplicationRead(ApplicationBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder.

    Enthält das zugehörige `job_offer` (Titel/Firma etc.), damit die
    Bewerbungsübersicht (`GET /applications`) ohne N+1-Nachladen pro Zeile
    im Frontend Titel und Firma anzeigen kann.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    sent_at: datetime | None = None
    created_at: datetime
    job_offer: JobOfferRead


class ApplicationGenerateRequest(BaseModel):
    """Payload für `POST /api/applications/generate`."""

    job_offer_id: int


class ApplicationSendRequest(BaseModel):
    """Payload für `POST /api/applications/{id}/send`.

    `to_email` wird explizit übergeben statt aus dem `JobOffer` abgeleitet,
    da gescrapte Stellenangebote keine strukturierte Kontakt-E-Mail liefern -
    der Nutzer prüft/ergänzt die Empfängeradresse vor dem Versand.
    """

    to_email: EmailStr
    subject: str | None = Field(default=None, max_length=255)
    message: str | None = None
