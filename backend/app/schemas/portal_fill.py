"""Pydantic-Schemas für den Portal-Auto-Fill-Agenten (U5: Freitext-Antworten).

Siehe `app.services.portal_agents.answering`.
"""
from pydantic import BaseModel


class PortalAnswerResult(BaseModel):
    """Rohes Ergebnis des LLM-Aufrufs für EINE Freitext-Frage eines
    Portal-Formulars (siehe `_SYSTEM_PROMPT` in `portal_agents/answering.py`)."""

    answer: str
