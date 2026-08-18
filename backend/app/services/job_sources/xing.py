"""Client für Xings Jobsuche per Playwright-Rendering.

Xing bietet - anders als LinkedIn - weder eine öffentliche Guest-API noch
eingebettete `schema.org/JobPosting`-JSON-LD-Daten. Ergebnisse müssen daher
aus der clientseitig gerenderten Suchergebnisseite extrahiert werden - siehe
KTD6 im Plan
(docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).

Der Browser (Chromium) ist im Backend-Image bereits vorhanden
(`backend/Dockerfile`: `playwright install --with-deps chromium`). Die
Job-Karten werden per CSS-Klassen-Heuristik extrahiert, analog zu
`GenericJobScraper._extract_heuristic_offers` in job_search_service.py -
Xings genaue CSS-Klassen sind unbestätigt/undokumentiert (siehe Planungsdoc),
daher der gleiche tolerante Ansatz statt fest verdrahteter Selektoren.

Bewusst eigenständig implementiert statt aus `job_search_service.py`
importiert (KTD3: `job_sources/` importiert nie aus
`job_search_service.py`, um einen zirkulären Import zwischen Orchestrator
und diesem Package zu vermeiden - die Playwright-Startlogik ist daher
dupliziert, nicht geteilt).

Zwei Ressourcen-Schutzmaßnahmen, weil dieser Client - anders als
`GenericJobScraper`s seltener manueller Fallback-Pfad - bei JEDER Suche
aufgerufen wird (KTD6):

1. Ein eigener innerer Timeout für den Playwright-Aufruf: `ThreadPoolExecutor`s
   äußerer Timeout (KTD1) bricht nur das *Warten* ab, nicht den laufenden
   Browser-Prozess - ohne inneren Timeout liefe ein hängendes Rendering über
   die bereits beantwortete Anfrage hinaus weiter.
2. Ein prozessweites Semaphore rund um den Browser-Start (nicht um die ganze
   Methode), damit ein Doppel-Tab/Doppel-Klick-Burst nicht beliebig viele
   Chromium-Instanzen gleichzeitig startet.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate

logger = logging.getLogger(__name__)

# Eigene Konstante statt Import aus job_search_service (KTD3: job_sources/
# importiert nie aus job_search_service.py).
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ApplicationManagerBot/1.0; "
    "+https://github.com/application-manager)"
)

_JOB_CLASS_PATTERN = re.compile(r"job|stelle|vacan", re.IGNORECASE)
_COMPANY_CLASS_PATTERN = re.compile(r"company|arbeitgeber|employer|firma", re.IGNORECASE)
_LOCATION_CLASS_PATTERN = re.compile(r"location|ort|city|standort", re.IGNORECASE)

# Modul-Level-Import statt Import innerhalb der Methode: dadurch lässt sich
# `sync_playwright` in Tests einfach patchen (siehe test_xing.py). Playwright
# ist eine harte Dependency (requirements.txt); der Fallback greift nur,
# falls die Installation dennoch unvollständig ist.
try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - playwright ist in requirements.txt gelistet
    sync_playwright = None  # type: ignore[assignment]

# Prozessweites Semaphore - begrenzt gleichzeitige Playwright/Chromium-Starts
# unabhängig von der Anzahl gleichzeitig laufender Suchen (KTD6).
_playwright_launch_semaphore = threading.Semaphore(2)


class XingJobScraper:
    """Scraped Xings gerenderte Jobsuche-Ergebnisseite per Playwright."""

    SOURCE_PLATFORM = "xing"
    SEARCH_URL = "https://www.xing.com/jobs/search"
    _MAX_RESULTS = 25

    def __init__(self, inner_timeout: float = 15.0) -> None:
        self._inner_timeout = inner_timeout

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über Xings gerenderte Suchergebnisseite.

        Liefert bei jedem Fehlerfall eine leere Liste statt einer Exception
        (Rendering-Fehler, Timeout, fehlende Ergebnisse) - der Aufrufer
        (`JobSearchService`) entscheidet anhand des Ergebnisses über den
        Status "unavailable" (siehe U4 im Plan).
        """
        query: dict[str, Any] = {"keywords": keywords}
        if location:
            query["location"] = location
        url = f"{self.SEARCH_URL}?{urlencode(query)}"

        html = self._render(url)
        if not html:
            return []

        return self._extract_offers(html, source_url=url)

    # --- Rendering ------------------------------------------------------

    def _render(self, url: str) -> str | None:
        if sync_playwright is None:
            logger.warning("Playwright ist nicht installiert - Xing-Suche nicht möglich.")
            return None

        with _playwright_launch_semaphore:
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(user_agent=_DEFAULT_USER_AGENT)
                        page.goto(
                            url,
                            timeout=self._inner_timeout * 1000,
                            wait_until="networkidle",
                        )
                        return page.content()
                    finally:
                        browser.close()
            except Exception as exc:  # noqa: BLE001 - z. B. Timeout, Geoblock, fehlende Browser-Binaries
                logger.warning("Xing-Rendering von %s fehlgeschlagen: %s", url, exc)
                return None

    # --- Extraktion -------------------------------------------------

    def _extract_offers(self, html: str, source_url: str) -> list[JobOfferCreate]:
        soup = BeautifulSoup(html, "html.parser")
        offers: list[JobOfferCreate] = []
        seen_titles: set[str] = set()

        candidates = soup.find_all(class_=_JOB_CLASS_PATTERN) + soup.find_all("article")
        for node in candidates:
            try:
                offer = self._map_node(node, source_url, seen_titles)
            except Exception:  # noqa: BLE001 - eine defekte Karte darf die übrigen nicht verwerfen
                logger.exception("Konnte Xing-Job-Karte nicht verarbeiten.")
                continue
            if offer is not None:
                offers.append(offer)
            if len(offers) >= self._MAX_RESULTS:
                break

        return offers

    def _map_node(self, node: Any, source_url: str, seen_titles: set[str]) -> JobOfferCreate | None:
        # Erst nach einer echten Überschrift suchen, erst danach auf ein
        # <a> zurückfallen: Xings Karten wickeln jede Karte in ein
        # ganzkartiges, textloses Overlay-<a> (der Linktext steckt nur im
        # aria-label), das im DOM VOR der sichtbaren <h2>-Überschrift steht.
        # `find()` mit einer Tag-Liste matcht in Dokumentreihenfolge, nicht
        # nach Priorität der Liste - ohne diese Trennung würde daher immer
        # das leere Overlay-<a> statt der echten Überschrift gefunden.
        title_el = node.find(["h1", "h2", "h3"]) or node.find("a")
        if title_el is None:
            return None
        title = title_el.get_text(strip=True)
        if len(title) < 3 or title in seen_titles:
            return None

        link_el = node.find("a", href=True)
        href = link_el["href"] if link_el else None
        if not href:
            # Ohne echten Link auf die Detailseite lässt sich R3 nicht
            # erfüllen - Karte überspringen statt auf die Suchseite zu verlinken.
            return None
        full_url = href if href.startswith("http") else urljoin(source_url, href)

        company_el = node.find(class_=_COMPANY_CLASS_PATTERN)
        company = company_el.get_text(strip=True) if company_el else "Unbekanntes Unternehmen"

        location_el = node.find(class_=_LOCATION_CLASS_PATTERN)
        location = location_el.get_text(strip=True) if location_el else None

        seen_titles.add(title)
        return JobOfferCreate(
            title=title,
            company=company,
            location=location,
            source_url=full_url,
            description_text=None,
            source_platform=self.SOURCE_PLATFORM,
        )
