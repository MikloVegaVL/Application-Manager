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

Die Suche läuft NICHT über `https://devjobs.de/jobs?search=...`: devjobs.de
wertet Suchparameter erst auf der Route `/jobs/search` aus (ce-debug
2026-09-16, live verifiziert - jeder `?search=`/`?q=`/`?query=`-Wert auf
`/jobs` liefert dieselben generischen Karten). Freitext trifft über
`?text=<keywords>`; ein Ort wird über `?locations=<slug>` gefiltert, wobei
der Slug aus dem Autocomplete-Endpunkt
`https://devjobs.de/jobs.data?query=<Ort>&mode=search` stammt (z. B.
`berlin-62422`). Ohne auflösbaren Ort wird deutschlandweit gesucht - der
Client filtert Treffer nicht mehr selbst nach, weil die serverseitige Suche
das bereits tut.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import (
    DEFAULT_USER_AGENT,
    render_html,
    validate_source_url,
)

logger = logging.getLogger(__name__)

_COMPANY_CLASS_PATTERN = re.compile(r"font-semibold")
_DESCRIPTION_CLASS_PATTERN = re.compile(r"line-clamp")


class DevjobsScraper:
    """Scraped devjobs.de's per Playwright gerenderte Suchergebnisseite."""

    SOURCE_PLATFORM = "devjobs"
    SEARCH_URL = "https://devjobs.de/jobs/search"
    LOCATION_LOOKUP_URL = "https://devjobs.de/jobs.data"
    LOCATION_LOOKUP_ROUTES = "routes/jobs"
    _MAX_RESULTS = 25
    _LOCATION_LOOKUP_TIMEOUT = 5.0
    _LOCATION_LOOKUP_HEADERS = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }

    def __init__(self, inner_timeout: float = 15.0) -> None:
        self._inner_timeout = inner_timeout

    def search(
        self,
        keywords: str,
        location: str | None = None,
        radius_km: int | None = None,
    ) -> list[JobOfferCreate]:
        """Sucht Stellenangebote über devjobs.de's gerenderte Suchergebnisseite.

        `radius_km` wird angenommen, aber ignoriert: devjobs.de kennt keinen
        Umkreis-Parameter.

        Liefert bei jedem Fehlerfall eine leere Liste statt einer Exception -
        der Aufrufer (`JobSearchService`) entscheidet anhand des Ergebnisses
        über den Status "unavailable".
        """
        query = {"text": keywords}
        location_slug = self._resolve_location_slug(location)
        if location_slug:
            query["locations"] = location_slug
        url = f"{self.SEARCH_URL}?{urlencode(query)}"

        html = render_html(url, timeout=self._inner_timeout)
        if not html:
            return []
        return self._extract_offers(html, source_url=url)

    # --- Ort -> Slug ------------------------------------------------------

    def _resolve_location_slug(self, location: str | None) -> str | None:
        """Löst einen Ortsnamen über devjobs' Autocomplete in einen Slug auf.

        Gibt `None` zurück, wenn kein Ort angegeben ist, die Suche fehlschlägt
        oder kein exakter Treffer existiert - dann wird deutschlandweit
        gesucht statt mit einem falschen Ort zu filtern.
        """
        if not location or not location.strip():
            return None
        try:
            response = requests.get(
                self.LOCATION_LOOKUP_URL,
                params={
                    "query": location,
                    "mode": "search",
                    "_routes": self.LOCATION_LOOKUP_ROUTES,
                },
                headers=self._LOCATION_LOOKUP_HEADERS,
                timeout=self._LOCATION_LOOKUP_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - fehlende Ortsauflösung darf die Suche nicht verhindern
            logger.warning(
                "devjobs-Ortssuche für '%s' fehlgeschlagen (%s).",
                location,
                type(exc).__name__,
            )
            return None
        return self._pick_location_slug(payload, location)

    @classmethod
    def _pick_location_slug(cls, payload: object, location: str) -> str | None:
        """Wählt den exakt passenden Ort aus der Autocomplete-Antwort."""
        try:
            search = cls._resolve_payload(payload, 0)["routes/jobs"]["data"]["search"]
            candidates = search.get("locations") or []
        except (KeyError, IndexError, TypeError, ValueError):
            return None

        wanted = cls._normalize_location(location)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            title = cls._normalize_location(str(candidate.get("title", "")))
            if title == wanted:
                slug = candidate.get("slug")
                return slug if isinstance(slug, str) and slug else None
        return None

    @staticmethod
    def _normalize_location(value: str) -> str:
        normalized = value.strip().lower()
        for umlaut, ascii_form in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            normalized = normalized.replace(umlaut, ascii_form)
        return normalized

    @staticmethod
    def _resolve_payload(data: object, index: int) -> object:
        """Löst Remix' Single-Fetch-Format auf (flaches Array mit `_n`-Refs).

        Jeder Objekt-Schlüssel `_n` verweist auf den Array-Index, der den
        echten Schlüsselnamen trägt; jeder Wert ist ein Array-Index.
        """
        if not isinstance(data, list) or index >= len(data):
            return None
        value = data[index]
        if isinstance(value, dict):
            resolved: dict[object, object] = {}
            for key, ref in value.items():
                real_key = data[int(key[1:])] if key.startswith("_") else key
                resolved[real_key] = (
                    DevjobsScraper._resolve_payload(data, ref)
                    if isinstance(ref, int)
                    else ref
                )
            return resolved
        if isinstance(value, list):
            return [DevjobsScraper._resolve_payload(data, item) for item in value]
        return value

    # --- Karten-Extraktion ------------------------------------------------

    def _extract_offers(self, html: str, source_url: str) -> list[JobOfferCreate]:
        soup = BeautifulSoup(html, "html.parser")
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
            offers.append(offer)
            if len(offers) >= self._MAX_RESULTS:
                break

        return offers
