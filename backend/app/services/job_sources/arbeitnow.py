"""Client für Arbeitnows offene Jobsuche-API (Deutschland/EU).

Arbeitnow bündelt Stellenanzeigen aus mehreren ATS-Plattformen (u. a.
Personio, Greenhouse, SmartRecruiters, Lever) zu einer einheitlichen,
öffentlichen JSON-API ohne API-Key oder Nutzerkonto (R4) - dieselbe
Integrationsform wie `ArbeitsagenturJobsClient` (KTD2), kein Enable-Flag,
kein `is_configured()`.

Die API bietet keine serverseitigen `keywords`/`location`-Suchparameter -
nur `remote` und `visa_sponsorship` sind dokumentiert. Die Stichwort-Filterung
läuft seit dem Plan
docs/plans/2026-09-15-003-feat-job-search-source-and-relevance-plan.md
(R8/KTD9/KTD10) nicht mehr hier, sondern zentral für alle Quellen in
`JobSearchService._apply_relevance_filter` (title/description, KEIN
`company_name`-Abgleich mehr - eine bewusste, akzeptierte Verengung).
`location` kennt der zentrale Filter dagegen nicht; dieser Client filtert
Treffer der ersten Seite weiterhin client-seitig nach Ort (KTD9). Eine Seite
liefert laut `meta.per_page` 250 Einträge (live verifiziert, 2026-09-15) -
für eine einzelne Suche reicht das aus, eine zweite Seite abzurufen ist nicht
nötig.

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
    _DEFAULT_COOLDOWN_SECONDS = 300.0

    def __init__(
        self,
        timeout: float = 10.0,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._timeout = timeout
        self._cooldown_seconds = cooldown_seconds
        self._headers = {
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

    def search(
        self,
        keywords: str,
        location: str | None = None,
        radius_km: int | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über Arbeitnows offene API.

        `radius_km` wird angenommen, aber ignoriert: die API kennt keinen
        Umkreis-Parameter, und der Ort wird ohnehin nur client-seitig per
        Substring gefiltert (siehe `_matches_location`).

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
        location_term = location.strip().lower() if location and location.strip() else None

        # Kein `result_cap`-Abbruch mehr (anders als vor diesem Plan): die
        # Seite hat kein serverseitiges Keyword-Relevanz-Ranking, also würde
        # ein früher Abbruch nach den ersten N Treffern in API-Reihenfolge
        # - VOR dem zentralen Relevanzfilter (R6/R7) - echte Treffer aus dem
        # Rest der Seite verlieren, statt nur die uninteressantesten zu
        # verwerfen. Adzuna/Jooble dürfen weiterhin serverseitig cappen, weil
        # deren Suche bereits relevanzsortiert antwortet.
        offers: list[JobOfferCreate] = []
        for raw in raw_results:
            if not self._matches_location(raw, location_term):
                continue
            try:
                offer = self._map_offer(raw)
            except Exception:  # noqa: BLE001 - ein defekter Datensatz darf die Suche nicht stoppen
                logger.exception("Konnte Arbeitnow-Angebot nicht verarbeiten.")
                continue
            if offer is not None:
                offers.append(offer)
        return offers

    # --- Client-seitige Location-Filterung ---------------------------------

    @staticmethod
    def _matches_location(raw: dict[str, Any], location_term: str | None) -> bool:
        """Filtert client-seitig nach Ort, da die API keinen `location`-
        Query-Parameter kennt (KTD9). Die frühere Stichwort-Hälfte dieser
        Prüfung entfällt - sie läuft jetzt zentral für alle Quellen in
        `JobSearchService._apply_relevance_filter` (R8/KTD9/KTD10)."""
        if not location_term:
            return True
        offer_location = str(raw.get("location") or "").lower()
        return location_term in offer_location

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
