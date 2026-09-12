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

from app.services.cv_sample_content import SAMPLE

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
CvTemplateId = Literal["classic", "template-1"]

CV_TEMPLATES: list[dict[str, str]] = [
    {"id": "classic", "label": "Classic"},
    {"id": "template-1", "label": "Template 1"},
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


def _format_date_range(start: str | None, end: str | None) -> str:
    """Formatiert einen Start-/End-Zeitraum als lesbaren String, z. B.
    '2021 – 2024' oder 'seit 2021'."""
    if not start and not end:
        return ""
    if start and not end:
        return f"seit {start}"
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


# Sortierschlüssel für den repräsentativen Kompetenzgrad einer Skill-Gruppe
# (der höchste in der Gruppe vertretene Grad bestimmt die Balkenlänge).
_SKILL_LEVEL_ORDER: dict[str, int] = {
    "Grundkenntnisse": 0,
    "Gut": 1,
    "Sehr gut": 2,
    "Experte": 3,
}

# Englische Anzeige-Labels für die intern deutsch gehaltenen `SkillLevel`-
# Werte: der CV wird immer auf Englisch erzeugt (die Enum-Werte bleiben
# unverändert, damit Schema/Migration/Frontend-Formular stabil bleiben).
_SKILL_LEVEL_LABELS_EN: dict[str, str] = {
    "Grundkenntnisse": "Basic",
    "Gut": "Good",
    "Sehr gut": "Very good",
    "Experte": "Expert",
}

# Fallback-Kategorie für Skills ohne (oder mit unbekannter) `category` -
# insbesondere Altdaten aus der Zeit vor der Kategorie-Einführung.
_OTHER_SKILL_CATEGORY = "Other"


def group_skills(skills: list[Any]) -> list[dict[str, Any]]:
    """Gruppiert Skills nach `category` für die CV-Vorlagen.

    Statt einer langen, flachen Liste rendert jede Vorlage je Kategorie eine
    kompakte Zeile (siehe R9-Folge). Die Gruppen behalten die Reihenfolge des
    ersten Auftretens bei; Skills ohne `category` landen in einer
    `Other`-Gruppe. `level` ist der höchste in der Gruppe vertretene
    Kompetenzgrad - die Vorlagen nutzen ihn als Balkenlänge (das per-Skill-
    Niveau wird zugunsten der kompakten Darstellung nicht einzeln gezeigt);
    `level_label` ist die englische Anzeigeform davon.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        entry = _entry_dict(skill)
        category = entry.get("category") or _OTHER_SKILL_CATEGORY
        groups.setdefault(category, []).append(entry)

    grouped: list[dict[str, Any]] = []
    for category, entries in groups.items():
        representative = max(
            entries, key=lambda entry: _SKILL_LEVEL_ORDER.get(entry.get("level"), 0)
        )
        level = representative.get("level")
        grouped.append(
            {
                "category": category,
                "skills": entries,
                "level": level,
                "level_label": _SKILL_LEVEL_LABELS_EN.get(level, level or ""),
            }
        )
    return grouped


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
    preview: bool = False,
    sample: Mapping[str, Any] | None = None,
) -> bytes:
    """Rendert den Lebenslauf als PDF (bytes).

    `template_id` wählt eines der `templates/cv/*.html`-Templates (R9).
    `full_name`/`email`/`phone`/`address` sind die serverseitig aus dem
    gespeicherten `MasterProfile` gemergten Identitätsfelder (KTD11);
    `photo_path` ist der Dateisystempfad des gespeicherten Profilfotos
    (oder `None`) - anders als die übrigen Inhaltsfelder kommt das Foto
    NICHT aus dem Request-Body, da es bereits beim Upload persistiert wird
    (siehe `app.api.cv_builder`).
    """
    template = _env.get_template(f"cv/{template_id}.html")

    # R8/KTD2: im Vorschaumodus den geteilten Beispiel-Inhalt bereitstellen,
    # wenn der Aufrufer keinen eigenen übergibt. Der Renderer ersetzt keine
    # echten Werte - die Templates entscheiden pro Feld (KTD3). Im Exportmodus
    # bleibt `sample` ungenutzt, selbst wenn ein Aufrufer es mitgibt.
    if preview and sample is None:
        sample = SAMPLE

    sample_skill_groups = (
        group_skills(list(sample.get("skills", []))) if (preview and sample) else []
    )
    skill_groups = group_skills(skills)

    experiences_ctx = [
        {**_entry_dict(exp), "date_range": _format_date_range(exp.start_date, exp.end_date)}
        for exp in experiences
    ]
    education_ctx = [
        {**_entry_dict(edu), "date_range": _format_date_range(edu.start_date, edu.end_date)}
        for edu in education
    ]
    projects_ctx = [
        {**_entry_dict(proj), "date_range": _format_date_range(proj.start_date, proj.end_date)}
        for proj in projects
    ]

    html_content = template.render(
        full_name=full_name,
        email=email,
        phone=phone,
        address=address,
        summary=summary,
        berufsbezeichnung=berufsbezeichnung,
        experiences=experiences_ctx,
        education=education_ctx,
        skills=[_entry_dict(skill) for skill in skills],
        skill_groups=skill_groups,
        sample_skill_groups=sample_skill_groups,
        languages=[_entry_dict(lang) for lang in languages],
        projects=projects_ctx,
        photo_url=_photo_file_uri(photo_path),
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
