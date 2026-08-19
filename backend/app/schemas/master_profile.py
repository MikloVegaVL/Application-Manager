"""Pydantic-Schemas für das Bewerber-Stammprofil (`MasterProfile`)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ExperienceEntry(BaseModel):
    """Eine Station im beruflichen Werdegang."""

    company: str = Field(..., max_length=255)
    role: str = Field(..., max_length=255)
    start_date: str | None = Field(default=None, description="z. B. '2020-01' oder '2020'")
    end_date: str | None = Field(default=None, description="leer/None = aktuelle Position")
    description: str | None = None


class EducationEntry(BaseModel):
    """Eine Ausbildungs-/Studienstation."""

    institution: str = Field(..., max_length=255)
    degree: str = Field(..., max_length=255)
    field_of_study: str | None = Field(default=None, max_length=255)
    start_date: str | None = None
    end_date: str | None = None


class MasterProfileBase(BaseModel):
    """Gemeinsame Felder für das Stammprofil."""

    full_name: str = Field(..., max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    experiences_json: list[ExperienceEntry] = Field(default_factory=list)
    education_json: list[EducationEntry] = Field(default_factory=list)
    skills_json: list[str] = Field(default_factory=list)


class MasterProfileCreate(MasterProfileBase):
    """Payload zum Anlegen bzw. vollständigen Überschreiben des Stammprofils
    (siehe `PUT /api/profile`, das als Upsert implementiert ist)."""


class MasterProfileUpdate(BaseModel):
    """Payload für ein partielles Update - alle Felder sind optional."""

    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    experiences_json: list[ExperienceEntry] | None = None
    education_json: list[EducationEntry] | None = None
    skills_json: list[str] | None = None


class MasterProfileRead(MasterProfileBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder.

    `cv_filename` ist nur gesetzt, wenn der Nutzer bereits eine Lebenslauf-
    Datei hochgeladen hat (siehe `POST /profile/cv-file`); `null` bedeutet
    "noch keine Datei hochgeladen" - das Frontend nutzt das, um den Upload-
    Status anzuzeigen und den Versand entsprechend zu warnen.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    cv_filename: str | None = None
    created_at: datetime
    updated_at: datetime


class CvUploadResponse(BaseModel):
    """Antwort von `POST /profile/upload-cv`.

    `upload_cv` übernimmt Felder aus dem CV nur, wenn die KI dafür tatsächlich
    etwas gefunden hat (siehe `app.api.profile.upload_cv`) - ein unvollständig
    gelesener CV darf ein bereits gepflegtes Profil nicht mit leeren Werten
    überschreiben. Das schützt gute Daten, verschluckt aber ohne `warnings`
    stillschweigend, dass z. B. gar keine Berufserfahrung erkannt wurde -
    siehe ce-debug-Untersuchung, 2026-08-18 (ein Nutzer bemerkte erst beim
    manuellen Nachsehen, dass sein Profil trotz "erfolgreichem" Import keine
    Berufserfahrung/Ausbildung enthielt). `warnings` benennt jedes Feld, das
    die KI leer zurückgab und das deshalb NICHT übernommen wurde, damit das
    Frontend das transparent anzeigen kann statt einen unbedingten Erfolg zu
    melden.
    """

    profile: MasterProfileRead
    warnings: list[str] = Field(default_factory=list)


class ParsedCvProfile(BaseModel):
    """Ergebnis der KI-gestützten CV-Analyse (siehe `app.services.pdf_parser`).

    Bewusst von `MasterProfileBase` getrennt: Ein Lebenslauf liefert nicht
    zwingend alle Felder (z. B. keine erkennbare E-Mail-Adresse), daher sind
    hier - anders als beim Stammprofil selbst - alle Felder optional.
    """

    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    summary: str | None = None
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
