"""Service zum Einlesen und KI-gestützten Strukturieren von Lebenslauf-PDFs.

Zwei-stufiger Ablauf:

1. `extract_text_from_pdf()` - reine Textextraktion aus dem PDF via `pypdf`
   (keine externen Abhängigkeiten, deterministisch, gut testbar).
2. `analyze_cv_text()` - übergibt den Rohtext an den gemeinsamen Ollama-
   Aufruf-Helfer (`app.services.llm_client`) und erhält eine bereits gegen
   das `ParsedCvProfile`-Schema validierte Antwort zurück.

`parse_cv_pdf()` verkettet beide Schritte für den Upload-Endpunkt.
"""
from __future__ import annotations

import logging
from io import BytesIO

from pypdf import PdfReader

from app.core.config import settings
from app.schemas.master_profile import DocumentLanguage, ParsedCvProfile
from app.services import llm_client
from app.services.llm_client import LlmUnavailableError, LlmValidationError

logger = logging.getLogger(__name__)

# Begrenzt die an die KI gesendete Textmenge (Kosten-/Token-Schutz). Für
# einen Lebenslauf sind mehrere zehntausend Zeichen bereits sehr großzügig.
_MAX_INPUT_CHARS = 15_000

# R10 (Global Language Unification, 2026-09-13): Die Extraktion folgt der
# gewünschten Sprache statt immer Englisch zu erzwingen. `{language}` wird per
# `str.replace` ersetzt (nicht `.format`), weil der Prompt JSON-Klammern
# enthält. Default bleibt Deutsch (App-Standardsprache).
_DEFAULT_PARSE_LANGUAGE: DocumentLanguage = "de"
_LANGUAGE_NAMES: dict[DocumentLanguage, str] = {"de": "GERMAN", "en": "ENGLISH"}

_SYSTEM_PROMPT_TEMPLATE = """\
You are a precise assistant that analyses résumés (CVs) and turns their \
content into structured JSON.

Answer EXCLUSIVELY with a JSON object in exactly the following shape \
(no prose, no markdown, no code fences):

{
  "full_name": "Full name or null",
  "email": "Email address or null",
  "phone": "Phone number or null",
  "address": "Postal address or null",
  "summary": "Short professional profile/summary (2-4 sentences) or null",
  "experiences": [
    {
      "company": "Company name",
      "role": "Position/job title",
      "start_date": "e.g. 2020-01 or 2020, or null",
      "end_date": "e.g. 2023-06, or null for a current position",
      "description": "Short description of responsibilities/achievements, or null"
    }
  ],
  "education": [
    {
      "institution": "Name of the educational institution",
      "degree": "Degree, e.g. 'B.Sc. Computer Science'",
      "field_of_study": "Field of study/specialisation, or null",
      "start_date": "or null",
      "end_date": "or null"
    }
  ],
  "skills": [
    {
      "name": "Skill name"
    }
  ],
  "projects": [
    {
      "title": "Project name",
      "description": "Short project description",
      "start_date": "e.g. 2020-01 or 2020, or null",
      "end_date": "e.g. 2023-06, or null if ongoing",
      "link": "URL to the project (e.g. GitHub, portfolio), or null"
    }
  ]
}

Rules:
- Do not invent information that is not in the text.
- Missing fields are set to null (or an empty list for arrays).
- ALWAYS write all generated text values (summary, descriptions, roles, \
degrees, skill names, project titles) in {language}, even if the source CV is \
written in another language. Translate as needed; keep proper nouns \
(company/institution names, product names, URLs) unchanged.
- "skills" contains both technical skills (e.g. programming languages, tools) \
and language skills/certificates as individual short strings.
- "projects" contains standalone projects (e.g. open-source, study, \
portfolio or side projects), NOT the regular positions from "experiences".
"""


def _build_system_prompt(language: DocumentLanguage) -> str:
    """Baut den CV-Analyse-Prompt für die gewünschte Ausgabesprache (R10)."""
    language_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES[_DEFAULT_PARSE_LANGUAGE])
    return _SYSTEM_PROMPT_TEMPLATE.replace("{language}", language_name)


# Prompt der App-Standardsprache (Deutsch) - für Aufrufer/Tests, die keinen
# expliziten Sprachparameter setzen.
_SYSTEM_PROMPT = _build_system_prompt(_DEFAULT_PARSE_LANGUAGE)


# Felder, für die eine leere KI-Antwort dem Nutzer als Warnung gemeldet wird
# (siehe `CvParseResponse.warnings`) - bewusst nur die inhaltlich substanziellen
# Felder, nicht Telefon/Adresse, die auf vielen Lebensläufen legitim fehlen.
# Ursprünglich Teil von `app.api.profile.upload_cv` (siehe ce-debug-
# Untersuchung, 2026-08-18), hierher verschoben mit U3 (Wegfall des
# Auto-Merge-Endpunkts) - `missing_field_warnings` ist jetzt reine
# Parse-Diagnostik ohne jeden Merge-/Speicher-Bezug.
_WARNING_LABELS: dict[str, str] = {
    "summary": "Kein Kurzprofil/Zusammenfassung gefunden.",
    "experiences": "Keine Berufserfahrung gefunden.",
    "education": "Keine Ausbildung gefunden.",
    "skills": "Keine Skills gefunden.",
    "projects": "Keine Projekte gefunden.",
}


def missing_field_warnings(parsed: ParsedCvProfile) -> list[str]:
    """Baut die Warnungsliste für `CvParseResponse` (siehe ce-debug-
    Untersuchung, 2026-08-18): Ein unvollständiger Parse - z. B. keine
    erkannte Berufserfahrung - blieb früher unsichtbar für den Nutzer. Da
    `POST /cv-builder/parse` (anders als das frühere `upload_cv`) ohnehin
    nichts speichert (R6), geht es hier nur noch darum, transparent zu
    machen, welche Felder die KI leer zurückgab, damit der Nutzer im
    Builder-Formular gezielt nachbessern kann."""
    return [message for field, message in _WARNING_LABELS.items() if not getattr(parsed, field)]


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


def analyze_cv_text(
    raw_text: str, *, language: DocumentLanguage = _DEFAULT_PARSE_LANGUAGE
) -> ParsedCvProfile:
    """Lässt Ollama den Rohtext eines Lebenslaufs in ein strukturiertes
    `ParsedCvProfile` überführen. `language` steuert, in welcher Sprache die
    extrahierten Textwerte ausgegeben werden (R10)."""
    messages = [
        {"role": "system", "content": _build_system_prompt(language)},
        {"role": "user", "content": raw_text[:_MAX_INPUT_CHARS]},
    ]

    try:
        # Eigenes, kleineres Modell nur für die CV-Analyse, unabhängig vom
        # allgemeinen OLLAMA_MODEL-Default (siehe settings.OLLAMA_MODEL_CV_PARSING
        # und ce-debug-Untersuchung, 2026-08-18).
        result = llm_client.generate_structured(
            ParsedCvProfile, messages, model=settings.OLLAMA_MODEL_CV_PARSING
        )
    except LlmValidationError as exc:
        logger.warning("KI-Antwort entsprach nicht dem erwarteten Profil-Schema: %s", exc)
        raise CvAnalysisError(
            "Die KI-Antwort entsprach nicht dem erwarteten Profil-Schema."
        ) from exc
    except LlmUnavailableError as exc:
        logger.exception("Ollama-Aufruf zur CV-Analyse fehlgeschlagen.")
        raise CvAnalysisError(f"KI-Analyse des Lebenslaufs fehlgeschlagen: {exc}") from exc

    return result


def parse_cv_pdf(
    file_bytes: bytes, *, language: DocumentLanguage = _DEFAULT_PARSE_LANGUAGE
) -> ParsedCvProfile:
    """End-to-End: PDF-Bytes -> Rohtext (pypdf) -> strukturiertes Profil
    (Ollama). `language` wird an `analyze_cv_text` durchgereicht (R10)."""
    raw_text = extract_text_from_pdf(file_bytes)
    return analyze_cv_text(raw_text, language=language)
