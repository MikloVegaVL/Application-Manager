"""Service zur PDF-Erstellung des Lebenslaufs (CV-Builder, U5).

Rendert eines der `templates/cv/*.html`-Templates mit den vom Nutzer im
CV-Builder-Formular gepflegten Inhalten (Freitext, Stationen, Skills, ...),
serverseitig gemerged mit den Identitätsfeldern (Name/Kontakt) des
gespeicherten `MasterProfile`-Datensatzes (siehe `app.api.cv_builder`,
KTD11), und konvertiert das Ergebnis via WeasyPrint zu PDF-Bytes.

Wiederbelebt das gleichnamige, in Commit `97ac0b1` entfernte Modul (siehe
Plan `docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md`, U5) -
angepasst an das seitdem geänderte Schema (`SkillEntry`/`LanguageEntry` mit
Kompetenzgrad statt reiner Namens-Strings, `ProjectEntry`, Foto) und um
Template-Auswahl (R9) sowie eine `url_fetcher`-Einschränkung (KTD6) erweitert.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, URLFetcher

from app.schemas.master_profile import DocumentLanguage
from app.services.cv_sample_content import SAMPLE_DE, SAMPLE_EN

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_CV_TEMPLATES_DIR = _TEMPLATES_DIR / "cv"

# Autoescaping bleibt zwingend aktiv (KTD6): das gerenderte Template enthält
# Freitext, den der Nutzer selbst eingibt oder den eine KI-Analyse einer
# beliebigen hochgeladenen CV-PDF liefert (Kurzprofil, Beschreibungstexte) -
# ohne Autoescaping könnte dieser Text als aktives HTML/JS ins Zwischen-HTML
# gelangen, das WeasyPrint anschließend rendert.
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)

# R9: kleine, feste Auswahl an visuellen Vorlagen (2-3 Stück) - dieselben
# Inhalte/Abschnitte, nur Layout/Typografie/Farbe unterscheiden sich. Der
# `Literal`-Typ hier ist die einzige Quelle der Wahrheit für gültige
# Template-IDs: `CvTemplateId` treibt sowohl die Pydantic-Validierung des
# Preview-/Export-Payloads (unbekannte ID -> automatisch 422 durch FastAPI)
# als auch `GET /cv-builder/templates` (siehe `app.api.cv_builder`).
CvTemplateId = Literal["classic", "template-1", "template-2", "template-3", "template-4"]

CV_TEMPLATES: list[dict[str, str]] = [
    {"id": "classic", "label": "Classic"},
    {"id": "template-1", "label": "Template 1"},
    {"id": "template-2", "label": "Template 2"},
    {"id": "template-3", "label": "Template 3"},
    {"id": "template-4", "label": "Template 4"},
]


class PdfRenderError(Exception):
    """Wird ausgelöst, wenn die PDF-Erzeugung fehlschlägt."""


# KTD6: WeasyPrint darf beim Rendern eines Preview-/Export-Requests keine
# ausgehenden Netzwerk-Requests an vom Nutzer beeinflussbare URLs auslösen
# (z. B. wenn ein per KI geparster Lebenslauf oder ein manuell eingetragener
# Projekt-Link zufällig wie eine Bild-/Stylesheet-URL aussieht). Erlaubt sind
# ausschließlich `file://` (für das lokal gespeicherte Profilfoto, siehe
# `render_cv_pdf`) und `data:` (eingebettete Ressourcen) - alles andere wird
# von `URLFetcher` bereits VOR jedem Verbindungsaufbau anhand des Schemas
# abgelehnt (siehe `URLFetcher.fetch`), nicht erst nachträglich gefiltert.
_LOCAL_ONLY_URL_FETCHER = URLFetcher(allowed_protocols=("file", "data"))


def _format_date_range(start: str | None, end: str | None, language: DocumentLanguage) -> str:
    """Formatiert einen Start-/End-Zeitraum als lesbaren String, z. B.
    '2021 – 2024', '2021 – present' (Englisch) oder 'seit 2021' (Deutsch).
    Nur die offene Wortwahl lokalisiert; die Datumswerte selbst bleiben
    unverändert (R6)."""
    if not start and not end:
        return ""
    if start and not end:
        return f"seit {start}" if language == "de" else f"{start} – present"
    if not start and end:
        return end
    return f"{start} – {end}"


def _entry_dict(entry: Any) -> dict[str, Any]:
    """Normalisiert einen Eintrag (Pydantic-Modell oder bereits ein dict) zu
    einem dict, damit `render_cv_pdf` sowohl mit den Schema-Objekten aus
    `app.api.cv_builder` als auch mit rohen dicts (z. B. in Tests) genutzt
    werden kann."""
    if hasattr(entry, "model_dump"):
        return entry.model_dump()
    return dict(entry)


def _entries_with_date_range(entries: list[Any], language: DocumentLanguage) -> list[dict[str, Any]]:
    """Reichert Erfahrung/Ausbildung/Projekt-Einträge mit dem sprachabhängig
    formatierten `date_range` an - dieselbe Form für alle drei Listen."""
    return [
        {
            **_entry_dict(entry),
            "date_range": _format_date_range(entry.start_date, entry.end_date, language),
        }
        for entry in entries
    ]


def _photo_file_uri(photo_path: str | Path | None) -> str | None:
    """Liefert eine `file://`-URI für das gespeicherte Profilfoto, oder
    `None`, wenn kein Foto existiert bzw. die Datei nicht (mehr) auf der
    Festplatte liegt. Das Template lässt den Foto-Slot in letzterem Fall
    bewusst komplett weg, statt ein kaputtes `<img>` zu rendern."""
    if not photo_path:
        return None
    path = Path(photo_path)
    if not path.is_file():
        return None
    return path.resolve().as_uri()


# Englische Anzeige-Labels für die intern deutsch gehaltenen `SkillLevel`-
# Werte. Die Enum-Werte bleiben unverändert, damit Schema/Migration/Frontend-
# Formular stabil bleiben; auf Deutsch sind sie selbst das Label (KTD4), auf
# Englisch greift diese Zuordnung.
_SKILL_LEVEL_LABELS_EN: dict[str, str] = {
    "Grundkenntnisse": "Basic",
    "Gut": "Good",
    "Sehr gut": "Very good",
    "Experte": "Expert",
}

# R4/KTD1: Anzahl gefüllter Blöcke (von 5) je Kompetenzgrad. Die 4-stufige
# Skala wird auf 5 Blöcke abgebildet, ohne dass eine Stufe leer wirkt
# (Grundkenntnisse = 2/5 ... Experte = 5/5) - serverseitig berechnet, damit
# keine Vorlage die Zuordnung lokal dupliziert.
_SKILL_LEVEL_BLOCKS: dict[str, int] = {
    "Grundkenntnisse": 2,
    "Gut": 3,
    "Sehr gut": 4,
    "Experte": 5,
}

# R6/KTD1: Anzahl gefüllter Punkte (von 6) je CEFR-Stufe (A1 = 1 ... C2 = 6) -
# unverändert übernommen aus der bisherigen lokalen `lang_dots`-Map in
# `template-1.html`, jetzt serverseitig zentral berechnet.
_LANGUAGE_LEVEL_DOTS: dict[str, int] = {
    "A1": 1,
    "A2": 2,
    "B1": 3,
    "B2": 4,
    "C1": 5,
    "C2": 6,
}

# R5/KTD1: alle festen Dokument-Chrome-Strings pro Dokumentsprache an einer
# Stelle. Jede der fünf Vorlagen konsumiert dieses Mapping als `doc`, statt die
# Strings lokal zu duplizieren. `title` ist das Substantiv im Dokumenttitel
# (`<title>{{ doc.title }} - {{ full_name }}</title>`), `page_prefix`/`page_of`
# bilden den `@page`-Footer. Die Nutzerinhalte werden nie übersetzt (R6).
_DEFAULT_DOCUMENT_LANGUAGE: DocumentLanguage = "en"
_DOC_CHROME: dict[DocumentLanguage, dict[str, str]] = {
    "en": {
        "lang": "en",
        "title": "Resume",
        "page_prefix": "Page",
        "page_of": "of",
        "photo_alt": "Profile photo",
        "photo_placeholder": "Photo",
        "contact": "Contact",
        "profile": "Profile",
        "experience": "Experience",
        "education": "Education",
        "skills": "Skills",
        "languages": "Languages",
        "projects": "Projects",
    },
    "de": {
        "lang": "de",
        "title": "Lebenslauf",
        "page_prefix": "Seite",
        "page_of": "von",
        "photo_alt": "Profilfoto",
        "photo_placeholder": "Foto",
        "contact": "Kontakt",
        "profile": "Profil",
        "experience": "Berufserfahrung",
        "education": "Ausbildung",
        "skills": "Skills",
        "languages": "Sprachen",
        "projects": "Projekte",
    },
}


def _skills_ctx(skills: list[Any], language: DocumentLanguage) -> list[dict[str, Any]]:
    """Normalisiert eine flache Skill-Liste für R3/R4: jede Vorlage außer
    Classic rendert jeden Skill als eigene Zeile mit einem 5-Block-Balken
    (`level_blocks`); Classic zeigt stattdessen die Textform des Kompetenzgrads
    (`level_label`, auch von den anderen Vorlagen für den unsichtbaren
    ATS-Text laut KTD10 wiederverwendet). Auf Deutsch ist die Textform der
    `SkillLevel`-Enum-Wert selbst (Grundkenntnisse/Gut/Sehr gut/Experte, KTD4);
    auf Englisch greift `_SKILL_LEVEL_LABELS_EN`."""
    result: list[dict[str, Any]] = []
    for skill in skills:
        entry = _entry_dict(skill)
        level = entry.get("level")
        if language == "de":
            level_label = level or ""
        else:
            level_label = _SKILL_LEVEL_LABELS_EN.get(level, level or "")
        result.append(
            {
                **entry,
                "level_blocks": _SKILL_LEVEL_BLOCKS.get(level, 0),
                "level_label": level_label,
            }
        )
    return result


def _languages_ctx(languages: list[Any]) -> list[dict[str, Any]]:
    """Normalisiert eine Sprachen-Liste für R6: jede Vorlage außer Classic
    rendert jede Sprache als eigene Zeile mit dem bestehenden 6-Punkte-CEFR-
    Indikator (`level_dots`)."""
    result: list[dict[str, Any]] = []
    for language in languages:
        entry = _entry_dict(language)
        result.append(
            {
                **entry,
                "level_dots": _LANGUAGE_LEVEL_DOTS.get(entry.get("level"), 0),
            }
        )
    return result


def render_cv_pdf(
    *,
    template_id: str,
    full_name: str,
    email: str,
    phone: str | None,
    address: str | None,
    summary: str | None,
    berufsbezeichnung: str | None = None,
    experiences: list[Any],
    education: list[Any],
    skills: list[Any],
    languages: list[Any],
    projects: list[Any],
    photo_path: str | Path | None,
    document_language: str | None = None,
    preview: bool = False,
    sample: Mapping[str, Any] | None = None,
) -> bytes:
    """Rendert den Lebenslauf als PDF (bytes).

    `template_id` wählt eines der `templates/cv/*.html`-Templates (R9).
    `document_language` (`"de"`/`"en"`, `None` = Englisch) steuert die Sprache
    der festen Dokument-Chrome (R4/R5) und des Vorschau-Skeletons (R8);
    unbekannte Werte fallen auf Englisch zurück.
    `full_name`/`email`/`phone`/`address` sind die serverseitig aus dem
    gespeicherten `MasterProfile` gemergten Identitätsfelder (KTD11);
    `photo_path` ist der Dateisystempfad des gespeicherten Profilfotos
    (oder `None`) - anders als die übrigen Inhaltsfelder kommt das Foto
    NICHT aus dem Request-Body, da es bereits beim Upload persistiert wird
    (siehe `app.api.cv_builder`).
    """
    resolved_language = (
        document_language if document_language in _DOC_CHROME else _DEFAULT_DOCUMENT_LANGUAGE
    )
    doc = _DOC_CHROME[resolved_language]

    template = _env.get_template(f"cv/{template_id}.html")

    # R8/KTD2: im Vorschaumodus den geteilten Beispiel-Inhalt bereitstellen,
    # wenn der Aufrufer keinen eigenen übergibt. Der Renderer ersetzt keine
    # echten Werte - die Templates entscheiden pro Feld (KTD3). Im Exportmodus
    # bleibt `sample` ungenutzt, selbst wenn ein Aufrufer es mitgibt. Die
    # Beispielsprache folgt der Dokumentsprache (KTD5).
    if preview and sample is None:
        sample = SAMPLE_DE if resolved_language == "de" else SAMPLE_EN

    skills_ctx = _skills_ctx(skills, resolved_language)
    languages_ctx = _languages_ctx(languages)
    sample_skills_ctx = (
        _skills_ctx(list(sample.get("skills", [])), resolved_language) if (preview and sample) else []
    )
    sample_languages_ctx = (
        _languages_ctx(list(sample.get("languages", []))) if (preview and sample) else []
    )

    experiences_ctx = _entries_with_date_range(experiences, resolved_language)
    education_ctx = _entries_with_date_range(education, resolved_language)
    projects_ctx = _entries_with_date_range(projects, resolved_language)

    html_content = template.render(
        full_name=full_name,
        email=email,
        phone=phone,
        address=address,
        summary=summary,
        berufsbezeichnung=berufsbezeichnung,
        experiences=experiences_ctx,
        education=education_ctx,
        skills_ctx=skills_ctx,
        sample_skills_ctx=sample_skills_ctx,
        languages_ctx=languages_ctx,
        sample_languages_ctx=sample_languages_ctx,
        projects=projects_ctx,
        photo_url=_photo_file_uri(photo_path),
        doc=doc,
        preview=preview,
        sample=sample,
    )

    try:
        pdf_bytes = HTML(
            string=html_content,
            base_url=str(_CV_TEMPLATES_DIR),
            url_fetcher=_LOCAL_ONLY_URL_FETCHER,
        ).write_pdf()
    except Exception as exc:  # noqa: BLE001 - WeasyPrint kann diverse Fehlerklassen werfen
        logger.exception("PDF-Erzeugung via WeasyPrint fehlgeschlagen.")
        raise PdfRenderError(f"PDF konnte nicht erzeugt werden: {exc}") from exc

    if not pdf_bytes:
        raise PdfRenderError("WeasyPrint lieferte ein leeres PDF-Ergebnis.")

    return pdf_bytes
