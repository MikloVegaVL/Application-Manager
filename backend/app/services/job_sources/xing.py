"""Client für Xings Jobsuche per Playwright-Rendering.

Xing bietet - anders als LinkedIn - weder eine öffentliche Guest-API noch
eingebettete `schema.org/JobPosting`-JSON-LD-Daten. Ergebnisse müssen daher
aus der clientseitig gerenderten Suchergebnisseite extrahiert werden - siehe
KTD6 im Plan
(docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).

Der Browser (Chromium) ist im Backend-Image bereits vorhanden
(`backend/Dockerfile`: `playwright install --with-deps chromium`). Die
Job-Karten werden per CSS-Klassen-Heuristik extrahiert - Xings genaue
CSS-Klassen sind unbestätigt/undokumentiert (siehe Planungsdoc), daher der
gleiche tolerante Ansatz wie in der geteilten Schicht
(`job_sources/shared.py`) statt fest verdrahteter Selektoren.

Die quellenübergreifende Maschinerie (User-Agent, Playwright-Renderlogik
samt begrenztem Start-Semaphore, CSS-Klassen-Muster und Karten-Mapping)
liegt in `job_sources/shared.py` und wird von hier nur konsumiert (KTD1:
`job_sources/` importiert nie aus `job_search_service.py`).

Zwei Ressourcen-Schutzmaßnahmen, weil dieser Client - anders als
`GenericJobScraper`s seltener manueller Fallback-Pfad - bei JEDER Suche
aufgerufen wird (KTD6):

1. Ein eigener innerer Timeout für den Playwright-Aufruf: `ThreadPoolExecutor`s
   äußerer Timeout (KTD1) bricht nur das *Warten* ab, nicht den laufenden
   Browser-Prozess - ohne inneren Timeout liefe ein hängendes Rendering über
   die bereits beantwortete Anfrage hinaus weiter.
2. Das geteilte Semaphore rund um den Browser-Start (nicht um die ganze
   Methode), damit ein Doppel-Tab/Doppel-Klick-Burst nicht beliebig viele
   Chromium-Instanzen gleichzeitig startet.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import (
    extract_heuristic_offers,
    render_html,
    strip_html,
)


class XingJobScraper:
    """Scraped Xings gerenderte Jobsuche-Ergebnisseite per Playwright."""

    SOURCE_PLATFORM = "xing"
    SEARCH_URL = "https://www.xing.com/jobs/search"
    _MAX_RESULTS = 25

    # Best-effort Länderfilter (siehe ce-debug-Untersuchung, 2026-08-18):
    # Xing bietet - anders als LinkedIn ("geoId") - keinen server-seitigen
    # Länder-Parameter; weder ein leerer `location`-Wert noch "Deutschland"/
    # "Germany"/"DE" grenzen die Ergebnisse zuverlässig ein, während eine
    # konkrete DACH-Nachbarstadt (z. B. "Wien") anstandslos deren Treffer
    # liefert. Diese App ist auf den deutschen Arbeitsmarkt ausgerichtet, also
    # werden Karten mit einer bekannten österreichischen/schweizer Großstadt
    # als Ort nachträglich verworfen. Unvollständig by design (nicht gelistete
    # Städte rutschen weiterhin durch) - siehe verlinktes Follow-up-Issue.
    _NON_GERMAN_LOCATION_MARKERS = (
        "österreich", "austria", "schweiz", "switzerland", "suisse", "svizzera",
        "wien", "vienna", "graz", "linz", "salzburg", "innsbruck", "klagenfurt",
        "villach", "wels", "sankt pölten", "st. pölten", "dornbirn",
        "wiener neustadt", "steyr", "feldkirch", "bregenz",
        "zürich", "zurich", "genf", "genève", "geneva", "basel", "bern",
        "lausanne", "winterthur", "luzern", "lucerne", "st. gallen",
        "sankt gallen", "lugano", "biel", "thun", "köniz", "rotkreuz", "zug",
        "baar",
    )

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

    def fetch_description(self, url: str) -> str | None:
        """Lädt die tatsächliche Job-Detailseite (nicht die Suchergebnisseite)
        nach und liefert deren sichtbaren Text.

        Bewusst NICHT Teil von `search()`/`_extract_offers()`: Xing bietet
        keine separate Detail-API (siehe Moduldoc), ein Playwright-Rendern
        JEDES Suchtreffers würde die Suche um bis zu `_MAX_RESULTS` weitere
        Browser-Starts verlangsamen und die gemeinsame Such-Deadline (KTD1)
        sprengen. Wird stattdessen einmalig und verzögert für ein einzelnes,
        bereits gespeichertes `JobOffer` aufgerufen (siehe `GET /jobs/{id}`),
        dessen `description_text` noch leer ist.
        """
        html = self._render(url)
        if not html:
            return None
        return strip_html(html)

    @classmethod
    def _is_known_non_german_location(cls, location: str | None) -> bool:
        if not location:
            return False
        normalized = location.casefold()

        # "Linz" is genuinely ambiguous: Linz, Austria vs. the much smaller
        # Linz am Rhein, Germany. Word-boundary matching alone can't tell
        # them apart ("linz" is a whole word in both), so this carve-out
        # keeps the German one out of the denylist explicitly.
        if "linz am rhein" in normalized:
            return False

        # Word-boundary, not substring: a naive `marker in normalized` check
        # would also match "bern" inside German "Bernau"/"Bernburg" and
        # "biel" inside German "Bielefeld" (a top-20 German city) - both
        # real false positives caught during self-review, 2026-08-18.
        #
        # Plain `\b` treats a hyphen as a boundary too, which still false-
        # positives on hyphenated German compound names sharing a prefix
        # with a marker - "baar" would otherwise match inside the real
        # Bavarian town "Baar-Ebenhausen" (caught by ce-code-review,
        # 2026-08-18). `(?<![\w-])...(?![\w-])` treats a hyphen like a word
        # character for boundary purposes, so a marker immediately followed
        # or preceded by a hyphen-joined word no longer counts as a match.
        return any(
            re.search(rf"(?<![\w-]){re.escape(marker)}(?![\w-])", normalized)
            for marker in cls._NON_GERMAN_LOCATION_MARKERS
        )

    # --- Rendering ------------------------------------------------------

    def _render(self, url: str) -> str | None:
        # Geteilte Renderlogik inkl. Start-Semaphore (KTD1/KTD5).
        return render_html(url, timeout=self._inner_timeout)

    # --- Extraktion -------------------------------------------------

    def _extract_offers(self, html: str, source_url: str) -> list[JobOfferCreate]:
        soup = BeautifulSoup(html, "html.parser")
        # Der Länderfilter läuft VOR dem _MAX_RESULTS-Cap, nicht danach:
        # sonst könnten nicht-deutsche Karten unter den ersten
        # _MAX_RESULTS Kandidaten den Cap für tatsächlich deutsche
        # Angebote weiter unten auf der Seite aufbrauchen, ohne dass der
        # Aufrufer davon erfährt (gefunden von ce-code-review, 2026-08-18).
        return extract_heuristic_offers(
            soup,
            source_url,
            self.SOURCE_PLATFORM,
            max_results=self._MAX_RESULTS,
            require_link=True,
            include=lambda offer: not self._is_known_non_german_location(offer.location),
            isolate_errors=True,
        )
