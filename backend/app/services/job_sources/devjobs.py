"""Client für devjobs.de per Playwright-Rendering.

devjobs.de blockt einen einfachen `requests`-Abruf per Cloudflare (HTTP 403,
verifiziert per ce-debug-Untersuchung, 2026-09-13) - ein echter Browser
kommt durch, daher wird hier (wie bei Xing) per Playwright gerendert statt
über den generischen `BoardSource`-Adapter (der plain `requests` nutzt).

Die gerenderte Seite nutzt außerdem reine Tailwind-Utility-Klassen ohne
"job"/"company"/"location"-artige Namen und ohne JSON-LD - die geteilte
Heuristik in `job_sources/shared.py` (die genau auf solche Namensmuster
matcht) findet hier nichts. Jede Job-Karte ist stattdessen ein
`<a href="/job/...">` mit genau einem `<h2>` (Titel), einem `<span>` (Ort)
und zwei `<p>` (erstes = Firma, zweites = Beschreibung) - stabil genug für
direkte Tag-/Klassen-Selektoren statt der generischen Karten-Heuristik.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import render_html, validate_source_url

logger = logging.getLogger(__name__)

_COMPANY_CLASS_PATTERN = re.compile(r"font-semibold")
_DESCRIPTION_CLASS_PATTERN = re.compile(r"line-clamp")


class DevjobsScraper:
    """Scraped devjobs.de's per Playwright gerenderte Suchergebnisseite.

    Der `?search=`-Query-Parameter unten wird von devjobs.de NICHT
    ausgewertet (ce-debug 2026-09-14, live verifiziert): `/jobs?search=...`
    verwirft den Query-String beim Redirect auf `/jobs/search`, und selbst
    `/jobs/search?search=...`/`?q=...` liefern für jedes Keyword exakt
    dieselben ~15 Angebote - die Suche der Seite läuft rein clientseitig
    über React-State, nicht über die URL. Ohne Gegenmaßnahme wären ALLE
    Treffer unabhängig vom Suchbegriff. `_matches_keywords` filtert daher
    selbst nach, statt sich (wie alle anderen Quellen) auf die Zielseite zu
    verlassen - und zwar VOR dem `_MAX_RESULTS`-Cap in `_extract_offers`
    (analog zu `shared.extract_heuristic_offers`' `include`-Parameter),
    damit eine irrelevante Karte unter den ersten `_MAX_RESULTS` keiner
    relevanten Karte weiter unten den Platz wegnimmt.
    """

    SOURCE_PLATFORM = "devjobs"
    SEARCH_URL = "https://devjobs.de/jobs"
    _MAX_RESULTS = 25
    # ponytail: reiner Substring-Abgleich auf Titel/Firma/Beschreibung, keine
    # echte Relevanzsuche - reicht, um klar unpassende Treffer (z. B. "Business
    # Analyst Controlling" bei Suche "Python") auszusortieren. Falls das zu
    # strikt/lasch ist: die eigentliche clientseitige Such-Interaktion der
    # Seite nachbauen (Tippen ins Suchfeld + auf die gefilterte Kartenliste
    # warten) statt eines URL-Parameters.
    _KEYWORD_PATTERN = re.compile(r"\w+")

    def __init__(self, inner_timeout: float = 15.0) -> None:
        self._inner_timeout = inner_timeout

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über devjobs.de's gerenderte Suchergebnisseite.

        Liefert bei jedem Fehlerfall eine leere Liste statt einer Exception -
        der Aufrufer (`JobSearchService`) entscheidet anhand des Ergebnisses
        über den Status "unavailable".
        """
        query = {"search": keywords}
        if location:
            query["location"] = location
        url = f"{self.SEARCH_URL}?{urlencode(query)}"

        html = render_html(url, timeout=self._inner_timeout)
        if not html:
            return []
        return self._extract_offers(html, source_url=url, keywords=keywords)

    def _keyword_set(self, keywords: str) -> set[str]:
        return {w.lower() for w in self._KEYWORD_PATTERN.findall(keywords) if len(w) >= 3}

    def _matches_keywords(self, offer: JobOfferCreate, keyword_set: set[str]) -> bool:
        if not keyword_set:
            return True
        haystack = " ".join(
            filter(None, [offer.title, offer.company, offer.description_text])
        ).lower()
        return any(word in haystack for word in keyword_set)

    def _extract_offers(self, html: str, source_url: str, keywords: str) -> list[JobOfferCreate]:
        soup = BeautifulSoup(html, "html.parser")
        keyword_set = self._keyword_set(keywords)
        offers: list[JobOfferCreate] = []
        seen_titles: set[str] = set()

        for card in soup.find_all("a", href=re.compile(r"^/job/")):
            title_el = card.find("h2")
            if title_el is None:
                continue
            title = title_el.get_text(strip=True)
            if len(title) < 3 or title in seen_titles:
                continue

            full_url = urljoin(source_url, card["href"])
            if not validate_source_url(full_url):
                continue

            company_el = card.find("p", class_=_COMPANY_CLASS_PATTERN)
            company = company_el.get_text(strip=True) if company_el else "Unbekanntes Unternehmen"

            location_el = card.find("span")
            offer_location = location_el.get_text(strip=True) if location_el else None

            description_el = card.find("p", class_=_DESCRIPTION_CLASS_PATTERN)
            description = description_el.get_text(strip=True) if description_el else None

            seen_titles.add(title)
            try:
                offer = JobOfferCreate(
                    title=title,
                    company=company,
                    location=offer_location,
                    source_url=full_url,
                    description_text=description,
                    source_platform=self.SOURCE_PLATFORM,
                )
            except Exception:  # noqa: BLE001 - eine defekte Karte darf die übrigen nicht verwerfen
                logger.exception("Konnte devjobs-Karte nicht verarbeiten.")
                continue
            if not self._matches_keywords(offer, keyword_set):
                continue
            offers.append(offer)
            if len(offers) >= self._MAX_RESULTS:
                break

        return offers
