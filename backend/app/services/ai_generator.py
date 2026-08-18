"""Service zur KI-gestützten Generierung von Bewerbungsunterlagen.

Nimmt das `MasterProfile` und ein ausgewähltes `JobOffer` entgegen und lässt
das LLM (via Ollama) daraus ein maßgeschneidertes Anschreiben sowie eine auf
die Stelle zugeschnittene Auswahl/Formulierung der Lebenslauf-Stationen
erzeugen.

Kontaktdaten (Name, E-Mail, Telefon, Adresse) werden NICHT von der KI
generiert, sondern deterministisch aus dem Profil übernommen - so können bei
diesen sicherheitsrelevanten Feldern keine Halluzinationen auftreten.
"""
from __future__ import annotations

import json
import logging

from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.schemas.generation import AiGenerationResult, TailoredCv
from app.services import llm_client
from app.services.llm_client import LlmUnavailableError, LlmValidationError

logger = logging.getLogger(__name__)

# Begrenzt die an die KI gesendete Stellenbeschreibung (Kosten-/Token-Schutz).
_MAX_JOB_DESCRIPTION_CHARS = 6_000

_SYSTEM_PROMPT = """\
Du bist ein erfahrener Karriereberater und Texter für Bewerbungsunterlagen \
im deutschsprachigen Raum.

Du erhältst das Profil eines Bewerbers sowie eine Zielstelle (jeweils als \
JSON). Erstelle daraus:

1. Ein maßgeschneidertes, überzeugendes Anschreiben auf Deutsch, das \
konkret auf die Stellenanzeige eingeht.
2. Lebenslauf-Inhalte, zugeschnitten auf die Zielstelle: eine kurze \
berufliche Zusammenfassung, eine nach Relevanz sortierte Auswahl/Formulierung \
der Berufserfahrungen, die Ausbildungsstationen sowie eine nach Relevanz \
sortierte Auswahl der wichtigsten Skills.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt exakt in folgender Form \
(keine Erklärtexte, kein Markdown, keine Code-Fences):

{
  "cover_letter_text": "Betreff: Bewerbung als <Position>\\n\\nSehr geehrte Damen und Herren,\\n\\n<3-5 überzeugende Absätze mit klarem Bezug zur Stellenanzeige>\\n\\nMit freundlichen Grüßen\\n<Vollständiger Name des Bewerbers>",
  "cv_content": {
    "summary": "2-3 Sätze berufliches Profil, zugeschnitten auf die Zielstelle",
    "experiences": [
      {"company": "...", "role": "...", "start_date": "...", "end_date": "...", "description": "..."}
    ],
    "education": [
      {"institution": "...", "degree": "...", "field_of_study": "...", "start_date": "...", "end_date": "..."}
    ],
    "skills": ["..."]
  }
}

Regeln:
- Erfinde KEINE Fakten (Firmen, Zeiträume, Abschlüsse, Institutionen), die \
nicht im Bewerberprofil stehen. Du darfst vorhandene Erfahrungen/Ausbildungs- \
stationen auswählen, umformulieren und nach Relevanz sortieren, aber keine \
neuen erfinden.
- Ist im Profil keine Erfahrung/Ausbildung vorhanden, gib eine leere Liste \
zurück statt Platzhalter zu erfinden.
- Ist keine Ansprechperson aus der Stellenbeschreibung erkennbar, nutze \
"Sehr geehrte Damen und Herren" als Anrede.
- Der Name in der Grußformel ist der vollständige Name aus dem Bewerberprofil.
- "skills" enthält eine auf die Stelle zugeschnittene Auswahl aus den im \
Profil vorhandenen Skills (keine neuen erfinden).
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


def generate_application_content(
    profile: MasterProfile, job_offer: JobOffer
) -> tuple[str, TailoredCv]:
    """Erzeugt Anschreiben-Text und maßgeschneiderten Lebenslauf für `job_offer`.

    Gibt ein Tupel `(cover_letter_text, tailored_cv)` zurück. Wirft
    `ApplicationGenerationError`, wenn Ollama nicht erreichbar ist oder
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

    tailored_cv = TailoredCv(
        full_name=profile.full_name,
        email=profile.email,
        phone=profile.phone,
        address=profile.address,
        summary=result.cv_content.summary,
        experiences=result.cv_content.experiences,
        education=result.cv_content.education,
        skills=result.cv_content.skills,
    )

    return result.cover_letter_text, tailored_cv
