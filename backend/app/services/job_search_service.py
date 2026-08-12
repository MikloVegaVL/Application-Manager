"""Service zur Jobsuche.

Aggregiert Stellenangebote aus mehreren Quellen und liefert sie als
`JobSearchResponse` zurück (siehe `app.schemas.job_offer`):

1. `ArbeitsagenturJobsClient`  - offizielle, öffentliche REST-Schnittstelle
   der Bundesagentur für Arbeit ("Jobsuche API").
2. `LinkedInJobsClient` (app.services.job_sources.linkedin) - LinkedIns
   öffentlicher, anonymer Guest-Suchendpunkt.
3. `XingJobScraper` (app.services.job_sources.xing)         - Playwright-
   basiertes Scraping von Xings gerenderter Suchergebnisseite.
4. `GenericJobScraper`         - generischer Fallback, der eine beliebige
   Jobbörsen-Ergebnisseite lädt (BeautifulSoup, bei JS-lastigen Seiten via
   Playwright) und strukturierte Stellenanzeigen extrahiert.

`JobSearchService` orchestriert die ersten drei Quellen **gleichzeitig**
über einen `ThreadPoolExecutor` mit einer festen Zeit-Deadline (siehe KTD1
im Plan: docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).
Jede Quelle, die innerhalb der Deadline Treffer liefert, trägt zu den
zusammengeführten Ergebnissen bei; jede Quelle, die einen Fehler wirft, die
Deadline überschreitet oder leer bleibt, wird im Antwortobjekt als
"unavailable" markiert statt die gesamte Suche zu blockieren oder die Quelle
stillschweigend wegzulassen (R5).

Liefert die Arbeitsagentur-API keine Treffer und wurde eine `fallback_url`
übergeben, wird zusätzlich (wie bisher) der generische `GenericJobScraper`
befragt - dieser Pfad ist von der neuen Mehrquellen-Suche unberührt.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.core.config import settings
from app.schemas.job_offer import JobOfferCreate, JobSearchResponse, SourceStatus
from app.services.job_sources.linkedin import LinkedInJobsClient
from app.services.job_sources.xing import XingJobScraper

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

    Wichtig: Die Bundesagentur hebt die API-Version regelmäßig an (zuletzt
    v4 -> v6) und ändert dabei auch das Antwortschema; alte Versionen werden
    irgendwann mit HTTP 403 abgewiesen. Sollte die Suche wieder leer
    bleiben, zuerst per curl prüfen, ob eine neuere Version unter
    https://github.com/bundesAPI/jobsuche-api aktuell ist.

    Da es sich um eine inoffizielle Schnittstelle handelt, wird das
    Antwortformat defensiv geparst (`.get()` mit Fallbacks) - ein einzelner
    unerwarteter Datensatz darf niemals die gesamte Suche zum Absturz
    bringen.
    """

    BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6"
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

        raw_offers = payload.get("ergebnisliste") or []
        offers: list[JobOfferCreate] = []
        for raw_offer in raw_offers:
            try:
                offers.append(self._map_offer(raw_offer))
            except Exception:  # noqa: BLE001 - ein defekter Datensatz darf nicht die Suche stoppen
                logger.exception("Konnte Arbeitsagentur-Angebot nicht verarbeiten: %r", raw_offer)
        return offers

    def _map_offer(self, raw: dict[str, Any]) -> JobOfferCreate:
        """Wandelt einen rohen API-Datensatz (Schema v6) in ein harmonisiertes JobOffer um."""
        lokationen = raw.get("stellenlokationen") or []
        adresse = (lokationen[0].get("adresse") or {}) if lokationen else {}
        location_parts = [adresse.get("plz"), adresse.get("ort")]
        location = " ".join(part for part in location_parts if part) or None

        # Manche Angebote verlinken direkt auf die Karriereseite des
        # Unternehmens (externeURL) - sonst Fallback auf die öffentliche
        # Detailseite der Arbeitsagentur anhand der Referenznummer.
        referenznummer = raw.get("referenznummer", "")
        detail_url = raw.get("externeURL") or (
            f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{referenznummer}"
            if referenznummer
            else f"{self.BASE_URL}/jobs"
        )

        return JobOfferCreate(
            title=raw.get("stellenangebotsTitel") or raw.get("hauptberuf") or "Unbekannte Position",
            company=raw.get("firma") or "Unbekanntes Unternehmen",
            location=location,
            source_url=detail_url,
            description_text=None,  # Volltext erfordert einen separaten Detail-Call (v4/jobdetails)
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

    Arbeitsagentur, LinkedIn und Xing werden gleichzeitig abgefragt (KTD1)
    und liefern eine `JobSearchResponse` mit zusammengeführten Ergebnissen
    plus einem Status pro Quelle. Liefert Arbeitsagentur keine Treffer und
    wurde eine `fallback_url` übergeben, wird zusätzlich (wie bisher) der
    generische Web-Scraper befragt.
    """

    def __init__(
        self,
        arbeitsagentur_client: ArbeitsagenturJobsClient | None = None,
        fallback_scraper: GenericJobScraper | None = None,
        linkedin_client: LinkedInJobsClient | None = None,
        xing_client: XingJobScraper | None = None,
        deadline_seconds: float | None = None,
    ) -> None:
        self._arbeitsagentur_client = arbeitsagentur_client or ArbeitsagenturJobsClient()
        self._fallback_scraper = fallback_scraper or GenericJobScraper()
        self._linkedin_client = linkedin_client or LinkedInJobsClient(
            result_cap=settings.JOB_SEARCH_LINKEDIN_RESULT_CAP,
            cooldown_seconds=settings.JOB_SEARCH_LINKEDIN_COOLDOWN_SECONDS,
        )
        self._xing_client = xing_client or XingJobScraper()
        self._deadline_seconds = (
            deadline_seconds if deadline_seconds is not None else settings.JOB_SEARCH_DEADLINE_SECONDS
        )

    def search(
        self,
        keywords: str,
        location: str | None = None,
        fallback_url: str | None = None,
    ) -> JobSearchResponse:
        """Fragt Arbeitsagentur, LinkedIn und Xing gleichzeitig ab und
        liefert eine zusammengeführte `JobSearchResponse` (KTD1/KTD2)."""
        primary_clients: dict[str, Any] = {
            ArbeitsagenturJobsClient.SOURCE_PLATFORM: self._arbeitsagentur_client,
        }
        if settings.JOB_SEARCH_LINKEDIN_ENABLED:
            primary_clients[LinkedInJobsClient.SOURCE_PLATFORM] = self._linkedin_client
        if settings.JOB_SEARCH_XING_ENABLED:
            primary_clients[XingJobScraper.SOURCE_PLATFORM] = self._xing_client

        results: list[JobOfferCreate] = []
        sources: list[SourceStatus] = []
        arbeitsagentur_results: list[JobOfferCreate] = []

        # NICHT `with ThreadPoolExecutor(...) as executor:` - dessen eigenes
        # __exit__ ruft shutdown(wait=True) auf, was genau auf das
        # ausgelaufene Future warten würde, das diese Deadline verhindern
        # soll (KTD1).
        executor = ThreadPoolExecutor(max_workers=len(primary_clients))
        try:
            deadline = monotonic() + self._deadline_seconds
            futures = {
                source_name: executor.submit(client.search, keywords, location)
                for source_name, client in primary_clients.items()
            }
            for source_name, future in futures.items():
                try:
                    offers = future.result(timeout=max(0.0, deadline - monotonic()))
                except FuturesTimeoutError:
                    logger.warning("Quelle '%s' hat die Such-Deadline überschritten.", source_name)
                    sources.append(SourceStatus(platform=source_name, status="unavailable", reason="timeout"))
                    continue
                except Exception:  # noqa: BLE001 - eine fehlschlagende Quelle darf die anderen nicht stoppen
                    logger.exception("Quelle '%s' ist mit einem Fehler fehlgeschlagen.", source_name)
                    sources.append(SourceStatus(platform=source_name, status="unavailable", reason="error"))
                    continue

                if source_name == ArbeitsagenturJobsClient.SOURCE_PLATFORM:
                    arbeitsagentur_results = offers

                if offers:
                    results.extend(offers)
                    sources.append(SourceStatus(platform=source_name, status="ok"))
                else:
                    reason = "empty"
                    if source_name == LinkedInJobsClient.SOURCE_PLATFORM and LinkedInJobsClient.is_cooldown_active():
                        reason = "rate-limited"
                    sources.append(SourceStatus(platform=source_name, status="unavailable", reason=reason))
        finally:
            # wait=False: ein bereits als "timeout" markiertes Future darf im
            # Hintergrund zu Ende laufen, ohne die Antwort zu blockieren (KTD1).
            executor.shutdown(wait=False)

        if not arbeitsagentur_results and fallback_url:
            logger.info("Keine Treffer über die Arbeitsagentur-API - nutze Fallback-Scraper (%s).", fallback_url)
            fallback_results = self._fallback_scraper.search(url=fallback_url, keywords=keywords, location=location)
            results.extend(fallback_results)

        return JobSearchResponse(results=results, sources=sources)


def get_job_search_service() -> JobSearchService:
    """FastAPI-Dependency-Provider für den `JobSearchService`."""
    return JobSearchService()
