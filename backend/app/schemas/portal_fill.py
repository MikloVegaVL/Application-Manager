"""Pydantic-Schemas für die Fill-API der Browser-Erweiterung (U3,
docs/plans/2026-09-22-003-feat-browser-extension-application-autofill-plan.md).

Trennt die app-aufgerufene Fill-Request-Route von den secret-gated
`/portal-fill/*`-Routen der Erweiterung. Das Fill-Paket (`PortalFillContext`)
enthält ausschließlich, was die Erweiterung zum Ausfüllen braucht (KTD2,
Annahmen) - keine Zugangsdaten.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.master_profile import (
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
    SkillEntry,
)


class PortalFillProfile(BaseModel):
    """Die Standard-Profilfelder, die die Erweiterung direkt füllen kann
    (R6) - inkl. der strukturierten Listen, damit auch Fragen zu Werdegang
    und Ausbildung lokal beantwortet werden können."""

    full_name: str
    email: str
    phone: str | None = None
    address: str | None = None
    linkedin: str | None = None
    website: str | None = None
    summary: str | None = None
    berufsbezeichnung: str | None = None
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)


class PortalFillDocument(BaseModel):
    """Ein hochladbares Dokument (Lebenslauf oder zusätzlicher Anhang, R8) -
    die Erweiterung lädt die Bytes über `download_url` vom App-Origin."""

    kind: Literal["cv", "attachment"]
    id: int | None = None
    filename: str
    download_url: str


class PortalFillContext(BaseModel):
    """Das Fill-Paket, das `GET /portal-fill/context` zurückgibt."""

    application_id: int
    job_offer_id: int
    job_title: str
    company: str
    job_url: str
    job_description: str | None = None
    cover_letter_text: str | None = None
    profile: PortalFillProfile
    documents: list[PortalFillDocument] = Field(default_factory=list)


class PortalFillRequestCreate(BaseModel):
    """JSON-Body für `POST /applications/{id}/fill-request`.

    Absichtlich leer: der Body existiert nur, damit der Request kein
    CORS-Simple-Request ist (KTD13) - die App liest alle nötigen Daten aus
    der Application/dem JobOffer."""


class PortalFillRequestResponse(BaseModel):
    """Antwort von `POST /applications/{id}/fill-request` - die Job-URL, die
    die App in einem neuen Tab öffnet (R1)."""

    job_url: str


class PortalFillAnswerRequest(BaseModel):
    """Payload für `POST /portal-fill/answer` (R7)."""

    application_id: int
    question: str = Field(..., min_length=1, max_length=2000)


class PortalFillAnswerResponse(BaseModel):
    """Ergebnis eines LLM-Antwortaufrufs (KTD7). `insufficient_information`
    signalisiert der Erweiterung, das Feld sichtbar zu markieren (R10),
    statt eine erfundene Antwort zu füllen."""

    answer: str
    insufficient_information: bool = False


class PortalFillSubmissionRequest(BaseModel):
    """Payload für `POST /portal-fill/submission` (R11/KTD3).

    `company`/`job_title`/`platform`/`submitted_at` werden bewusst NICHT
    akzeptiert - sie leitet der Server aus dem `JobOffer` ab bzw. stempelt
    sie selbst. `portal_url` ist die tatsächlich abgesendete Formular-URL
    (LinkedIn-Job oder externe Arbeitgeber-Seite)."""

    report_id: str = Field(..., min_length=1, max_length=128)
    job_offer_id: int
    portal_url: str = Field(..., min_length=1, max_length=2048)


class PortalFillSubmissionResponse(BaseModel):
    """Die gespeicherte Submission-Zeile (idempotent, KTD3)."""

    model_config = ConfigDict(from_attributes=True)

    report_id: str | None = None
    application_id: int | None = None
    company: str | None = None
    job_title: str | None = None
    platform: str | None = None
    portal_url: str
    submitted_at: datetime
