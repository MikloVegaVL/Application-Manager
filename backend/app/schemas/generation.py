"""Pydantic-Schemas für die KI-gestützte Bewerbungsgenerierung
(siehe `app.services.ai_generator`)."""
from pydantic import BaseModel, Field

from app.schemas.master_profile import EducationEntry, ExperienceEntry


class AiTailoredCvContent(BaseModel):
    """Die vom LLM generierten/kuratierten Lebenslauf-Inhalte.

    Bewusst OHNE Kontaktdaten (Name, E-Mail, Telefon, Adresse) - diese
    werden deterministisch aus dem `MasterProfile` übernommen, statt sie
    von der KI reproduzieren zu lassen (vermeidet Halluzinationen bei
    sicherheitsrelevanten Daten).
    """

    summary: str = Field(..., description="Auf die Zielstelle zugeschnittenes berufliches Profil")
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class AiGenerationResult(BaseModel):
    """Rohes Ergebnis des LLM-Aufrufs (siehe `_SYSTEM_PROMPT` in `ai_generator.py`)."""

    cover_letter_text: str
    cv_content: AiTailoredCvContent


class TailoredCv(BaseModel):
    """Vollständiger, render-fertiger Lebenslauf für die PDF-Erzeugung:
    Kontaktdaten deterministisch aus dem Profil, restliche Inhalte
    KI-generiert bzw. -kuratiert."""

    full_name: str
    email: str
    phone: str | None = None
    address: str | None = None
    summary: str
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
