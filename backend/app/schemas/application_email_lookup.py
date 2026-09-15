"""Pydantic-Schemas für die On-Demand-Bewerbungs-E-Mail-Suche.

`ApplicationEmailLookupRequest` ist der Job-Payload, den beide Oberflächen
(Job-Suchkarte und Sendedialog) senden (KTD1). `ApplicationEmailLookupResult`
ist das Ergebnis mit genau einem von drei Status: `found`, `not-found` oder
`failed` (A5/KTD4) - `failed` (Fetch-/Deadline-Fehler) wird von
`not-found` (Suche abgeschlossen, keine Adresse) unterschieden.
"""
from typing import Literal

from pydantic import BaseModel, Field


class ApplicationEmailLookupRequest(BaseModel):
    """Job-Payload für die Bewerbungs-E-Mail-Suche."""

    source_url: str = Field(..., max_length=1024)
    company: str = Field(..., max_length=255)
    # `force=True` überspringt die Persistiert-zuerst-Auslese im Endpoint und
    # lässt den Scraper tatsächlich erneut laufen (Default unverändert `False`).
    force: bool = False


class ApplicationEmailLookupResult(BaseModel):
    """Ergebnis der Suche: genau eine gefundene Adresse oder ein expliziter
    Nicht-gefunden-/Fehler-Status (R6/A5)."""

    status: Literal["found", "not-found", "failed"]
    email: str | None = None
    source_url: str | None = None
