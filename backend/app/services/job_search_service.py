"""Service zur Jobsuche.

Aggregiert Stellenangebote aus zwei Quellen und liefert sie in einem
einheitlichen Format zurück, das direkt dem `JobOfferCreate`-Schema
entspricht (siehe `app.schemas.job_offer`):

1. `ArbeitsagenturJobsClient`  - offizielle, öffentliche REST-Schnittstelle
   der Bundesagentur für Arbeit ("Jobsuche API").
2. `GenericJobScraper`         - generischer Fallback, der eine beliebige
   Jobbörsen-Ergebnisseite lädt (BeautifulSoup, bei JS-lastigen Seiten via
   Playwright) und strukturierte Stellenanzeigen extrahiert.

`JobSearchService` orchestriert beide Quellen: Liefert die Arbeitsagentur-
API keine Treffer (Ausfall, keine Ergebnisse, Rate-Limit), wird - sofern
eine `fallback_url` übergeben wurde - der generische Scraper genutzt.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate

logger = logging.getLogger(__name__)

# Browser-artiger User-Agent, um von Zielseiten nicht pauschal als Bot
# geblockt zu werden. Für produktive Nutzung sollte jede Quelle einzeln auf
# robots.txt / Nutzungsbedingungen geprüft werden.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ApplicationManagerBot/1.0; "
    "+https://github.com/application-manager)"
)


class ArbeitsagenturJobsClient:
    """Client für die öffentliche Jobsuche-API der Bundesagentur für Arbeit.

    Die API ist nicht offiziell dokumentiert, wird aber öffentlich von
    https://www.arbeitsagentur.de/jobsuche genutzt und akzeptiert dafür den
    Client-Key "jobboerse-jobsuche" im Header `X-API-Key`. Für hochfrequente
    oder produktive Nutzung empfiehlt sich ein eigener, registrierter Key
    (siehe https://jobsuche.api.bund.dev/).

    Da es sich um eine inoffizielle Schnittstelle handelt, wird das
    Antwortformat defensiv geparst (`.get()` mit Fallbacks) - ein einzelner
    unerwarteter Datensatz darf niemals die gesamte Suche zum Absturz
    bringen.
    """

    BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4"
    API_KEY = "jobboerse-jobsuche"
    SOURCE_PLATFORM = "arbeitsagentur"

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._headers = {
            "X-API-Key": self.API_KEY,
            "Accept": "application/json",
            "User-Agent": _DEFAULT_USER_AGENT,
        }

    def search(
        self,
        keywords: str,
        location: str | None = None,
        results_limit: int = 25,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote nach Jobtitel/Keywords und optional Ort."""
        params: dict[str, Any] = {"was": keywords, "size": results_limit}
        if location:
            params["wo"] = location

        try:
            response = requests.get(
                f"{self.BASE_URL}/jobs",
                params=params,
                headers=self._headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Arbeitsagentur-API nicht erreichbar: %s", exc)
            return []

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Arbeitsagentur-API lieferte kein valides JSON zurück.")
            return []

        raw_offers = payload.get("stellenangebote") or []
        offers: list[JobOfferCreate] = []
        for raw_offer in raw_offers:
            try:
                offers.append(self._map_offer(raw_offer))
            except Exception:  # noqa: BLE001 - ein defekter Datensatz darf nicht die Suche stoppen
                logger.exception("Konnte Arbeitsagentur-Angebot nicht verarbeiten: %r", raw_offer)
        return offers

    def _map_offer(self, raw: dict[str, Any]) -> JobOfferCreate:
        """Wandelt einen rohen API-Datensatz in ein harmonisiertes JobOffer um."""
        arbeitsort = raw.get("arbeitsort") or {}
        location_parts = [arbeitsort.get("plz"), arbeitsort.get("ort")]
        location = " ".join(part for part in location_parts if part) or None

        refnr = raw.get("refnr", "")
        detail_url = (
            f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
            if refnr
            else f"{self.BASE_URL}/jobs"
        )

        return JobOfferCreate(
            title=raw.get("titel") or raw.get("beruf") or "Unbekannte Position",
            company=raw.get("arbeitgeber") or "Unbekanntes Unternehmen",
            location=location,
            source_url=detail_url,
            description_text=None,  # Volltext erfordert einen separaten Detail-Call
            source_platform=self.SOURCE_PLATFORM,
        )


class GenericJobScraper:
    """Generischer Fallback-Scraper für Stellenanzeigen-Webseiten ohne API.

    Extrahiert Stellenanzeigen aus einer beliebigen Ergebnisseite in zwei
    Stufen:

    1. Bevorzugt über eingebettete `schema.org/JobPosting`-JSON-LD-Daten,
       die die meisten seriösen Jobbörsen zu SEO-Zwecken einbetten - das
       liefert sauber strukturierte, verlässliche Felder.
    2. Fällt das aus, über eine heuristische Extraktion anhand verbreiteter
       HTML-/CSS-Muster (Karten-/Listenelemente mit Job-typischen
       Klassennamen).

    Für Seiten, deren Inhalt erst per JavaScript nachgeladen wird, kann
    `use_playwright=True` gesetzt werden, um die Seite vor der Extraktion
    vollständig zu rendern.
    """

    SOURCE_PLATFORM = "web-scraper"
    _MAX_HEURISTIC_RESULTS = 25

    def __init__(self, use_playwright: bool = False, timeout: float = 15.0) -> None:
        self._use_playwright = use_playwright
        self._timeout = timeout

    def search(
        self,
        url: str,
        keywords: str | None = None,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Lädt `url` und extrahiert daraus strukturierte Stellenanzeigen."""
        html = self._fetch_html(url)
        if not html:
            return []
        return self._extract_offers(html, source_url=url)

    # --- HTML-Beschaffung -------------------------------------------------

    def _fetch_html(self, url: str) -> str | None:
        if self._use_playwright:
            return self._fetch_with_playwright(url)
        return self._fetch_with_requests(url)

    def _fetch_with_requests(self, url: str) -> str | None:
        try:
            response = requests.get(
                url,
                timeout=self._timeout,
                headers={"User-Agent": _DEFAULT_USER_AGENT},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.warning("Fallback-Scraper: Abruf von %s fehlgeschlagen: %s", url, exc)
            return None

    def _fetch_with_playwright(self, url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright ist nicht installiert - Fallback auf requests.")
            return self._fetch_with_requests(url)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(user_agent=_DEFAULT_USER_AGENT)
                    page.goto(url, timeout=self._timeout * 1000, wait_until="networkidle")
                    return page.content()
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 - z. B. fehlende Browser-Binaries
            logger.warning(
                "Playwright-Rendering von %s fehlgeschlagen (%s). "
                "Ist der Browser installiert? -> `playwright install chromium`",
                url,
                exc,
            )
            return None

    # --- Extraktion ---------------------------------------------------

    def _extract_offers(self, html: str, source_url: str) -> list[JobOfferCreate]:
        soup = BeautifulSoup(html, "html.parser")

        offers = self._extract_json_ld_offers(soup, source_url)
        if offers:
            return offers

        return self._extract_heuristic_offers(soup, source_url)

    def _extract_json_ld_offers(self, soup: BeautifulSoup, source_url: str) -> list[JobOfferCreate]:
        offers: list[JobOfferCreate] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            for item in data if isinstance(data, list) else [data]:
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                offer = self._map_json_ld_offer(item, source_url)
                if offer is not None:
                    offers.append(offer)
        return offers

    def _map_json_ld_offer(self, item: dict[str, Any], source_url: str) -> JobOfferCreate | None:
        title = item.get("title")
        if not title:
            return None

        organization = item.get("hiringOrganization")
        if isinstance(organization, dict):
            company = organization.get("name")
        else:
            company = organization
        company = company or "Unbekanntes Unternehmen"

        job_location = item.get("jobLocation")
        if isinstance(job_location, list):
            job_location = job_location[0] if job_location else {}
        address = job_location.get("address") if isinstance(job_location, dict) else None
        address = address if isinstance(address, dict) else {}
        location = ", ".join(
            filter(None, [address.get("addressLocality"), address.get("addressRegion")])
        ) or None

        raw_description = item.get("description") or ""
        description_text = BeautifulSoup(raw_description, "html.parser").get_text(
            separator=" ", strip=True
        ) or None

        return JobOfferCreate(
            title=str(title).strip(),
            company=str(company).strip(),
            location=location,
            source_url=item.get("url") or source_url,
            description_text=description_text,
            source_platform=self.SOURCE_PLATFORM,
        )

    def _extract_heuristic_offers(self, soup: BeautifulSoup, source_url: str) -> list[JobOfferCreate]:
        job_class_pattern = re.compile(r"job|stelle|vacan", re.IGNORECASE)
        company_pattern = re.compile(r"company|arbeitgeber|employer|firma", re.IGNORECASE)
        location_pattern = re.compile(r"location|ort|city|standort", re.IGNORECASE)

        offers: list[JobOfferCreate] = []
        seen_titles: set[str] = set()

        candidates = soup.find_all(class_=job_class_pattern) + soup.find_all("article")
        for node in candidates:
            title_el = node.find(["h1", "h2", "h3", "a"])
            if title_el is None:
                continue
            title = title_el.get_text(strip=True)
            if len(title) < 3 or title in seen_titles:
                continue

            link_el = node.find("a", href=True)
            href = link_el["href"] if link_el else source_url
            full_url = href if href.startswith("http") else urljoin(source_url, href)

            company_el = node.find(class_=company_pattern)
            company = company_el.get_text(strip=True) if company_el else "Unbekanntes Unternehmen"

            location_el = node.find(class_=location_pattern)
            location = location_el.get_text(strip=True) if location_el else None

            seen_titles.add(title)
            offers.append(
                JobOfferCreate(
                    title=title,
                    company=company,
                    location=location,
                    source_url=full_url,
                    description_text=None,
                    source_platform=self.SOURCE_PLATFORM,
                )
            )
            if len(offers) >= self._MAX_HEURISTIC_RESULTS:
                break

        return offers


class JobSearchService:
    """Orchestriert die Jobsuche über alle verfügbaren Quellen.

    Primärquelle ist die Arbeitsagentur-API. Liefert sie keine Treffer
    (z. B. wegen eines Ausfalls oder schlicht keiner Ergebnisse) und wurde
    eine `fallback_url` übergeben, wird zusätzlich der generische
    Web-Scraper befragt.
    """

    def __init__(
        self,
        arbeitsagentur_client: ArbeitsagenturJobsClient | None = None,
        fallback_scraper: GenericJobScraper | None = None,
    ) -> None:
        self._arbeitsagentur_client = arbeitsagentur_client or ArbeitsagenturJobsClient()
        self._fallback_scraper = fallback_scraper or GenericJobScraper()

    def search(
        self,
        keywords: str,
        location: str | None = None,
        fallback_url: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote und liefert sie im einheitlichen
        `JobOfferCreate`-Format zurück."""
        results = self._arbeitsagentur_client.search(keywords=keywords, location=location)
        if results:
            logger.info(
                "Arbeitsagentur-API lieferte %d Treffer für '%s' (%s).",
                len(results),
                keywords,
                location or "beliebiger Ort",
            )
            return results

        if not fallback_url:
            logger.info(
                "Keine Treffer über die Arbeitsagentur-API und keine "
                "fallback_url angegeben - Suche liefert keine Ergebnisse."
            )
            return []

        logger.info("Keine Treffer über die Arbeitsagentur-API - nutze Fallback-Scraper (%s).", fallback_url)
        return self._fallback_scraper.search(url=fallback_url, keywords=keywords, location=location)


def get_job_search_service() -> JobSearchService:
    """FastAPI-Dependency-Provider für den `JobSearchService`."""
    return JobSearchService()
