"""Service zur KI-gestützten Generierung von Bewerbungsunterlagen.

Nimmt das `MasterProfile` und ein ausgewähltes `JobOffer` entgegen und lässt
das LLM (via Ollama) daraus ein maßgeschneidertes Anschreiben erzeugen.

Der Lebenslauf wird NICHT mehr von der KI generiert/gerendert - der Nutzer
lädt seinen eigenen Lebenslauf als Datei im Profil hoch, die unverändert als
E-Mail-Anhang verwendet wird (siehe `app.api.profile`,
`app.api.applications.send_application`).
"""
from __future__ import annotations

import json
import logging

from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.schemas.generation import AiGenerationResult
from app.services import llm_client
from app.services.llm_client import LlmUnavailableError, LlmValidationError

logger = logging.getLogger(__name__)

# Begrenzt die an die KI gesendete Stellenbeschreibung (Kosten-/Token-Schutz).
_MAX_JOB_DESCRIPTION_CHARS = 6_000

_SYSTEM_PROMPT = """\
Du bist ein erfahrener Karriereberater und Texter für Bewerbungsunterlagen \
im deutschsprachigen Raum.

Du erhältst das Profil eines Bewerbers sowie eine Zielstelle (jeweils als \
JSON). Erstelle daraus ein maßgeschneidertes, überzeugendes Anschreiben auf \
Deutsch, das konkret auf die Stellenanzeige eingeht.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt exakt in folgender Form \
(keine Erklärtexte, kein Markdown, keine Code-Fences):

{
  "cover_letter_text": "Betreff: Bewerbung als <Position>\\n\\nSehr geehrte Damen und Herren,\\n\\n<3-5 überzeugende Absätze mit klarem Bezug zur Stellenanzeige>\\n\\nMit freundlichen Grüßen\\n<Vollständiger Name des Bewerbers>"
}

Regeln:
- Erfinde KEINE Fakten (Firmen, Zeiträume, Abschlüsse, Institutionen), die \
nicht im Bewerberprofil stehen.
- Ist keine Ansprechperson aus der Stellenbeschreibung erkennbar, nutze \
"Sehr geehrte Damen und Herren" als Anrede.
- Der Name in der Grußformel ist der vollständige Name aus dem Bewerberprofil.
"""


class ApplicationGenerationError(Exception):
    """Wird ausgelöst, wenn die KI-gestützte Generierung fehlschlägt."""


def _build_user_prompt(profile: MasterProfile, job_offer: JobOffer) -> str:
    profile_payload = {
        "full_name": profile.full_name,
        "summary": profile.summary,
        "experiences": profile.experiences_json,
        "education": profile.education_json,
        "skills": profile.skills_json,
    }
    job_payload = {
        "title": job_offer.title,
        "company": job_offer.company,
        "location": job_offer.location,
        "description": (job_offer.description_text or "")[:_MAX_JOB_DESCRIPTION_CHARS],
    }
    return (
        "Bewerberprofil (JSON):\n"
        f"{json.dumps(profile_payload, ensure_ascii=False, indent=2)}\n\n"
        "Zielstelle (JSON):\n"
        f"{json.dumps(job_payload, ensure_ascii=False, indent=2)}"
    )


def generate_application_content(profile: MasterProfile, job_offer: JobOffer) -> str:
    """Erzeugt den Anschreiben-Text für `job_offer`.

    Wirft `ApplicationGenerationError`, wenn Ollama nicht erreichbar ist oder
    keine gültige KI-Antwort zustande kam.
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(profile, job_offer)},
    ]

    try:
        result = llm_client.generate_structured(AiGenerationResult, messages)
    except LlmValidationError as exc:
        logger.warning("KI-Antwort entsprach nicht dem erwarteten Schema: %s", exc)
        raise ApplicationGenerationError(
            "Die KI-Antwort entsprach nicht dem erwarteten Schema."
        ) from exc
    except LlmUnavailableError as exc:
        logger.exception("Ollama-Aufruf zur Bewerbungsgenerierung fehlgeschlagen.")
        raise ApplicationGenerationError(f"KI-Generierung fehlgeschlagen: {exc}") from exc

    return result.cover_letter_text
