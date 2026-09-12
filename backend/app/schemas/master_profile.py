"""Pydantic-Schemas für das Bewerber-Stammprofil (`MasterProfile`)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# KTD3: Skill-Kompetenzgrad als 4-stufige Skala (deutschsprachige Konvention,
# die bereits im übrigen UI dieser App verwendet wird) - bewusst kein
# bespoke-Design, sondern ein fixer, geschlossener Wertebereich.
SkillLevel = Literal["Grundkenntnisse", "Gut", "Sehr gut", "Experte"]

# KTD3: Sprachkenntnisse nutzen den bestehenden externen CEFR-Standard
# (A1-C2), kein bespoke-Design nötig.
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

# Gruppierung der Skills für den CV (R9-Folge): statt einer langen, flachen
# Liste wird je Kategorie eine kompakte Zeile gerendert (siehe
# `app.services.pdf_service.group_skills`). Fixer, geschlossener Wertebereich
# wie bei `SkillLevel`/`LanguageLevel` - die KI ordnet beim CV-Parsen eine
# dieser Kategorien zu, das Frontend bietet dieselben Optionen an.
# `Other` ist der Fallback für nicht zuordenbare oder noch nicht kategorisierte
# Skills (z. B. Altdaten ohne `category`).
SkillCategory = Literal["Frontend", "Backend", "Tools", "Soft Skills", "Other"]


class SkillEntry(BaseModel):
    """Ein Skill mit Kompetenzgrad und optionaler Kategorie (siehe KTD3)."""

    name: str = Field(..., max_length=255)
    level: SkillLevel
    category: SkillCategory | None = None


class LanguageEntry(BaseModel):
    """Eine Sprachkenntnis mit CEFR-Niveau (siehe KTD3)."""

    name: str = Field(..., max_length=255)
    level: LanguageLevel


class ProjectEntry(BaseModel):
    """Ein Projekt im CV-Builder - mindestens Titel und Beschreibung (R3)."""

    title: str = Field(..., max_length=255)
    description: str
    start_date: str | None = Field(default=None, description="z. B. '2020-01' oder '2020'")
    end_date: str | None = Field(default=None, description="leer/None = laufend")
    link: str | None = None


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
    berufsbezeichnung: str | None = Field(default=None, max_length=255)
    experiences_json: list[ExperienceEntry] = Field(default_factory=list)
    education_json: list[EducationEntry] = Field(default_factory=list)
    skills_json: list[SkillEntry] = Field(default_factory=list)
    languages_json: list[LanguageEntry] = Field(default_factory=list)
    projects_json: list[ProjectEntry] = Field(default_factory=list)
    photo_filename: str | None = None
    template_id: str | None = None


class MasterProfileCreate(MasterProfileBase):
    """Payload zum Anlegen bzw. vollständigen Überschreiben des Stammprofils
    (siehe `PUT /api/profile`, das als Upsert implementiert ist)."""


class MasterProfileUpdate(BaseModel):
    """Payload für ein partielles Update - alle Felder sind optional.

    `photo_filename` (wie `photo_path`) ist hier bewusst NICHT enthalten
    (fix(review)): Foto-Metadaten dürfen ausschließlich über die dedizierten
    `POST`/`DELETE /profile/photo`-Endpunkte geschrieben werden, sonst könnte
    ein `PATCH /profile`-Payload `photo_filename` überschreiben, ohne dass
    sich der tatsächliche `photo_path` (bzw. die Datei auf der Festplatte)
    mitändert - die beiden liefen dann auseinander.
    """

    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    berufsbezeichnung: str | None = Field(default=None, max_length=255)
    experiences_json: list[ExperienceEntry] | None = None
    education_json: list[EducationEntry] | None = None
    skills_json: list[SkillEntry] | None = None
    languages_json: list[LanguageEntry] | None = None
    projects_json: list[ProjectEntry] | None = None
    template_id: str | None = None


class ProfileAttachmentRead(BaseModel):
    """Eine zusätzliche Anhang-Datei am Stammprofil (siehe `ProfileAttachment`,
    `POST /profile/attachments`) - wird beim Versand einer Bewerbung neben dem
    Lebenslauf als weiterer E-Mail-Anhang verschickt."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    created_at: datetime


class MasterProfileRead(MasterProfileBase):
    """Antwortmodell inkl. serverseitig verwalteter Felder.

    `cv_filename` ist nur gesetzt, wenn der Nutzer bereits eine Lebenslauf-
    Datei hochgeladen hat (siehe `POST /profile/cv-file`); `null` bedeutet
    "noch keine Datei hochgeladen" - das Frontend nutzt das, um den Upload-
    Status anzuzeigen und den Versand entsprechend zu warnen. `attachments`
    listet die zusätzlichen PDF-Anhänge (siehe `ProfileAttachmentRead`,
    maximal `MAX_PROFILE_ATTACHMENTS` in `app.api.profile`).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    cv_filename: str | None = None
    attachments: list[ProfileAttachmentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ParsedSkill(BaseModel):
    """Ein per KI aus dem CV extrahierter Skill (siehe `ParsedCvProfile`).

    Anders als das gespeicherte `SkillEntry` trägt ein geparster Skill noch
    keinen Kompetenzgrad - den leitet die KI bewusst nicht ab (R7), das
    Frontend ergänzt beim Übernehmen einen Default. Die Kategorie hingegen
    kann die KI bereits zuordnen, damit die CV-Vorlage Skills gruppieren kann.
    """

    name: str = Field(..., max_length=255)
    category: SkillCategory | None = None


class ParsedCvProfile(BaseModel):
    """Ergebnis der KI-gestützten CV-Analyse (siehe `app.services.pdf_parser`).

    Bewusst von `MasterProfileBase` getrennt: Ein Lebenslauf liefert nicht
    zwingend alle Felder (z. B. keine erkennbare E-Mail-Adresse), daher sind
    hier - anders als beim Stammprofil selbst - alle Felder optional.

    `full_name`/`email`/`phone`/`address` sind reine Anzeigefelder für den
    CV-Builder (R5): Sie werden im Import-Vorschau-Formular nur read-only
    dargestellt und fließen NIE in den Save-Payload des Builders ein (KTD1) -
    `POST /cv-builder/parse` schreibt ohnehin grundsätzlich nichts in die
    Datenbank (R6).
    """

    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    summary: str | None = None
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[ParsedSkill] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)


class CvParseResponse(BaseModel):
    """Antwort von `POST /cv-builder/parse` (R5/R6): liefert das rohe, per KI
    geparste Profil unverändert zurück - dieser Endpunkt schreibt NICHTS in
    die Datenbank, das übernimmt ausschließlich ein späterer, expliziter
    Save-Aufruf des Nutzers im Builder-Formular. `warnings` benennt jedes
    Feld, für das die KI nichts gefunden hat (siehe
    `app.services.pdf_parser.missing_field_warnings`), damit das Frontend das
    transparent anzeigen kann statt einen unbedingten Erfolg zu melden."""

    parsed: ParsedCvProfile
    warnings: list[str] = Field(default_factory=list)
