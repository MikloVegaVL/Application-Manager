"""Pydantic-Schemas für den Portal-Auto-Fill-Agenten (U5: Freitext-Antworten;
U6: Start/Status-Request-/Response-Schemas für `app.api.portal_fill`).

Siehe `app.services.portal_agents.answering`.
"""
from pydantic import BaseModel


class PortalAnswerResult(BaseModel):
    """Rohes Ergebnis des LLM-Aufrufs für EINE Freitext-Frage eines
    Portal-Formulars (siehe `_SYSTEM_PROMPT` in `portal_agents/answering.py`).

    `insufficient_information` (KTD6): das LLM setzt es auf `True`, wenn die
    Frage nicht allein aus dem Profil beantwortet werden kann (z. B. eine
    übersehene Screening-Frage). Ein solcher Lauf pausiert statt eine
    erfundene Antwort zu füllen."""

    answer: str
    insufficient_information: bool = False


class PortalFillStartRequest(BaseModel):
    """Payload für `POST /api/applications/{id}/portal-fill/start`."""

    application_form_url: str
    # KTD4: füllt das Formular, pausiert aber VOR dem Submit - ein
    # Validierungslauf, der erst nach explizitem Resume wirklich sendet.
    dry_run: bool = False


class PortalFillStatusResponse(BaseModel):
    """Antwortmodell für `GET /api/applications/{id}/portal-fill/status` -
    direkt aus den `Application`-Spalten (siehe `app.models.application`).

    `failure_class` ist NUR gesetzt, wenn `automation_state == "failed"`
    (KTD1/KTD5) - ein Pausen-Grund darf nie als terminaler Fehler gelesen
    werden."""

    automation_state: str | None = None
    action_needed_reason: str | None = None
    action_needed_detail: str | None = None
    failure_class: str | None = None
