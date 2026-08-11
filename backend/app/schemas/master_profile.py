"""Pydantic-Schemas für das Bewerber-Stammprofil (`MasterProfile`)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MasterProfileBase(BaseModel):
    """Gemeinsame Felder für das Stammprofil.

    `experiences_json`, `education_json` und `skills_json` sind bewusst
    generisch als Liste von Dicts bzw. Strings typisiert, da die konkrete
    Struktur (Werdegangs-Stationen, Ausbildungsabschnitte) in einem
    späteren Command feiner spezifiziert und validiert wird.
    """

    full_name: str = Field(..., max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    experiences_json: list[dict[str, Any]] = Field(default_factory=list)
    education_json: list[dict[str, Any]] = Field(default_factory=list)
    skills_json: list[str] = Field(default_factory=list)


class MasterProfileCreate(MasterProfileBase):
    """Payload zum Anlegen des Stammprofils."""


class MasterProfileUpdate(BaseModel):
    """Payload für ein partielles Update - alle Felder sind optional."""

    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    experiences_json: list[dict[str, Any]] | None = None
    education_json: list[dict[str, Any]] | None = None
    skills_json: list[str] | None = None


class MasterProfileRead(MasterProfileBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
