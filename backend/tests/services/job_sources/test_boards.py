"""Tests für die acht HTML-Board-Quellen (U6).

Siehe backend/app/services/job_sources/boards.py und den Plan
docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md
(U6, R1/R2/R3/R4/R6/R10; KD2/KD4; KTD2/KTD6/KTD10).

Kein Test macht einen echten Netzwerkaufruf: die Beschaffung läuft über
`requests_mock`, der generische Extraktionspfad nutzt `requests` (kein
Playwright) für alle Boards.
"""
from __future__ import annotations

import re

import pytest
from requests_mock import ANY

from app.core.config import settings
from app.schemas.job_offer import JobOfferCreate
from app.services.job_search_service import JobSearchService, SourceRegistration
from app.services.job_sources.boards import BOARD_DESCRIPTORS, BoardSource

BOARD_KEYS = (
    "devjobs",
    "kimeta",
    "stepstone",
    "germantechjobs",
    "indeed",
    "jobware",
    "programmiererjobboerse",
    "it-entwickler-jobs",
)

# Die zugehörigen Enable-Flags aus U3 (KTD7).
BOARD_FLAGS = (
    "JOB_SEARCH_DEVJOBS_ENABLED",
    "JOB_SEARCH_KIMETA_ENABLED",
    "JOB_SEARCH_STEPSTONE_ENABLED",
    "JOB_SEARCH_GERMANTECHJOBS_ENABLED",
    "JOB_SEARCH_INDEED_ENABLED",
    "JOB_SEARCH_JOBWARE_ENABLED",
    "JOB_SEARCH_PROGRAMMIERERJOBBOERSE_ENABLED",
    "JOB_SEARCH_IT_ENTWICKLER_JOBS_ENABLED",
)

JSON_LD_HTML = """
<html><body>
  <script type="application/ld+json">
    {"@type": "JobPosting", "title": "Backend Engineer",
     "hiringOrganization": {"name": "Beta AG"},
     "jobLocation": {"address": {"addressLocality": "Munich"}},
     "description": "<p>Bewirb dich <b>jetzt</b></p>",
     "url": "https://beta.example/jobs/1"}
  </script>
</body></html>
"""

HEURISTIC_HTML = """
<html><body>
  <article class="job-card">
    <a href="https://devjobs.de/jobs/angular-developer"><h2>Angular Developer</h2></a>
    <span class="company">Acme GmbH</span>
    <span class="location">Berlin</span>
    <span class="salary">50.000 - 70.000 EUR</span>
    <span class="homeoffice">2 Tage/Woche</span>
  </article>
</body></html>
"""

# Zwei Karten mit unterschiedlichen Gehaltsangaben - beweist, dass jede Karte
# NUR ihr eigenes Gehalt bekommt (nicht das der ganzen Seite).
TWO_CARDS_SALARY_HTML = """
<html><body>
  <article class="job-card">
    <a href="https://devjobs.de/jobs/angular-developer"><h2>Angular Developer</h2></a>
    <span class="salary">50.000 EUR</span>
  </article>
  <article class="job-card">
    <a href="https://devjobs.de/jobs/backend-engineer"><h2>Backend Engineer</h2></a>
    <span class="salary">70.000 EUR</span>
  </article>
</body></html>
"""

# Eine Karte ohne echten Detail-Link (kein <a href>) darf nicht die
# Suchseite als `source_url` persistieren.
NO_LINK_CARD_HTML = """
<html><body>
  <article class="job-card">
    <h2>No Link Job</h2>
  </article>
  <article class="job-card">
    <a href="https://devjobs.de/jobs/safe-1"><h2>Safe Job</h2></a>
  </article>
</body></html>
"""

# Eine Karte mit einem Titel jenseits von JobOfferCreate.title's max_length=255
# (Pydantic-ValidationError), gefolgt von einer gültigen Karte - beweist, dass
# eine defekte Karte nicht das ganze Board verwirft.
ONE_BROKEN_ONE_VALID_HTML = f"""
<html><body>
  <article class="job-card">
    <a href="https://devjobs.de/jobs/broken"><h2>{"x" * 300}</h2></a>
  </article>
  <article class="job-card">
    <a href="https://devjobs.de/jobs/safe-1"><h2>Safe Job</h2></a>
  </article>
</body></html>
"""

NO_RESULTS_HTML = """
<html><body>
  <div class="job-list"><p>Keine Treffer gefunden.</p></div>
</body></html>
"""


# --- Deskriptoren -----------------------------------------------------------


def test_eight_distinct_board_platform_keys():
    """Verification: alle acht Plattform-Schlüssel sind eindeutig und keiner
    ist der generische "web-scraper" (R4/R6)."""
    keys = [descriptor.source_platform for descriptor in BOARD_DESCRIPTORS]

    assert len(keys) == 8
    assert len(set(keys)) == 8
    assert set(keys) == set(BOARD_KEYS)
    assert "web-scraper" not in keys


def test_search_url_builder_derives_a_public_url_with_keyword_and_location():
    for descriptor in BOARD_DESCRIPTORS:
        url = descriptor.build_search_url("Angular Developer", "Berlin")

        assert url.startswith("https://")
        assert "Berlin" in url


@pytest.mark.parametrize(
    "descriptor", BOARD_DESCRIPTORS, ids=lambda d: d.source_platform
)
def test_each_descriptor_yields_offers_tagged_with_its_own_platform(requests_mock, descriptor):
    """Happy path: jeder der acht Deskriptoren liefert Angebote mit SEINEM
    Plattform-Schlüssel - gemockt über requests_mock mit JSON-LD-Fixture."""
    requests_mock.get(ANY, text=JSON_LD_HTML)

    offers = BoardSource(descriptor).search("Angular", "Berlin")

    assert len(offers) == 1
    assert offers[0].source_platform == descriptor.source_platform
    assert offers[0].source_platform != "web-scraper"
    assert offers[0].title == "Backend Engineer"


# --- Edge: leere/ungültige Treffer -----------------------------------------


def test_zero_parseable_offers_reports_empty(requests_mock):
    """Edge: eine Seite ohne erkennbare Job-Karten liefert eine leere Liste
    (der Orchestrator kennzeichnet das als `empty`)."""
    requests_mock.get(ANY, text=NO_RESULTS_HTML)

    assert BoardSource(BOARD_DESCRIPTORS[0]).search("Angular") == []


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "ftp://example.com/job/1",
        "http://192.168.1.5/job/1",
        "http://localhost:8000/job/1",
        "http://127.0.0.1/job/1",
    ],
)
def test_non_http_or_private_result_url_is_rejected(requests_mock, unsafe_url):
    """R3/KTD10: eine nicht-http(s)- oder private Ziel-URL wird verworfen,
    öffentliche Treffer derselben Seite bleiben erhalten."""
    html = f"""
    <html><body>
      <article class="job-card">
        <a href="{unsafe_url}"><h2>Unsafe Job</h2></a>
      </article>
      <article class="job-card">
        <a href="https://devjobs.de/jobs/safe-1"><h2>Safe Job</h2></a>
      </article>
    </body></html>
    """
    requests_mock.get(ANY, text=html)

    offers = BoardSource(BOARD_DESCRIPTORS[0]).search("Angular")

    assert [offer.title for offer in offers] == ["Safe Job"]
    assert offers[0].source_url == "https://devjobs.de/jobs/safe-1"


# --- Integration: Salary/Homeoffice ----------------------------------------


def test_salary_homeoffice_prose_folds_into_description_text(requests_mock):
    """R10/KTD6: Gehalts-/Homeoffice-Prosa landet über den geteilten Helfer in
    `description_text` - ohne neues strukturiertes Feld."""
    requests_mock.get(ANY, text=HEURISTIC_HTML)

    offers = BoardSource(BOARD_DESCRIPTORS[0]).search("Angular", "Berlin")

    assert len(offers) == 1
    assert "Gehalt: 50.000 - 70.000 EUR" in offers[0].description_text
    assert "Homeoffice: 2 Tage/Woche" in offers[0].description_text
    assert "salary" not in JobOfferCreate.model_fields
    assert "homeoffice" not in JobOfferCreate.model_fields


def test_salary_is_attributed_per_card(requests_mock):
    """R10/KTD6: jede Karte bekommt nur ihr eigenes Gehalt - nicht das der
    ganzen Seite (früher wurde einmal global aus dem Soup gelesen)."""
    requests_mock.get(ANY, text=TWO_CARDS_SALARY_HTML)

    offers = BoardSource(BOARD_DESCRIPTORS[0]).search("Angular")

    by_title = {offer.title: offer for offer in offers}
    assert "Gehalt: 50.000 EUR" in by_title["Angular Developer"].description_text
    assert "Gehalt: 70.000 EUR" in by_title["Backend Engineer"].description_text
    assert "70.000" not in by_title["Angular Developer"].description_text
    assert "50.000" not in by_title["Backend Engineer"].description_text


# --- Error: Karten ohne Detail-Link / defekte Karten -----------------------


def test_card_without_a_detail_link_is_dropped(requests_mock):
    """R3: eine Karte ohne echten `<a href>` darf nicht die Suchseite als
    `source_url` persistieren."""
    requests_mock.get(ANY, text=NO_LINK_CARD_HTML)

    offers = BoardSource(BOARD_DESCRIPTORS[0]).search("Angular")

    assert [offer.title for offer in offers] == ["Safe Job"]
    assert offers[0].source_url == "https://devjobs.de/jobs/safe-1"


def test_one_malformed_card_does_not_discard_the_whole_board(requests_mock):
    """Error: eine defekte Karte (hier: zu langer Titel) darf die übrigen
    Karten desselben Boards nicht verwerfen."""
    requests_mock.get(ANY, text=ONE_BROKEN_ONE_VALID_HTML)

    offers = BoardSource(BOARD_DESCRIPTORS[0]).search("Angular")

    assert [offer.title for offer in offers] == ["Safe Job"]


# --- Error-Isolation über den Orchestrator ---------------------------------


def test_one_board_fetch_failure_leaves_the_other_seven_unaffected(requests_mock):
    """Error: fällt der Abruf eines Boards aus, liefern die übrigen sieben
    weiterhin Treffer und `ok`-Status."""
    # ANY zuerst registrieren, die konkrete Fehler-URL danach - requests_mock
    # prüft die zuletzt registrierten Matcher zuerst.
    requests_mock.get(ANY, text=JSON_LD_HTML)
    requests_mock.get(re.compile(r"https://de\.indeed\.com/.*"), status_code=500)

    service = JobSearchService(
        sources=[
            SourceRegistration(BoardSource(descriptor, timeout=1.0))
            for descriptor in BOARD_DESCRIPTORS
        ],
        deadline_seconds=2.0,
    )

    response = service.search("Angular", "Berlin")

    ok_platforms = {status.platform for status in response.sources if status.status == "ok"}
    assert ok_platforms == set(BOARD_KEYS) - {"indeed"}

    indeed_status = next(status for status in response.sources if status.platform == "indeed")
    assert indeed_status.status == "unavailable"
    assert indeed_status.reason == "empty"

    # Nur die sieben gesunden Boards tragen zu den Ergebnissen bei.
    assert {offer.source_platform for offer in response.results} == ok_platforms
    assert "web-scraper" not in {offer.source_platform for offer in response.results}


# --- Registry-Wiring (KTD7) -------------------------------------------------


def test_registry_registers_all_eight_boards_with_distinct_platforms(monkeypatch):
    for flag in BOARD_FLAGS:
        monkeypatch.setattr(settings, flag, True)

    service = JobSearchService(deadline_seconds=1.0)

    registrations = {
        registration.platform: registration
        for registration in service._sources  # noqa: SLF001 - white-box wiring check
        if registration.platform in BOARD_KEYS
    }
    assert set(registrations) == set(BOARD_KEYS)
    for platform, registration in registrations.items():
        assert registration.client.SOURCE_PLATFORM == platform
        assert registration.client.SOURCE_PLATFORM != "web-scraper"


def test_disabled_board_flag_removes_it_from_the_registry(monkeypatch):
    monkeypatch.setattr(settings, "JOB_SEARCH_INDEED_ENABLED", False)

    service = JobSearchService(deadline_seconds=1.0)

    platforms = [registration.platform for registration in service._sources]  # noqa: SLF001
    assert "indeed" not in platforms
    assert "devjobs" in platforms
