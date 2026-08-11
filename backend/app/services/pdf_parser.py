"""Service zum Einlesen und KI-gestützten Strukturieren von Lebenslauf-PDFs.

Zwei-stufiger Ablauf:

1. `extract_text_from_pdf()` - reine Textextraktion aus dem PDF via `pypdf`
   (keine externen Abhängigkeiten, deterministisch, gut testbar).
2. `analyze_cv_text()` - übergibt den Rohtext an GPT-4o (OpenAI Chat
   Completions API mit erzwungenem JSON-Output) und validiert die Antwort
   gegen das `ParsedCvProfile`-Schema.

`parse_cv_pdf()` verkettet beide Schritte für den Upload-Endpunkt.
"""
from __future__ import annotations

import json
import logging
from io import BytesIO

from openai import OpenAI, OpenAIError
from pydantic import ValidationError
from pypdf import PdfReader

from app.core.config import settings
from app.schemas.master_profile import ParsedCvProfile

logger = logging.getLogger(__name__)

# Begrenzt die an die KI gesendete Textmenge (Kosten-/Token-Schutz). Für
# einen Lebenslauf sind mehrere zehntausend Zeichen bereits sehr großzügig.
_MAX_INPUT_CHARS = 15_000

_SYSTEM_PROMPT = """\
Du bist ein präziser Assistent, der Lebensläufe (CVs) analysiert und deren \
Inhalt in strukturiertes JSON überführt.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt exakt in folgender Form \
(keine Erklärtexte, kein Markdown, keine Code-Fences):

{
  "full_name": "Vollständiger Name oder null",
  "email": "E-Mail-Adresse oder null",
  "phone": "Telefonnummer oder null",
  "address": "Postanschrift oder null",
  "summary": "Kurzes berufliches Profil/Zusammenfassung (2-4 Sätze) oder null",
  "experiences": [
    {
      "company": "Firmenname",
      "role": "Positions-/Jobtitel",
      "start_date": "z. B. 2020-01 oder 2020, oder null",
      "end_date": "z. B. 2023-06, oder null falls aktuelle Position",
      "description": "Kurzbeschreibung der Tätigkeiten/Erfolge, oder null"
    }
  ],
  "education": [
    {
      "institution": "Name der Bildungseinrichtung",
      "degree": "Abschluss, z. B. 'B.Sc. Informatik'",
      "field_of_study": "Studienfach/Schwerpunkt, oder null",
      "start_date": "oder null",
      "end_date": "oder null"
    }
  ],
  "skills": ["Skill 1", "Skill 2"]
}

Regeln:
- Erfinde keine Informationen, die nicht im Text stehen.
- Fehlende Felder werden als null (bzw. leere Liste für Arrays) gesetzt.
- "skills" enthält sowohl fachliche (z. B. Programmiersprachen, Tools) als \
auch Sprachkenntnisse/Zertifikate als einzelne kurze Strings.
- Antworte auf Deutsch, außer der Lebenslauf ist eindeutig auf Englisch \
verfasst - dann bleibe bei den Originalbegriffen.
"""


class PdfParsingError(Exception):
    """Wird ausgelöst, wenn aus der PDF-Datei kein Text extrahiert werden kann."""


class CvAnalysisError(Exception):
    """Wird ausgelöst, wenn die KI-gestützte Analyse des CV-Texts fehlschlägt."""


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extrahiert den reinen Fließtext aus einer PDF-Datei.

    Wirft `PdfParsingError`, wenn die Datei nicht lesbar ist, passwort-
    geschützt bleibt oder keinerlei extrahierbaren Text enthält (z. B. ein
    reines Bild-/Scan-PDF ohne Texterkennung).
    """
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 - jede Art von Lesefehler abfangen
        raise PdfParsingError(f"PDF konnte nicht gelesen werden: {exc}") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")  # Versuch mit leerem Passwort (häufig bei Export-PDFs)
        except Exception as exc:  # noqa: BLE001
            raise PdfParsingError(
                "Die PDF ist passwortgeschützt und konnte nicht entschlüsselt werden."
            ) from exc

    try:
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        raise PdfParsingError(f"Text konnte nicht aus der PDF extrahiert werden: {exc}") from exc

    text = "\n\n".join(page.strip() for page in pages_text if page.strip())

    if not text.strip():
        raise PdfParsingError(
            "Aus der PDF konnte kein Text extrahiert werden. "
            "Enthält die Datei nur gescannte Bilder ohne Texterkennung (OCR)?"
        )

    return text


def analyze_cv_text(raw_text: str) -> ParsedCvProfile:
    """Lässt GPT-4o den Rohtext eines Lebenslaufs in ein strukturiertes
    `ParsedCvProfile` überführen."""
    if not settings.OPENAI_API_KEY:
        raise CvAnalysisError(
            "OPENAI_API_KEY ist nicht konfiguriert - die KI-gestützte CV-Analyse "
            "ist nicht verfügbar. Bitte in der .env hinterlegen."
        )

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw_text[:_MAX_INPUT_CHARS]},
            ],
        )
    except OpenAIError as exc:
        logger.exception("OpenAI-Aufruf zur CV-Analyse fehlgeschlagen.")
        raise CvAnalysisError(f"KI-Analyse des Lebenslaufs fehlgeschlagen: {exc}") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise CvAnalysisError("Die KI-Antwort enthielt keine Daten.")

    try:
        raw_json = json.loads(content)
    except json.JSONDecodeError as exc:
        raise CvAnalysisError("Die KI-Antwort war kein valides JSON.") from exc

    try:
        return ParsedCvProfile.model_validate(raw_json)
    except ValidationError as exc:
        logger.warning("KI-Antwort entsprach nicht dem erwarteten Profil-Schema: %s", exc)
        raise CvAnalysisError(
            "Die KI-Antwort entsprach nicht dem erwarteten Profil-Schema."
        ) from exc


def parse_cv_pdf(file_bytes: bytes) -> ParsedCvProfile:
    """End-to-End: PDF-Bytes -> Rohtext (pypdf) -> strukturiertes Profil (GPT-4o)."""
    raw_text = extract_text_from_pdf(file_bytes)
    return analyze_cv_text(raw_text)
