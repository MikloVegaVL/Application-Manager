"""Pydantic-Schemas für den Portal-Auto-Fill-Agenten (U5: Freitext-Antworten;
U6: Start/Status-Request-/Response-Schemas für `app.api.portal_fill`).

Siehe `app.services.portal_agents.answering`.
"""
from pydantic import BaseModel


class PortalAnswerResult(BaseModel):
    """Rohes Ergebnis des LLM-Aufrufs für EINE Freitext-Frage eines
    Portal-Formulars (siehe `_SYSTEM_PROMPT` in `portal_agents/answering.py`)."""

    answer: str


class PortalFillStartRequest(BaseModel):
    """Payload für `POST /api/applications/{id}/portal-fill/start`."""

    application_form_url: str


class PortalFillStatusResponse(BaseModel):
    """Antwortmodell für `GET /api/applications/{id}/portal-fill/status` -
    direkt aus den `Application`-Spalten (siehe `app.models.application`)."""

    automation_state: str | None = None
    action_needed_reason: str | None = None
