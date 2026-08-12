"""Client für LinkedIns öffentliche "Guest"-Jobsuche.

LinkedIn bietet keine offizielle öffentliche Such-API. Dieser Client nutzt
stattdessen den undokumentierten "Guest"-Endpunkt, den linkedin.com/jobs
selbst für anonyme (nicht eingeloggte) Suchergebnisse lädt. Er liefert ein
HTML-Fragment einzelner Job-Karten (kein JSON), gedacht zum Scrapen per
CSS-Selektor - siehe KTD4 im Plan
(docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).

Jede Job-Karte verlinkt bereits direkt auf die öffentliche
`linkedin.com/jobs/view/{id}`-Detailseite. Ein zweiter Request pro Ergebnis
(z. B. für die JSON-LD-Detailseite) ist für einen korrekten direkten Link
nicht nötig und würde unnötig am ohnehin knappen anonymen Rate-Limit-Budget
zehren (KTD4).

Anonyme Zugriffe werden von LinkedIn nach ca. 10 Ergebnisseiten mit HTTP 429
rate-limitiert. Um dieses Budget zu schonen: (a) begrenzt dieser Client die
angeforderte Ergebnisanzahl pro Suche, und (b) merkt er sich nach einem 429
einen Cooldown-Zeitpunkt und überspringt weitere Anfragen bis dahin (KTD5).

Wichtig: Der Cooldown ist bewusst Klassen-Level-State statt Instanzattribut.
`JobSearchService` (und damit dieser Client) wird pro Request neu
instanziiert (siehe `get_job_search_service()` in job_search_service.py) -
ein Instanzattribut würde den Cooldown also bei jedem Request zurücksetzen
und nie tatsächlich greifen.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate

logger = logging.getLogger(__name__)

# Eigener User-Agent-Konstante statt Import aus job_search_service (KTD3:
# job_sources/ importiert nie aus job_search_service.py).
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ApplicationManagerBot/1.0; "
    "+https://github.com/application-manager)"
)


class LinkedInJobsClient:
    """Client für LinkedIns öffentlichen, nicht eingeloggten Guest-Suchendpunkt."""

    SOURCE_PLATFORM = "linkedin"
    BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    _DEFAULT_RESULT_CAP = 10
    _DEFAULT_COOLDOWN_SECONDS = 300.0

    # Klassen-Level-State (siehe Moduldocstring): überlebt neue Instanzen,
    # solange der Prozess läuft. Setzen erfolgt ausschließlich über
    # `_set_cooldown`, das explizit auf der Klasse (nicht `self`) schreibt.
    _cooldown_until: float = 0.0

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
            "Accept": "text/html",
            "User-Agent": _DEFAULT_USER_AGENT,
        }

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über LinkedIns öffentlichen Guest-Endpunkt.

        Liefert eine leere Liste statt einer Exception bei jedem Fehlerfall
        (Netzwerkfehler, Rate-Limit, aktiver Cooldown) - der Aufrufer
        (`JobSearchService`) entscheidet anhand des Ergebnisses über den
        Status "unavailable" (siehe U4 im Plan).
        """
        if self._in_cooldown():
            logger.info("LinkedIn-Client: aktiver Cooldown - Anfrage übersprungen.")
            return []

        params: dict[str, Any] = {"keywords": keywords, "start": 0}
        if location:
            params["location"] = location

        try:
            response = requests.get(
                self.BASE_URL,
                params=params,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("LinkedIn-Guest-Endpunkt nicht erreichbar: %s", exc)
            return []

        if response.status_code == 429:
            logger.warning(
                "LinkedIn-Guest-Endpunkt hat rate-limitiert (429) - aktiviere Cooldown (%.0fs).",
                self._cooldown_seconds,
            )
            self._set_cooldown()
            return []

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("LinkedIn-Guest-Endpunkt lieferte Fehlerstatus: %s", exc)
            return []

        return self._parse_fragment(response.text)

    # --- Cooldown-Verwaltung (Klassen-Level, siehe Moduldocstring) --------

    @classmethod
    def is_cooldown_active(cls) -> bool:
        """Öffentliche Abfrage, ob der Client sich aktuell im Rate-Limit-
        Cooldown befindet - genutzt vom Orchestrator (`JobSearchService`),
        um eine leere Ergebnisliste als "rate-limited" statt generisch
        "empty" zu kennzeichnen (KTD5)."""
        return cls._in_cooldown()

    @classmethod
    def _in_cooldown(cls) -> bool:
        return time.monotonic() < cls._cooldown_until

    def _set_cooldown(self) -> None:
        # Bewusst auf der Klasse geschrieben (nicht `self`), damit der
        # Cooldown über neue Instanzen hinweg gilt.
        LinkedInJobsClient._cooldown_until = time.monotonic() + self._cooldown_seconds

    # --- Parsing ------------------------------------------------------

    def _parse_fragment(self, html: str) -> list[JobOfferCreate]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[JobOfferCreate] = []

        for card in soup.find_all("div", class_="base-card"):
            try:
                offer = self._map_card(card)
            except Exception:  # noqa: BLE001 - eine defekte Karte darf die Suche nicht stoppen
                logger.exception("Konnte LinkedIn-Job-Karte nicht verarbeiten.")
                continue
            if offer is not None:
                offers.append(offer)
            if len(offers) >= self._result_cap:
                break

        return offers

    def _map_card(self, card: Any) -> JobOfferCreate | None:
        title_el = card.find(class_="base-search-card__title")
        link_el = card.find("a", class_="base-card__full-link") or card.find("a", href=True)
        if title_el is None or link_el is None or not link_el.get("href"):
            return None

        title = title_el.get_text(strip=True)
        href = link_el["href"]
        source_url = href if href.startswith("http") else urljoin(self.BASE_URL, href)
        # Job-Detaillinks führen oft Tracking-Query-Parameter mit (z. B.
        # "?refId=..."); die Basis-URL bis zum Job-Pfad ist bereits ein
        # funktionierender direkter Link auf die echte Detailseite.
        source_url = source_url.split("?", 1)[0]

        company_el = card.find(class_="base-search-card__subtitle")
        company = company_el.get_text(strip=True) if company_el else "Unbekanntes Unternehmen"

        location_el = card.find(class_="job-search-card__location")
        location = location_el.get_text(strip=True) if location_el else None

        return JobOfferCreate(
            title=title,
            company=company,
            location=location,
            source_url=source_url,
            description_text=None,
            source_platform=self.SOURCE_PLATFORM,
        )
