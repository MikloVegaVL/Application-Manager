"""Client für Joobles credential-basierte Jobsuche-API (Deutschland).

Jooble bietet eine dokumentierte, credential-basierte Such-API. Dieser Client
fragt ausschließlich den deutschen Markt ab (KD6): fehlt ein `location`, wird
der Suchradius per Default auf Deutschland gesetzt. Die Antwort
(`{totalCount, jobs}`) wird auf das harmonisierte `JobOfferCreate` gemappt.

Zugangsdaten (`JOOBLE_API_KEY`) kommen ausschließlich aus den Settings
(KTD7) - nie aus einem Nutzerkonto (R2). Fehlt der Key, meldet
`is_configured()` `False` und `search()` wirft `SourceNotConfiguredError`,
OHNE einen HTTP-Call zu machen (KTD4/KTD9). Lehnt der Server den Key ab
(HTTP 401/403), wird dieselbe Exception geworfen; der Orchestrator mappt
beides auf `status="unavailable", reason="not-configured"`.

Der API-Key steckt bei Jooble im PFAD (`/api/<key>`), nicht in einem
Query-Parameter - die geteilte `redact_credentials()`-Regex würde ihn daher
NICHT maskieren. Deshalb wird die rohe, key-tragende URL (und die rohe
Exception, die dieselbe URL enthalten kann) hier niemals geloggt (KTD10/R9).

Die quellenübergreifende Maschinerie (User-Agent, URL-Validierung,
Salary-Prosa, HTML-Stripping) liegt in `job_sources/shared.py` (KTD10) und
wird von hier nur konsumiert.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import (
    DEFAULT_USER_AGENT,
    CooldownMixin,
    SourceNotConfiguredError,
    fold_salary_homeoffice,
    strip_html,
    validate_source_url,
)

logger = logging.getLogger(__name__)


class JoobleJobsClient(CooldownMixin):
    """Client für Joobles credential-basierte Jobsuche-API (Deutschland)."""

    SOURCE_PLATFORM = "jooble"
    BASE_URL_TEMPLATE = "https://jooble.org/api/{api_key}"
    # Jooble liefert keine eigene Detail-URL, die von `link` unabhängig wäre -
    # als Fallback (fehlender `link`) dient die kanonische Jooble-Detailseite.
    DETAIL_URL_TEMPLATE = "https://jooble.org/desc/{job_id}"
    # Jooble ist auf den deutschen Markt ausgerichtet (KD6); fehlt der
    # Aufrufer-Ort, wird er explizit gesetzt statt leer gelassen.
    DEFAULT_LOCATION = "Germany"
    _DEFAULT_RESULT_CAP = 25
    _DEFAULT_COOLDOWN_SECONDS = 300.0

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 10.0,
        result_cap: int = _DEFAULT_RESULT_CAP,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._api_key = api_key or ""
        self._timeout = timeout
        self._result_cap = result_cap
        self._cooldown_seconds = cooldown_seconds
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

    def is_configured(self) -> bool:
        """Ob ein API-Key vorhanden ist (KTD9)."""
        return bool(self._api_key)

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über Joobles deutsche Such-API.

        Fehlende oder serverseitig abgelehnte Zugangsdaten werfen
        `SourceNotConfiguredError` (KTD4/KTD9); 429 aktiviert einen Cooldown
        und liefert eine leere Liste (der Orchestrator kennzeichnet das als
        "rate-limited"). Echte Fehler (Netzwerk, unerwarteter HTTP-Status,
        ungültiges JSON) werden als redigierte Exception nach oben gereicht,
        damit der Orchestrator sie als "error" kennzeichnet - die rohe
        Exception enthält die key-tragende URL und darf nie geloggt werden.
        """
        if not self.is_configured():
            raise SourceNotConfiguredError("Jooble: API-Key fehlt.")

        if self._in_cooldown():
            logger.info("Jooble-Client: aktiver Cooldown - Anfrage übersprungen.")
            return []

        payload: dict[str, Any] = {
            "keywords": keywords,
            "location": location or self.DEFAULT_LOCATION,
        }
        # Nur die redigierte URL loggen - die rohe URL enthält den API-Key im
        # Pfad (R9).
        logger.debug("Jooble-Anfrage: POST %s", self._redacted_endpoint())

        try:
            response = requests.post(
                self._endpoint(),
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            # `str(exc)` enthält die rohe URL inkl. Key - nur den Typ loggen.
            logger.warning("Jooble-API nicht erreichbar (%s).", type(exc).__name__)
            raise RuntimeError("Jooble-API nicht erreichbar.") from None

        if response.status_code in (401, 403):
            logger.warning(
                "Jooble-API hat den API-Key abgelehnt (HTTP %s).",
                response.status_code,
            )
            raise SourceNotConfiguredError(
                f"Jooble: API-Key abgelehnt (HTTP {response.status_code})."
            )

        if response.status_code == 429:
            logger.warning(
                "Jooble-API hat rate-limitiert (429) - aktiviere Cooldown (%.0fs).",
                self._cooldown_seconds,
            )
            self._set_cooldown()
            return []

        if response.status_code >= 400:
            logger.warning(
                "Jooble-API lieferte Fehlerstatus (HTTP %s).", response.status_code
            )
            raise RuntimeError(
                f"Jooble-API lieferte Fehlerstatus (HTTP {response.status_code})."
            )

        try:
            data = response.json()
        except ValueError:
            logger.warning("Jooble-API lieferte kein valides JSON zurück.")
            raise RuntimeError("Jooble-API lieferte kein valides JSON zurück.") from None

        raw_jobs = data.get("jobs") or []
        offers: list[JobOfferCreate] = []
        for raw in raw_jobs:
            try:
                offer = self._map_offer(raw)
            except Exception:  # noqa: BLE001 - ein defekter Datensatz darf die Suche nicht stoppen
                logger.exception("Konnte Jooble-Angebot nicht verarbeiten.")
                continue
            if offer is not None:
                offers.append(offer)
            if len(offers) >= self._result_cap:
                break
        return offers

    # --- Endpunkt / Cooldown-Verwaltung ---------------------------------

    def _endpoint(self) -> str:
        return self.BASE_URL_TEMPLATE.format(api_key=self._api_key)

    def _redacted_endpoint(self) -> str:
        """Die key-tragende URL mit maskiertem Pfad-Key (nur zum Loggen)."""
        return self.BASE_URL_TEMPLATE.format(api_key="***")

    # --- Mapping --------------------------------------------------------

    def _map_offer(self, raw: dict[str, Any]) -> JobOfferCreate | None:
        title = raw.get("title")
        source_url = self._resolve_source_url(raw)
        if not title or not source_url:
            return None

        company = raw.get("company") or "Unbekanntes Unternehmen"
        location = raw.get("location")

        description_text = fold_salary_homeoffice(
            strip_html(raw.get("snippet")),
            salary=raw.get("salary"),
        )

        return JobOfferCreate(
            title=str(title).strip(),
            company=str(company).strip(),
            location=str(location).strip() if location else None,
            source_url=source_url,
            description_text=description_text,
            source_platform=self.SOURCE_PLATFORM,
        )

    def _resolve_source_url(self, raw: dict[str, Any]) -> str | None:
        """Validiert `link`; fällt nur bei fehlendem Link auf die kanonische
        Jooble-Detailseite aus der (als String behandelten) `id` zurück.

        Ein vorhandener, aber unsicherer Link (`javascript:`, privater Host)
        wird verworfen - nicht durch die id ersetzt (R3/KTD10).
        """
        link = raw.get("link")
        if link:
            return link if validate_source_url(link) else None

        job_id = raw.get("id")
        if job_id is None:
            return None
        # `id` ist eine große Zahl; die String-Behandlung verhindert
        # Float-Präzisionsverlust (z. B. 1234567890123456789).
        candidate = self.DETAIL_URL_TEMPLATE.format(job_id=str(job_id))
        return candidate if validate_source_url(candidate) else None
