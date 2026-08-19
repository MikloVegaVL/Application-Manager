"""Pydantic-Schemas für die KI-gestützte Bewerbungsgenerierung
(siehe `app.services.ai_generator`).

Die KI generiert ausschließlich das Anschreiben - der Lebenslauf wird nicht
mehr KI-generiert/gerendert, sondern vom Nutzer als eigene Datei im Profil
hochgeladen und beim Versand als Anhang verwendet (siehe `app.api.profile`,
`app.api.applications.send_application`).
"""
from pydantic import BaseModel


class AiGenerationResult(BaseModel):
    """Rohes Ergebnis des LLM-Aufrufs (siehe `_SYSTEM_PROMPT` in `ai_generator.py`)."""

    cover_letter_text: str
