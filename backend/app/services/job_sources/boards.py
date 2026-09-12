"""Generisch gelesene HTML-Jobbörsen (U6).

Definiert je eine `BoardDescriptor` pro benannter Börse mit einem eigenen,
eindeutigen Plattform-Schlüssel und einem Such-URL-Builder (R4/R6, KD4/KTD2).
Die eigentliche Beschaffung/Extraktion läuft über die geteilte Schicht
`job_sources/shared.py` (KTD1/KTD2): kein Board bekommt zunächst einen
eigenen Scraper (R6/KD4).

Die genauen Such-URL-Muster der Börsen sind undokumentiert und können sich
jederzeit ändern. Wo ein Muster nicht bestätigt ist, steht ein Kommentar an
der jeweiligen Definition; die generische Extraktion fällt ohnehin auf
heuristisches HTML zurück und eine nicht lesbare Börse meldet `unavailable`,
statt die übrigen Quellen zu blockieren (R5).

Abhängigkeitsrichtung bleibt einseitig (KTD1): dieses Modul importiert NIE
aus `app.services.job_search_service`.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources.shared import (
    BoardDescriptor,
    BoardSourceAdapter,
    fold_salary_homeoffice,
    make_search_url_builder,
)

# Zusätzliche, quellen-spezifische Klassen-Muster, die für die generische
# Karten-Erkennung in shared.py zu speziell wären: Gehalt und Homeoffice/Remote.
SALARY_CLASS_PATTERN = re.compile(r"salary|gehalt|verguetung|vergütung|pay", re.IGNORECASE)
HOMEOFFICE_CLASS_PATTERN = re.compile(r"homeoffice|home-office|remote", re.IGNORECASE)


def _stepstone_search_url(keywords: str, location: str | None) -> str:
    """Baut Stepstones pfadbasiertes Such-URL-Muster.

    Muster: `https://www.stepstone.de/jobs/<kw>/in-<ort>` (ohne Ort nur
    `/jobs/<kw>`). Die Slugs ersetzen Leerzeichen durch Bindestriche; der
    Rest wird URL-kodiert.
    """
    keyword_slug = quote(keywords.strip().replace(" ", "-"), safe="")
    if location and location.strip():
        location_slug = quote(location.strip().replace(" ", "-"), safe="")
        return f"https://www.stepstone.de/jobs/{keyword_slug}/in-{location_slug}"
    return f"https://www.stepstone.de/jobs/{keyword_slug}"


# Ein Deskriptor pro benannter Börse. Reihenfolge = Anzeige-/Registry-Reihenfolge.
BOARD_DESCRIPTORS: tuple[BoardDescriptor, ...] = (
    BoardDescriptor(
        source_platform="devjobs",
        build_search_url=make_search_url_builder(
            "https://devjobs.de/jobs",
            keyword_param="search",
            location_param="location",
        ),
    ),
    BoardDescriptor(
        source_platform="kimeta",
        # Bestätigtes Muster nicht verfügbar - best-known Query-Parameter.
        build_search_url=make_search_url_builder(
            "https://www.kimeta.de/stellenangebote",
            keyword_param="q",
            location_param="l",
        ),
    ),
    BoardDescriptor(
        source_platform="stepstone",
        build_search_url=_stepstone_search_url,
    ),
    BoardDescriptor(
        source_platform="germantechjobs",
        # Bestätigtes Muster nicht verfügbar - best-known Query-Parameter.
        build_search_url=make_search_url_builder(
            "https://germantechjobs.de/jobs",
            keyword_param="search",
            location_param="location",
        ),
    ),
    BoardDescriptor(
        source_platform="indeed",
        build_search_url=make_search_url_builder(
            "https://de.indeed.com/jobs",
            keyword_param="q",
            location_param="l",
        ),
    ),
    BoardDescriptor(
        source_platform="programmiererjobboerse",
        # Bestätigtes Muster nicht verfügbar - best-known Query-Parameter.
        build_search_url=make_search_url_builder(
            "https://www.programmiererjobboerse.de/stellenangebote",
            keyword_param="search",
            location_param="ort",
        ),
    ),
    BoardDescriptor(
        source_platform="it-entwickler-jobs",
        # Bestätigtes Muster nicht verfügbar - best-known Query-Parameter.
        build_search_url=make_search_url_builder(
            "https://www.it-entwickler-jobs.de/jobs",
            keyword_param="q",
            location_param="location",
        ),
    ),
)


class BoardSource(BoardSourceAdapter):
    """Board-Adapter mit URL-Validierung und Salary/Homeoffice-Prosa (R3/R10).

    Erbt die generische Extraktion aus `shared.BoardSourceAdapter`, verwirft
    zusätzlich unsichere Ziel-URLs (kein `javascript:`/privater Host, KTD10)
    und faltet Gehalts-/Homeoffice-Angaben über den geteilten Helfer in
    `description_text` (KTD6/KD8) - kein neues strukturiertes Feld.

    Gehalt/Homeoffice werden pro Karte gelesen (nicht einmal global aus dem
    Soup), damit jede Anzeige nur ihre eigenen Angaben bekommt.
    """

    def _enrich_offer(self, offer: JobOfferCreate, node: BeautifulSoup) -> None:
        salary_el = node.find(class_=SALARY_CLASS_PATTERN)
        homeoffice_el = node.find(class_=HOMEOFFICE_CLASS_PATTERN)
        salary = salary_el.get_text(" ", strip=True) if salary_el else None
        homeoffice = homeoffice_el.get_text(" ", strip=True) if homeoffice_el else None
        if salary or homeoffice:
            offer.description_text = fold_salary_homeoffice(
                offer.description_text,
                salary=salary,
                homeoffice=homeoffice,
            )
