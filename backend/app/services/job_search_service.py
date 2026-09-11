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

import base64
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from time import monotonic
from typing import Any
from urllib.parse import unquote

import requests

from app.core.config import settings
from app.schemas.job_offer import JobOfferCreate, JobSearchResponse, SourceStatus
from app.services.job_sources.linkedin import LinkedInJobsClient
from app.services.job_sources.shared import (
    DEFAULT_USER_AGENT,
    MAX_HEURISTIC_RESULTS,
    extract_heuristic_offers,
    extract_json_ld_offers,
    extract_offers,
    fetch_html,
    map_json_ld_offer,
    strip_html,
)
from app.services.job_sources.xing import XingJobScraper

logger = logging.getLogger(__name__)


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
    # Jobdetails leben unter einer eigenen API-Version (v4), nicht unter v6
    # wie die Suche selbst - siehe https://github.com/bundesAPI/jobsuche-api.
    DETAIL_BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails"
    API_KEY = "jobboerse-jobsuche"
    SOURCE_PLATFORM = "arbeitsagentur"

    # Passt exakt das Format, das `_map_offer` selbst für `detail_url` baut,
    # wenn kein `externeURL` vorhanden ist (siehe dort) - nur daraus lässt
    # sich die für den Detail-Call nötige Referenznummer zurückgewinnen.
    _DETAIL_URL_PATTERN = re.compile(r"/jobsuche/jobdetail/(?P<refnr>[^/?#]+)")

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._headers = {
            "X-API-Key": self.API_KEY,
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
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

    def fetch_description(self, source_url: str) -> str | None:
        """Lädt den Volltext einer bereits gespeicherten Arbeitsagentur-Stelle
        nach (`v4/jobdetails`).

        Bewusst NICHT Teil von `search()`/`_map_offer()`: ein Detail-Call pro
        Treffer würde bei bis zu 25 Treffern die gemeinsame Such-Deadline
        (KTD1, `JOB_SEARCH_DEADLINE_SECONDS`) sprengen. Wird stattdessen
        einmalig und verzögert für ein einzelnes, bereits gespeichertes
        `JobOffer` aufgerufen (siehe `GET /jobs/{id}`), dessen
        `description_text` noch leer ist.

        Nur möglich, wenn `source_url` auf die eigene Jobdetail-Seite der
        Arbeitsagentur zeigt (kein `externeURL`, siehe `_map_offer`) - nur
        daraus lässt sich die für den Detail-Call nötige Referenznummer
        rekonstruieren. Zeigt `source_url` auf die Karriereseite eines
        Drittanbieters, liefert dies `None`.
        """
        match = self._DETAIL_URL_PATTERN.search(source_url)
        if not match:
            return None
        refnr = unquote(match.group("refnr"))
        encoded_refnr = base64.b64encode(refnr.encode("utf-8")).decode("ascii")

        try:
            response = requests.get(
                f"{self.DETAIL_BASE_URL}/{encoded_refnr}",
                headers=self._headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Arbeitsagentur-Jobdetails für %s nicht erreichbar: %s", source_url, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Arbeitsagentur-Jobdetails lieferten kein valides JSON zurück.")
            return None

        # Die community-gepflegte API-Doku listet beide Feldnamen für
        # dieselbe Beschreibung (siehe bundesAPI/jobsuche-api) - defensiv
        # beide versuchen statt sich auf einen festzulegen.
        raw_description = payload.get("stellenangebotsBeschreibung") or payload.get("stellenbeschreibung") or ""
        if not raw_description:
            return None
        return strip_html(raw_description)


class GenericJobScraper:
    """Generischer Fallback-Scraper für Stellenanzeigen-Webseiten ohne API.

    Dünner Konsument der geteilten Extraktions-Helfer in
    `app.services.job_sources.shared` (KTD2): die zweistufige Extraktion
    (bevorzugt `schema.org/JobPosting`-JSON-LD, sonst heuristische Karten-
    Erkennung) und die HTML-Beschaffung liegen dort und werden von allen
    HTML-Quellen geteilt. `SOURCE_PLATFORM` bleibt "web-scraper", weil dieser
    Pfad eine beliebige, unbenannte Fallback-URL lädt - benannte Boards nutzen
    stattdessen ihren `BoardDescriptor`.
    """

    SOURCE_PLATFORM = "web-scraper"
    _MAX_HEURISTIC_RESULTS = MAX_HEURISTIC_RESULTS

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
        html = fetch_html(url, use_playwright=self._use_playwright, timeout=self._timeout)
        if not html:
            return []
        return self._extract_offers(html, source_url=url)

    # --- Extraktion (dünne Delegationen auf die geteilte Schicht) --------

    def _extract_offers(self, html: str, source_url: str) -> list[JobOfferCreate]:
        return extract_offers(
            html,
            source_url,
            self.SOURCE_PLATFORM,
            max_results=self._MAX_HEURISTIC_RESULTS,
        )

    def _extract_json_ld_offers(self, soup: Any, source_url: str) -> list[JobOfferCreate]:
        return extract_json_ld_offers(soup, source_url, self.SOURCE_PLATFORM)

    def _map_json_ld_offer(self, item: dict[str, Any], source_url: str) -> JobOfferCreate | None:
        return map_json_ld_offer(item, source_url, self.SOURCE_PLATFORM)

    def _extract_heuristic_offers(self, soup: Any, source_url: str) -> list[JobOfferCreate]:
        return extract_heuristic_offers(
            soup,
            source_url,
            self.SOURCE_PLATFORM,
            max_results=self._MAX_HEURISTIC_RESULTS,
        )


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
        self._deadline_seconds = (
            deadline_seconds if deadline_seconds is not None else settings.JOB_SEARCH_DEADLINE_SECONDS
        )
        # Xings innerer Timeout darf laut KTD6 die äußere Such-Deadline nie
        # überschreiten - sonst hält ein Xing-Render, das erst nach der
        # Deadline abbricht, den Playwright-Semaphore länger als nötig,
        # während der Rest der Antwort schon zurückgegeben wurde. Ein Sicherheits-
        # abstand von 1s lässt Playwright selbst noch sauber abbrechen können.
        self._xing_client = xing_client or XingJobScraper(
            inner_timeout=max(1.0, self._deadline_seconds - 1.0)
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
            # Auch der Fallback-Pfad bekommt einen Status-Eintrag - sonst
            # verletzt die Antwort ihre eigene Zusicherung, dass `sources`
            # jede Quelle abdeckt, die zu `results` beiträgt (z. B. würde die
            # Frontend-Statusleiste sonst alle drei Primärquellen als
            # "unavailable" zeigen, obwohl der Fallback Treffer geliefert hat).
            fallback_status = "ok" if fallback_results else "unavailable"
            sources.append(
                SourceStatus(
                    platform=GenericJobScraper.SOURCE_PLATFORM,
                    status=fallback_status,
                    reason=None if fallback_results else "empty",
                )
            )

        return JobSearchResponse(results=results, sources=sources)

    def enrich_description(self, source_platform: str, source_url: str) -> str | None:
        """Lädt nachträglich den vollen Anzeigetext für ein einzelnes,
        bereits gespeichertes `JobOffer` nach, dessen `description_text`
        noch leer ist (siehe `GET /jobs/{id}`).

        Nur Arbeitsagentur und Xing unterstützen einen Detail-Call; Suchtreffer
        werden nie persistiert (KTD2), daher kann dieser Nachlade-Schritt erst
        hier, für die eine tatsächlich gespeicherte Stelle, laufen - nicht
        schon während `search()` für bis zu 25 Treffer gleichzeitig (siehe
        die Docstrings von `ArbeitsagenturJobsClient.fetch_description`/
        `XingJobScraper.fetch_description`). Für andere Quellen (LinkedIn,
        der generische Fallback-Scraper, der `description_text` bereits beim
        Scrapen füllt) ein No-Op.
        """
        if source_platform == ArbeitsagenturJobsClient.SOURCE_PLATFORM:
            return self._arbeitsagentur_client.fetch_description(source_url)
        if source_platform == XingJobScraper.SOURCE_PLATFORM:
            return self._xing_client.fetch_description(source_url)
        return None


def get_job_search_service() -> JobSearchService:
    """FastAPI-Dependency-Provider für den `JobSearchService`."""
    return JobSearchService()
