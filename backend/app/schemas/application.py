"""Pydantic-Schemas für Bewerbungen (`Application`)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.application import ApplicationStatus
from app.schemas.job_offer import JobOfferRead
from app.schemas.master_profile import ProfileType

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
    "ApplicationSubmissionSummary",
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


class ApplicationSubmissionSummary(BaseModel):
    """Kompaktes "applied"-Indiz für die Bewerbungsübersicht (U4/KTD3),
    abgeleitet aus der jüngsten `PortalSubmission`-Zeile der Bewerbung -
    damit die Oberfläche das Indiz ohne zweiten Request rendern kann."""

    model_config = ConfigDict(from_attributes=True)

    platform: str | None = None
    portal_url: str
    submitted_at: datetime


class ApplicationRead(ApplicationBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder.

    Enthält das zugehörige `job_offer` (Titel/Firma etc.), damit die
    Bewerbungsübersicht (`GET /applications`) ohne N+1-Nachladen pro Zeile
    im Frontend Titel und Firma anzeigen kann.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    sent_at: datetime | None = None
    sent_to_email: str | None = None
    created_at: datetime
    job_offer: JobOfferRead
    # `null`, solange kein Portal-Fill erfolgreich gemeldet wurde (R11).
    submission: ApplicationSubmissionSummary | None = None
    # Zugeordnetes Profil (`it`/`full_life`, U3/R4/R5) - `null`, solange noch
    # nicht generiert wurde. Gelesen über `Application.profile_type` (Property,
    # siehe `app.models.application`), das intern die verknüpfte
    # `MasterProfile.profile_type` auflöst.
    profile_type: str | None = None


class ApplicationGenerateRequest(BaseModel):
    """Payload für `POST /api/applications/generate`.

    `profile_type` ist nur bei der ERSTEN Generierung für ein Stellenangebot
    Pflicht (R4) - ist für die Bewerbung bereits ein Profil gesperrt (R5),
    wird ein hier mitgeschickter Wert ignoriert (siehe
    `app.api.applications.generate_application`, KTD3).

    `for_new_application` ist R5's Ausweg (U9, KTD12): statt das für dieses
    Stellenangebot bereits gesperrte Profil zu überschreiben, legt es eine
    ZUSÄTZLICHE, unabhängige `Application`-Zeile für dasselbe Stellenangebot
    an, gesperrt auf das hier mitgeschickte `profile_type`. Bewusst ein
    explizites Flag statt eines impliziten Nebeneffekts (z. B. beim erneuten
    Speichern des Jobs) - das verhindert, dass ein wiederholter/verdoppelter
    Request stillschweigend weitere `Application`-Zeilen erzeugt."""

    job_offer_id: int
    profile_type: ProfileType | None = None
    for_new_application: bool = False


class ApplicationSendRequest(BaseModel):
    """Payload für `POST /api/applications/{id}/send`.

    `to_email` wird explizit übergeben statt aus dem `JobOffer` abgeleitet,
    da gescrapte Stellenangebote keine strukturierte Kontakt-E-Mail liefern -
    der Nutzer prüft/ergänzt die Empfängeradresse vor dem Versand.
    """

    to_email: EmailStr
    subject: str | None = Field(default=None, max_length=255)
    message: str | None = None
