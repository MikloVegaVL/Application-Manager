"""Client für Adzunas offizielle Jobsuche-API (Deutschland).

Adzuna bietet eine dokumentierte, credential-basierte Such-API. Dieser Client
fragt ausschließlich den deutschen Markt ab (`/jobs/de/search/{page}`, KD6)
und mappt die JSON-Treffer auf das harmonisierte `JobOfferCreate`.

Zugangsdaten (`app_id`/`app_key`) kommen ausschließlich aus den Settings
(`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, KTD7) - nie aus einem Nutzerkonto (R2).
Fehlen sie, meldet `is_configured()` `False` und `search()` wirft
`SourceNotConfiguredError`, OHNE einen HTTP-Call zu machen (KTD4/KTD9).
Lehnt der Server die Zugangsdaten ab (HTTP 401/403/410), wird dieselbe
Exception geworfen; der Orchestrator mappt beides auf
`status="unavailable", reason="not-configured"`.

Die quellenübergreifende Maschinerie (User-Agent, URL-Validierung,
Salary-Prosa, HTML-Stripping, Credential-Redaktion) liegt in
`job_sources/shared.py` (KTD10) und wird von hier nur konsumiert.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

import requests

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import (
    DEFAULT_USER_AGENT,
    SourceNotConfiguredError,
    fold_salary_homeoffice,
    redact_credentials,
    strip_html,
    validate_source_url,
)

logger = logging.getLogger(__name__)


class AdzunaJobsClient:
    """Client für Adzunas credential-basierte Jobsuche-API (Deutschland)."""

    SOURCE_PLATFORM = "adzuna"
    BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search/1"
    _DEFAULT_RESULT_CAP = 25
    _DEFAULT_COOLDOWN_SECONDS = 300.0

    # Bewusst Klassen-Level-State (wie LinkedInJobsClient): der Client wird pro
    # Request neu instanziiert, ein Instanzattribut würde den Rate-Limit-
    # Cooldown also nie tatsächlich greifen lassen (KTD5).
    _cooldown_until: float = 0.0

    def __init__(
        self,
        app_id: str = "",
        app_key: str = "",
        timeout: float = 10.0,
        result_cap: int = _DEFAULT_RESULT_CAP,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._app_id = app_id or ""
        self._app_key = app_key or ""
        self._timeout = timeout
        self._result_cap = result_cap
        self._cooldown_seconds = cooldown_seconds
        self._headers = {
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

    def is_configured(self) -> bool:
        """Ob beide Zugangsdaten vorhanden sind (KTD9)."""
        return bool(self._app_id and self._app_key)

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über Adzunas deutsche Such-API.

        Liefert bei den meisten Fehlerfällen eine leere Liste statt einer
        Exception (Netzwerkfehler, Rate-Limit, Cooldown, ungültiges JSON) - der
        Aufrufer entscheidet anhand des Ergebnisses über den Status. Fehlende
        oder serverseitig abgelehnte Zugangsdaten werfen dagegen
        `SourceNotConfiguredError` (KTD4/KTD9).
        """
        if not self.is_configured():
            raise SourceNotConfiguredError("Adzuna: app_id/app_key fehlen.")

        if self._in_cooldown():
            logger.info("Adzuna-Client: aktiver Cooldown - Anfrage übersprungen.")
            return []

        params: dict[str, Any] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "what": keywords,
            "results_per_page": self._result_cap,
        }
        if location:
            params["where"] = location

        # Nur die redigierte URL loggen - die rohe URL enthält `app_key` (R9).
        logger.debug(
            "Adzuna-Anfrage: GET %s?%s",
            self.BASE_URL,
            redact_credentials(urlencode(params)),
        )

        try:
            response = requests.get(
                self.BASE_URL,
                params=params,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            # Rohe Exception enthält die volle URL inkl. app_key - redigieren.
            logger.warning(
                "Adzuna-API nicht erreichbar: %s", redact_credentials(str(exc))
            )
            return []

        if response.status_code in (401, 403, 410):
            logger.warning(
                "Adzuna-API hat die Zugangsdaten abgelehnt (HTTP %s).",
                response.status_code,
            )
            raise SourceNotConfiguredError(
                f"Adzuna: Zugangsdaten abgelehnt (HTTP {response.status_code})."
            )

        if response.status_code == 429:
            logger.warning(
                "Adzuna-API hat rate-limitiert (429) - aktiviere Cooldown (%.0fs).",
                self._cooldown_seconds,
            )
            self._set_cooldown()
            return []

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "Adzuna-API lieferte Fehlerstatus: %s", redact_credentials(str(exc))
            )
            return []

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Adzuna-API lieferte kein valides JSON zurück.")
            return []

        raw_results = payload.get("results") or []
        offers: list[JobOfferCreate] = []
        for raw in raw_results:
            try:
                offer = self._map_offer(raw)
            except Exception:  # noqa: BLE001 - ein defekter Datensatz darf die Suche nicht stoppen
                logger.exception("Konnte Adzuna-Angebot nicht verarbeiten.")
                continue
            if offer is not None:
                offers.append(offer)
        return offers

    # --- Cooldown-Verwaltung (Klassen-Level, siehe Moduldocstring) --------

    @classmethod
    def is_cooldown_active(cls) -> bool:
        """Öffentliche Abfrage für den Orchestrator, um eine leere
        Ergebnisliste als "rate-limited" statt generisch "empty" zu
        kennzeichnen (KTD3)."""
        return cls._in_cooldown()

    @classmethod
    def _in_cooldown(cls) -> bool:
        return time.monotonic() < cls._cooldown_until

    def _set_cooldown(self) -> None:
        AdzunaJobsClient._cooldown_until = time.monotonic() + self._cooldown_seconds

    # --- Mapping ------------------------------------------------------

    def _map_offer(self, raw: dict[str, Any]) -> JobOfferCreate | None:
        title = raw.get("title")
        redirect_url = raw.get("redirect_url")
        if not title or not validate_source_url(redirect_url):
            return None

        company = (raw.get("company") or {}).get("display_name") or "Unbekanntes Unternehmen"
        location = (raw.get("location") or {}).get("display_name")

        description_text = fold_salary_homeoffice(
            strip_html(raw.get("description")),
            salary=self._format_salary(raw),
        )

        return JobOfferCreate(
            title=str(title).strip(),
            company=str(company).strip(),
            location=location,
            source_url=redirect_url,
            description_text=description_text,
            source_platform=self.SOURCE_PLATFORM,
        )

    @staticmethod
    def _format_salary(raw: dict[str, Any]) -> str | None:
        """Faltet `salary_min`/`salary_max`/`salary_is_predicted` in Prosa (KTD6)."""
        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        if salary_min is None and salary_max is None:
            return None

        def _format(value: Any) -> str:
            try:
                return f"{float(value):,.0f}".replace(",", ".")
            except (TypeError, ValueError):
                return str(value)

        if salary_min is not None and salary_max is not None:
            amount = f"{_format(salary_min)} - {_format(salary_max)} EUR"
        elif salary_min is not None:
            amount = f"ab {_format(salary_min)} EUR"
        else:
            amount = f"bis {_format(salary_max)} EUR"

        if str(raw.get("salary_is_predicted", "0")).lower() in ("1", "true"):
            amount += " (geschätzt)"
        return amount
