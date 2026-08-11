"""Pydantic-Schemas für Stellenangebote (`JobOffer`)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobOfferBase(BaseModel):
    """Gemeinsame Felder, die sowohl beim Anlegen als auch beim Lesen
    eines Stellenangebots vorhanden sind."""

    title: str = Field(..., max_length=255)
    company: str = Field(..., max_length=255)
    location: str | None = Field(default=None, max_length=255)
    source_url: str = Field(..., max_length=1024)
    description_text: str | None = None
    source_platform: str = Field(..., max_length=100)


class JobOfferCreate(JobOfferBase):
    """Payload zum Anlegen eines neuen Stellenangebots (z. B. via Scraper)."""


class JobOfferUpdate(BaseModel):
    """Payload für ein partielles Update - alle Felder sind optional."""

    title: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=1024)
    description_text: str | None = None
    source_platform: str | None = Field(default=None, max_length=100)
    is_processed: bool | None = None


class JobOfferRead(JobOfferBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    is_processed: bool
