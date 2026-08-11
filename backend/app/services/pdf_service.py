"""Service zur PDF-Erstellung der Bewerbungsmappe (Anschreiben + Lebenslauf).

Rendert ein Jinja2-HTML/CSS-Template (DIN-5008-orientiertes Anschreiben-
Layout, gefolgt vom Lebenslauf auf eigener Seite) mit den generierten/
kuratierten Bewerbungsdaten und konvertiert das Ergebnis via WeasyPrint zu
PDF-Bytes. Beide Dokumente werden bewusst als EIN zusammenhängendes PDF
gerendert (statt zwei separate Dateien zu erzeugen und zu mergen), damit
Layout und Seitennummerierung durchgängig konsistent bleiben.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.models.job_offer import JobOffer
from app.schemas.generation import TailoredCv

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


class PdfRenderError(Exception):
    """Wird ausgelöst, wenn die PDF-Erzeugung fehlschlägt."""


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


def render_application_pdf(
    cover_letter_text: str,
    cv: TailoredCv,
    job_offer: JobOffer,
) -> bytes:
    """Rendert Anschreiben + Lebenslauf als ein zusammenhängendes PDF (bytes)."""
    template = _env.get_template("application.html")

    experiences = [
        {**exp.model_dump(), "date_range": _format_date_range(exp.start_date, exp.end_date)}
        for exp in cv.experiences
    ]
    education = [
        {**edu.model_dump(), "date_range": _format_date_range(edu.start_date, edu.end_date)}
        for edu in cv.education
    ]

    html_content = template.render(
        cv=cv,
        experiences=experiences,
        education=education,
        recipient={"company": job_offer.company, "location": job_offer.location},
        cover_letter_text=cover_letter_text,
        date=date.today().strftime("%d.%m.%Y"),
    )

    try:
        pdf_bytes = HTML(string=html_content, base_url=str(_TEMPLATES_DIR)).write_pdf()
    except Exception as exc:  # noqa: BLE001 - WeasyPrint kann diverse Fehlerklassen werfen
        logger.exception("PDF-Erzeugung via WeasyPrint fehlgeschlagen.")
        raise PdfRenderError(f"PDF konnte nicht erzeugt werden: {exc}") from exc

    if not pdf_bytes:
        raise PdfRenderError("WeasyPrint lieferte ein leeres PDF-Ergebnis.")

    return pdf_bytes
