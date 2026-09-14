"""Tests für `XingJobScraper` (siehe backend/app/services/job_sources/xing.py).

Deckt die Testszenarien aus U3 des Plans ab:
docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.services.job_sources import shared as shared_module
from app.services.job_sources.xing import XingJobScraper

# Xings echte Karten-Struktur (siehe ce-debug-Untersuchung, 2026-08-18):
# jede Karte ist ein <article>, dessen erstes Kind ein textloses
# Overlay-<a> ist (der ganzkartige Klick-Link, sein Linktext steckt nur im
# aria-label) - die eigentliche, sichtbare Überschrift (<h2>) kommt erst
# danach. Ein `find()` über ["h1","h2","h3","a"] greift in Dokumentreihenfolge
# daher immer zuerst dieses leere <a> statt der echten Überschrift.
TWO_CARDS_HTML = """
<html><body>
  <article class="job-teaser-card">
    <a class="job-teaser-card__overlay-link" href="/stellenangebote/12345-angular-developer"></a>
    <div class="job-teaser-card__body">
      <h2>Angular Developer</h2>
      <span class="company-name">Acme GmbH</span>
      <span class="job-location">Berlin</span>
    </div>
  </article>
  <article class="job-teaser-card">
    <a class="job-teaser-card__overlay-link" href="https://www.xing.com/stellenangebote/67890-backend-engineer"></a>
    <div class="job-teaser-card__body">
      <h2>Backend Engineer</h2>
      <span class="company-name">Beta AG</span>
      <span class="job-location">Munich</span>
    </div>
  </article>
</body></html>
"""

ZERO_CARDS_HTML = "<html><body><p>Keine Ergebnisse</p></body></html>"

# Xing hat keinen zuverlässigen Länder-Parameter (siehe ce-debug-Untersuchung,
# 2026-08-18: weder ein LinkedIn-artiges `geoId` noch ein wirksamer
# `location`-Freitext-Filter für Länder wie "Deutschland"/"Germany"/"DE" -
# alle drei liefern kommentarlos dieselben ungefilterten Treffer wie gar
# keine Location). Diese Karte mit einer bekannten österreichischen Stadt
# beweist, dass DACH-Nachbarländer sonst mit auftauchen.
ONE_GERMAN_ONE_AUSTRIAN_HTML = """
<html><body>
  <article class="job-teaser-card">
    <a class="job-teaser-card__overlay-link" href="/stellenangebote/11111-german-job"></a>
    <div class="job-teaser-card__body">
      <h2>Backend Engineer Berlin</h2>
      <span class="company-name">Acme GmbH</span>
      <span class="job-location">Berlin</span>
    </div>
  </article>
  <article class="job-teaser-card">
    <a class="job-teaser-card__overlay-link" href="/stellenangebote/22222-austrian-job"></a>
    <div class="job-teaser-card__body">
      <h2>Backend Engineer Wien</h2>
      <span class="company-name">Beta GmbH</span>
      <span class="job-location">Wien</span>
    </div>
  </article>
</body></html>
"""

# Eine Karte mit einem Titel jenseits von JobOfferCreate.title's max_length=255
# (Pydantic-ValidationError), gefolgt von einer normalen, gültigen Karte -
# beweist, dass eine defekte Karte nicht die ganze Extraktion verwirft.
ONE_BROKEN_ONE_VALID_HTML = f"""
<html><body>
  <article class="job-teaser-card">
    <a class="job-teaser-card__overlay-link" href="/stellenangebote/99999-broken"></a>
    <div class="job-teaser-card__body">
      <h2>{"x" * 300}</h2>
      <span class="company-name">Broken GmbH</span>
    </div>
  </article>
  <article class="job-teaser-card">
    <a class="job-teaser-card__overlay-link" href="/stellenangebote/12345-angular-developer"></a>
    <div class="job-teaser-card__body">
      <h2>Angular Developer</h2>
      <span class="company-name">Acme GmbH</span>
      <span class="job-location">Berlin</span>
    </div>
  </article>
</body></html>
"""


def _fake_playwright(html: str) -> MagicMock:
    """Baut ein Fake-`playwright`-Objekt, das `html` als Seiteninhalt liefert."""
    page = MagicMock()
    page.goto = MagicMock()
    page.content = MagicMock(return_value=html)

    browser = MagicMock()
    browser.new_page = MagicMock(return_value=page)
    browser.close = MagicMock()

    playwright = MagicMock()
    playwright.chromium.launch = MagicMock(return_value=browser)
    return playwright


def _fake_sync_playwright_factory(html: str):
    """Baut das Callable, das den lokalen Namen `sync_playwright` ersetzt -
    `sync_playwright()` liefert einen Context Manager, dessen `__enter__`
    das Fake-`playwright`-Objekt zurückgibt (analog zur echten API)."""
    playwright = _fake_playwright(html)

    @contextmanager
    def _cm():
        yield playwright

    return _cm


@pytest.fixture(autouse=True)
def _restore_semaphore():
    """Jeder Test bekommt ein frisches Semaphore, damit Tests sich nicht
    gegenseitig über gehaltene Permits beeinflussen."""
    original = shared_module.playwright_launch_semaphore
    shared_module.playwright_launch_semaphore = threading.Semaphore(2)
    yield
    shared_module.playwright_launch_semaphore = original


def test_happy_path_returns_mapped_offers(mocker):
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(TWO_CARDS_HTML))

    offers = XingJobScraper().search("Angular", "Berlin")

    assert len(offers) == 2
    assert all(offer.source_platform == "xing" for offer in offers)
    assert offers[0].title == "Angular Developer"
    assert offers[0].company == "Acme GmbH"
    assert offers[0].location == "Berlin"


def test_zero_cards_returns_empty_list(mocker):
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(ZERO_CARDS_HTML))

    offers = XingJobScraper().search("Nonexistent Role")

    assert offers == []


def test_one_malformed_card_does_not_discard_the_others(mocker):
    """A card whose fields fail JobOfferCreate's validation (e.g. an
    oversized title) must not abort extraction for the whole page - the
    other, valid cards still come back, mirroring the per-record isolation
    ArbeitsagenturJobsClient/LinkedInJobsClient already use."""
    mocker.patch.object(
        shared_module, "sync_playwright", _fake_sync_playwright_factory(ONE_BROKEN_ONE_VALID_HTML)
    )

    offers = XingJobScraper().search("Angular")

    assert len(offers) == 1
    assert offers[0].title == "Angular Developer"


def test_source_url_is_xing_detail_link_not_search_page(mocker):
    """Covers AE2: der Link zeigt auf die echte Xing-Detailseite der
    Stellenanzeige, nicht auf die Suchergebnisseite."""
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(TWO_CARDS_HTML))

    offers = XingJobScraper().search("Angular")

    assert offers[0].source_url == "https://www.xing.com/stellenangebote/12345-angular-developer"
    assert offers[1].source_url == "https://www.xing.com/stellenangebote/67890-backend-engineer"
    assert "search" not in offers[0].source_url


def test_filters_out_known_non_german_locations(mocker):
    """Best-effort guard: Xing has no reliable country parameter (see
    ce-debug-Untersuchung, 2026-08-18), so a card whose location matches a
    known non-German DACH city (e.g. "Wien") must be dropped even though its
    title/company/link are otherwise perfectly valid. Not a complete fix
    (unlisted cities still slip through - tracked as a follow-up), but it
    closes the gap for the common cases."""
    mocker.patch.object(
        shared_module, "sync_playwright", _fake_sync_playwright_factory(ONE_GERMAN_ONE_AUSTRIAN_HTML)
    )

    offers = XingJobScraper().search("Backend")

    assert len(offers) == 1
    assert offers[0].location == "Berlin"


def test_non_german_cards_do_not_consume_the_max_results_cap(mocker):
    """The country filter must run BEFORE `_MAX_RESULTS` truncates the
    candidate list, not after - otherwise non-German cards near the top of
    the page could exhaust the cap and silently push out real German
    offers further down, with no signal to the caller that anything was
    dropped as foreign rather than simply absent (found by ce-code-review,
    2026-08-18)."""
    mocker.patch.object(XingJobScraper, "_MAX_RESULTS", 2)
    cards = "".join(
        f"""
        <article class="job-teaser-card">
          <a class="job-teaser-card__overlay-link" href="/stellenangebote/{i}"></a>
          <div class="job-teaser-card__body">
            <h2>Job {i}</h2>
            <span class="company-name">Acme GmbH</span>
            <span class="job-location">{location}</span>
          </div>
        </article>
        """
        for i, location in enumerate(["Wien", "Zürich", "Berlin", "Hamburg"])
    )
    html = f"<html><body>{cards}</body></html>"
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(html))

    offers = XingJobScraper().search("Backend")

    assert [offer.location for offer in offers] == ["Berlin", "Hamburg"]


# --- _is_known_non_german_location(): direct unit coverage --------------
#
# The full search()+Playwright-mocked tests above and below prove the filter
# is *wired in*; these test the matching MECHANISM itself in isolation
# (word-boundary regex, casefold, the "Linz am Rhein" carve-out, and the
# None/empty-string early return) without the overhead of building HTML
# fixtures and mocking a browser for every case.

@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (None, False),
        ("", False),
        ("Wien", True),
        ("WIEN", True),  # casefold normalization
        ("Zürich", True),
        ("Berlin", False),
        ("Bernau bei Berlin", False),  # "bern" substring, real German town
        ("Bernburg (Saale)", False),  # "bern" substring, real German town
        ("Bielefeld", False),  # "biel" substring, top-20 German city
        ("Baar-Ebenhausen", False),  # "baar" substring, real Bavarian town
        ("Baar", True),  # the actual Swiss canton/town, unprefixed
        ("Linz am Rhein", False),  # carve-out: real German town
        ("Linz", True),  # Linz, Austria, unprefixed
    ],
)
def test_is_known_non_german_location_direct(location, expected):
    assert XingJobScraper._is_known_non_german_location(location) is expected  # noqa: SLF001


@pytest.mark.parametrize(
    ("name", "location"),
    [
        ("Bernau bei Berlin", "Bernau bei Berlin"),
        ("Bernburg", "Bernburg (Saale)"),
        ("Bielefeld", "Bielefeld"),
        ("Linz am Rhein", "Linz am Rhein"),
        ("Baar-Ebenhausen", "Baar-Ebenhausen"),
    ],
)
def test_non_german_filter_does_not_false_positive_on_similar_german_names(mocker, name, location):
    """Substring matching (`"bern" in location`) would wrongly drop German
    towns whose name merely contains a DACH-neighbor city as a substring -
    "Bernau bei Berlin"/"Bernburg" contain "bern" (Switzerland), "Bielefeld"
    (a top-20 German city) contains "biel" (Switzerland), "Baar-Ebenhausen"
    (a real Bavarian town) contains "baar" (a Swiss canton/town) with only a
    hyphen as separator, and "Linz am Rhein" is a real German town sharing
    its primary name with Linz, Austria. Caught during self-review and
    ce-code-review of the word-boundary filter, 2026-08-18. Parametrized so
    one failing case doesn't hide the others."""
    html = f"""
    <html><body>
      <article class="job-teaser-card">
        <a class="job-teaser-card__overlay-link" href="/stellenangebote/1-{name}"></a>
        <div class="job-teaser-card__body">
          <h2>Backend Engineer {name}</h2>
          <span class="company-name">Acme GmbH</span>
          <span class="job-location">{location}</span>
        </div>
      </article>
    </body></html>
    """
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(html))

    offers = XingJobScraper().search("Backend")

    assert len(offers) == 1, f"{location!r} was wrongly filtered as non-German"
    assert offers[0].location == location


def test_playwright_launch_failure_returns_empty_list_without_raising(mocker):
    @contextmanager
    def _raising_cm():
        raise RuntimeError("simulated launch/navigation failure (e.g. geo-block)")
        yield  # pragma: no cover - unreachable, satisfies generator shape

    mocker.patch.object(shared_module, "sync_playwright", _raising_cm)

    offers = XingJobScraper().search("Angular")

    assert offers == []


def test_inner_timeout_treated_same_as_launch_failure(mocker):
    """Ein Playwright-Timeout beim `page.goto` wird von derselben
    generischen except-Klausel wie ein Start-/Navigationsfehler behandelt -
    leere Liste, keine unbehandelte Exception, kein Hang."""
    page = MagicMock()
    page.goto = MagicMock(side_effect=TimeoutError("Timeout exceeded while navigating"))
    browser = MagicMock()
    browser.new_page = MagicMock(return_value=page)
    browser.close = MagicMock()
    playwright = MagicMock()
    playwright.chromium.launch = MagicMock(return_value=browser)

    @contextmanager
    def _cm():
        yield playwright

    mocker.patch.object(shared_module, "sync_playwright", _cm)

    offers = XingJobScraper(inner_timeout=0.01).search("Angular")

    assert offers == []
    browser.close.assert_called_once()  # Browser wird trotz Timeout sauber geschlossen


# --- fetch_description() (lazy single-detail-page load) -------------------
#
# Covers the ce-debug follow-up (2026-08-20): fetching a detail page for
# every search hit would multiply Playwright launches by up to _MAX_RESULTS
# and blow the shared search deadline (KTD1) - `fetch_description` is
# instead called once, lazily, for a single already-saved JobOffer (see
# `JobSearchService.enrich_description` / `GET /jobs/{id}`).

DETAIL_PAGE_HTML = """
<html><body>
  <h1>Angular Developer</h1>
  <p>Bitte sende deine Bewerbung an bewerbung@acme.example.</p>
</body></html>
"""


def test_fetch_description_returns_the_detail_pages_visible_text(mocker):
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(DETAIL_PAGE_HTML))

    description = XingJobScraper().fetch_description("https://www.xing.com/stellenangebote/12345-angular-developer")

    assert description is not None
    assert "bewerbung@acme.example" in description


def test_fetch_description_returns_none_when_rendering_fails(mocker):
    @contextmanager
    def _raising_cm():
        raise RuntimeError("simulated launch/navigation failure")
        yield  # pragma: no cover - unreachable, satisfies generator shape

    mocker.patch.object(shared_module, "sync_playwright", _raising_cm)

    description = XingJobScraper().fetch_description("https://www.xing.com/stellenangebote/12345")

    assert description is None


def test_concurrent_searches_serialize_on_the_semaphore(mocker):
    """Zwei gleichzeitige `.search()`-Aufrufe dürfen nie gleichzeitig einen
    Browser starten - das Semaphore serialisiert den Start (KTD6), nicht
    die ganze Methode."""
    shared_module.playwright_launch_semaphore = threading.Semaphore(1)

    concurrent_launches = 0
    max_concurrent_launches = 0
    lock = threading.Lock()
    fake_playwright = _fake_playwright(ZERO_CARDS_HTML)

    @contextmanager
    def _slow_cm():
        nonlocal concurrent_launches, max_concurrent_launches
        with lock:
            concurrent_launches += 1
            max_concurrent_launches = max(max_concurrent_launches, concurrent_launches)
        try:
            time.sleep(0.05)  # hält das Semaphore kurz, damit ein zweiter Thread anstehen muss
            yield fake_playwright
        finally:
            with lock:
                concurrent_launches -= 1

    # Jeder Aufruf von `sync_playwright()` liefert einen frischen Context
    # Manager (wie die echte API) - `_slow_cm` selbst ist das Callable,
    # nicht bereits ein aufgerufener Generator.
    mocker.patch.object(shared_module, "sync_playwright", _slow_cm)

    threads = [
        threading.Thread(target=lambda: XingJobScraper().search("Angular"))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_concurrent_launches == 1
