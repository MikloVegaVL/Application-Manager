"""Client für Arbeitnows offene Jobsuche-API (Deutschland/EU).

Arbeitnow bündelt Stellenanzeigen aus mehreren ATS-Plattformen (u. a.
Personio, Greenhouse, SmartRecruiters, Lever) zu einer einheitlichen,
öffentlichen JSON-API ohne API-Key oder Nutzerkonto (R4) - dieselbe
Integrationsform wie `ArbeitsagenturJobsClient` (KTD2), kein Enable-Flag,
kein `is_configured()`.

Die API bietet keine serverseitigen `keywords`/`location`-Suchparameter -
nur `remote` und `visa_sponsorship` sind dokumentiert -, daher filtert dieser
Client die Treffer der ersten Seite client-seitig nach Stichwort und Ort
(KTD3). Eine Seite liefert laut `meta.per_page` 250 Einträge (live
verifiziert, 2026-09-15) - für eine einzelne Suche reicht das aus, eine
zweite Seite abzurufen ist nicht nötig.

Die quellenübergreifende Maschinerie (User-Agent, URL-Validierung,
HTML-Stripping, Cooldown) liegt in `job_sources/shared.py` und wird von hier
nur konsumiert.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import (
    DEFAULT_USER_AGENT,
    CooldownMixin,
    strip_html,
    validate_source_url,
)

logger = logging.getLogger(__name__)


class ArbeitnowJobsClient(CooldownMixin):
    """Client für Arbeitnows offene, keyless Jobsuche-API."""

    SOURCE_PLATFORM = "arbeitnow"
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
    _DEFAULT_RESULT_CAP = 25
    _DEFAULT_COOLDOWN_SECONDS = 300.0

    def __init__(
        self,
        timeout: float = 10.0,
        result_cap: int = _DEFAULT_RESULT_CAP,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._timeout = timeout
        self._result_cap = result_cap
        self._cooldown_seconds = cooldown_seconds
        self._headers = {
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über Arbeitnows offene API.

        Kein `is_configured()`-Gate (KTD2) - die API braucht keine
        Zugangsdaten. 429 aktiviert einen Cooldown und liefert eine leere
        Liste (der Orchestrator kennzeichnet das als "rate-limited"); echte
        Fehler (Netzwerk, unerwarteter HTTP-Status, ungültiges JSON) werden
        als Exception nach oben gereicht, damit der Orchestrator sie als
        "error" kennzeichnet.
        """
        if self._in_cooldown():
            logger.info("Arbeitnow-Client: aktiver Cooldown - Anfrage übersprungen.")
            return []

        try:
            response = requests.get(
                self.BASE_URL,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("Arbeitnow-API nicht erreichbar (%s).", type(exc).__name__)
            raise RuntimeError("Arbeitnow-API nicht erreichbar.") from None

        if response.status_code == 429:
            logger.warning(
                "Arbeitnow-API hat rate-limitiert (429) - aktiviere Cooldown (%.0fs).",
                self._cooldown_seconds,
            )
            self._set_cooldown()
            return []

        if response.status_code >= 400:
            logger.warning(
                "Arbeitnow-API lieferte Fehlerstatus (HTTP %s).", response.status_code
            )
            raise RuntimeError(
                f"Arbeitnow-API lieferte Fehlerstatus (HTTP {response.status_code})."
            )

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Arbeitnow-API lieferte kein valides JSON zurück.")
            raise RuntimeError("Arbeitnow-API lieferte kein valides JSON zurück.") from None

        raw_results = payload.get("data") or []
        keyword_terms = [term.lower() for term in keywords.split() if term]
        location_term = location.strip().lower() if location and location.strip() else None

        offers: list[JobOfferCreate] = []
        for raw in raw_results:
            if not self._matches(raw, keyword_terms, location_term):
                continue
            try:
                offer = self._map_offer(raw)
            except Exception:  # noqa: BLE001 - ein defekter Datensatz darf die Suche nicht stoppen
                logger.exception("Konnte Arbeitnow-Angebot nicht verarbeiten.")
                continue
            if offer is not None:
                offers.append(offer)
            if len(offers) >= self._result_cap:
                break
        return offers

    # --- Client-seitige Filterung (KTD3) ---------------------------------

    @staticmethod
    def _matches(
        raw: dict[str, Any],
        keyword_terms: list[str],
        location_term: str | None,
    ) -> bool:
        """Filtert client-seitig, da die API keine `keywords`/`location`-
        Query-Parameter kennt (KTD3). Jeder Stichwort-Teilbegriff muss in
        Titel, Beschreibung oder Firmenname vorkommen (UND-Verknüpfung)."""
        if keyword_terms:
            haystack = " ".join(
                str(raw.get(field, "")) for field in ("title", "description", "company_name")
            ).lower()
            if not all(term in haystack for term in keyword_terms):
                return False
        if location_term:
            offer_location = str(raw.get("location") or "").lower()
            if location_term not in offer_location:
                return False
        return True

    # --- Mapping ----------------------------------------------------------

    def _map_offer(self, raw: dict[str, Any]) -> JobOfferCreate | None:
        title = raw.get("title")
        source_url = raw.get("url")
        if not title or not validate_source_url(source_url):
            return None

        company = raw.get("company_name") or "Unbekanntes Unternehmen"
        location = raw.get("location")

        return JobOfferCreate(
            title=str(title).strip(),
            company=str(company).strip(),
            location=str(location).strip() if location else None,
            source_url=source_url,
            description_text=strip_html(raw.get("description")),
            source_platform=self.SOURCE_PLATFORM,
        )
