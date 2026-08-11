"""Pydantic-Schemas für Bewerbungen (`Application`)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.application import ApplicationStatus

# Enum aus dem ORM-Modell wiederverwendet, damit API und DB immer denselben
# Satz gültiger Status-Werte kennen ('draft', 'sent', 'rejected', 'interview').
__all__ = [
    "ApplicationStatus",
    "ApplicationBase",
    "ApplicationCreate",
    "ApplicationUpdate",
    "ApplicationRead",
]


class ApplicationBase(BaseModel):
    """Gemeinsame Felder einer Bewerbung."""

    job_offer_id: int
    cover_letter_text: str | None = None
    tailored_cv_json: dict[str, Any] | None = None
    pdf_path: str | None = Field(default=None, max_length=1024)
    status: ApplicationStatus = ApplicationStatus.DRAFT


class ApplicationCreate(ApplicationBase):
    """Payload zum Anlegen einer neuen Bewerbung zu einem Stellenangebot."""


class ApplicationUpdate(BaseModel):
    """Payload für ein partielles Update - alle Felder sind optional.

    `job_offer_id` ist absichtlich ausgenommen: eine Bewerbung wird nicht
    nachträglich einem anderen Stellenangebot zugeordnet.
    """

    cover_letter_text: str | None = None
    tailored_cv_json: dict[str, Any] | None = None
    pdf_path: str | None = Field(default=None, max_length=1024)
    status: ApplicationStatus | None = None
    sent_at: datetime | None = None


class ApplicationRead(ApplicationBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sent_at: datetime | None = None
    created_at: datetime
