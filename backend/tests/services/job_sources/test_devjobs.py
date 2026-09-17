"""Tests für `DevjobsScraper` (siehe backend/app/services/job_sources/devjobs.py).

devjobs.de blockt einen einfachen `requests`-Abruf per Cloudflare und rendert
seine Job-Karten als reine Tailwind-Utility-Markup ohne "job"/"company"-
artige Klassennamen (ce-debug-Untersuchung, 2026-09-13) - daher eigener
Playwright-Client statt des generischen `BoardSource`-Pfads.

Regression (ce-debug 2026-09-16): Die Suche lief zuvor über
`/jobs?search=...`, was devjobs.de ignoriert - die Seite lieferte für jedes
Keyword dieselben generischen Karten. Korrekt ist die Route
`/jobs/search?text=<keywords>` (Freitext) plus `?locations=<slug>` (Ort),
siehe `test_search_url_uses_text_endpoint` /
`test_location_is_resolved_to_slug`.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.job_sources import devjobs as devjobs_module
from app.services.job_sources import shared as shared_module
from app.services.job_sources.devjobs import DevjobsScraper

# Echte Karten-Struktur (siehe ce-debug-Untersuchung, 2026-09-13): jede Karte
# ist ein <a href="/job/..."> mit genau einem <h2> (Titel), einem <span>
# (Ort) und zwei <p> (erstes = Firma via "font-semibold", zweites =
# Beschreibung via "line-clamp").
TWO_CARDS_HTML = """
<html><body>
  <a href="/job/aaa111">
    <h2>Applied AI Engineer</h2>
    <p class="w-full font-semibold">SIXT SE</p>
    <span class="truncate">Pullach im Isartal</span>
    <p class="line-clamp-2 font-normal">Baut KI-Lösungen.</p>
  </a>
  <a href="/job/bbb222">
    <h2>Backend Engineer</h2>
    <p class="w-full font-semibold">Beta AG</p>
    <span class="truncate">Berlin</span>
    <p class="line-clamp-2 font-normal">Baut APIs.</p>
  </a>
</body></html>
"""

ZERO_CARDS_HTML = "<html><body><p>Keine Ergebnisse</p></body></html>"

ONE_BROKEN_ONE_VALID_HTML = f"""
<html><body>
  <a href="/job/broken">
    <h2>{"x" * 300}</h2>
    <p class="font-semibold">Beta AG</p>
  </a>
  <a href="/job/safe-1">
    <h2>Safe Job</h2>
    <p class="font-semibold">Acme GmbH</p>
  </a>
</body></html>
"""


def _fake_playwright(html: str):
    page = MagicMock()
    page.goto = MagicMock()
    page.content = MagicMock(return_value=html)

    browser = MagicMock()
    browser.new_page = MagicMock(return_value=page)
    browser.close = MagicMock()

    playwright = MagicMock()
    playwright.chromium.launch = MagicMock(return_value=browser)
    return playwright, page


def _patch_playwright(mocker, html: str) -> MagicMock:
    """Patcht Playwright und liefert die Fake-Page zurück (für URL-Asserts)."""
    playwright, page = _fake_playwright(html)

    @contextmanager
    def _cm():
        yield playwright

    mocker.patch.object(shared_module, "sync_playwright", _cm)
    return page


def _remix_locations_payload(*locations: dict) -> list:
    """Baut eine minimale Antwort im Remix-Single-Fetch-Format.

    Objekt-Schlüssel wie `_10` verweisen auf den Array-Index mit dem echten
    Schlüsselnamen; die Werte sind Array-Indizes auf die jeweiligen Werte.
    """
    data: list = [
        {"_1": 2},
        "routes/jobs",
        {"_3": 4},
        "data",
        {"_5": 6},
        "search",
        {"_7": 8},
        "locations",
        [],
    ]
    indices = []
    for loc in locations:
        base = len(data)
        data.append({"_10": base + 2, "_12": base + 4, "_14": base + 6})
        data.extend(["id", loc["id"]])
        data.extend(["slug", loc["slug"]])
        data.extend(["title", loc["title"]])
        indices.append(base)
    data[8] = indices
    return data


def _patch_location_lookup(mocker, *locations: dict):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=_remix_locations_payload(*locations))
    return mocker.patch.object(devjobs_module.requests, "get", return_value=response)


def _query(page: MagicMock) -> dict:
    url = page.goto.call_args.args[0]
    return parse_qs(urlparse(url).query)


@pytest.fixture(autouse=True)
def _restore_semaphore():
    import threading

    original = shared_module.playwright_launch_semaphore
    shared_module.playwright_launch_semaphore = threading.Semaphore(2)
    yield
    shared_module.playwright_launch_semaphore = original


def test_happy_path_returns_mapped_offers(mocker):
    page = _patch_playwright(mocker, TWO_CARDS_HTML)
    _patch_location_lookup(mocker, {"id": "1", "slug": "berlin-62422", "title": "Berlin"})

    offers = DevjobsScraper().search("Engineer", "Berlin")

    assert len(offers) == 2
    assert all(offer.source_platform == "devjobs" for offer in offers)
    assert offers[0].title == "Applied AI Engineer"
    assert offers[0].company == "SIXT SE"
    assert offers[0].location == "Pullach im Isartal"
    assert offers[0].description_text == "Baut KI-Lösungen."
    assert offers[0].source_url == "https://devjobs.de/job/aaa111"


def test_search_url_uses_text_endpoint(mocker):
    """Regression (ce-debug 2026-09-16): die Suche muss über
    `/jobs/search?text=` laufen - `/jobs?search=` wird von der Seite ignoriert."""
    page = _patch_playwright(mocker, TWO_CARDS_HTML)

    DevjobsScraper().search("Applied AI")

    url = page.goto.call_args.args[0]
    assert url.startswith("https://devjobs.de/jobs/search?")
    assert parse_qs(urlparse(url).query) == {"text": ["Applied AI"]}


def test_search_accepts_and_ignores_radius(mocker):
    """`JobSearchService` ruft jede Quelle mit `radius_km=` auf; devjobs.de
    kennt keinen Umkreis-Parameter, die Signatur muss ihn aber annehmen."""
    page = _patch_playwright(mocker, TWO_CARDS_HTML)

    offers = DevjobsScraper().search("Python", "Berlin", radius_km=25)

    assert len(offers) == 2
    assert "radius" not in "".join(_query(page).keys())


def test_location_is_resolved_to_slug(mocker):
    page = _patch_playwright(mocker, TWO_CARDS_HTML)
    _patch_location_lookup(
        mocker,
        {"id": "1", "slug": "berlin-62422", "title": "Berlin"},
        {"id": "2", "slug": "berlin-txl", "title": "Berlin TXL"},
    )

    DevjobsScraper().search("Python", "Berlin")

    assert _query(page)["locations"] == ["berlin-62422"]


def test_unknown_location_is_omitted(mocker):
    """Kein exakter Ortstreffer -> deutschlandweit statt falscher Ort."""
    page = _patch_playwright(mocker, TWO_CARDS_HTML)
    _patch_location_lookup(mocker, {"id": "1", "slug": "berlin-62422", "title": "Berlin"})

    DevjobsScraper().search("Python", "Frankfurt")

    assert "locations" not in _query(page)


def test_location_lookup_failure_is_ignored(mocker):
    page = _patch_playwright(mocker, TWO_CARDS_HTML)
    mocker.patch.object(devjobs_module.requests, "get", side_effect=RuntimeError("offline"))

    offers = DevjobsScraper().search("Python", "Berlin")

    assert len(offers) == 2
    assert "locations" not in _query(page)


def test_location_is_not_looked_up_without_location(mocker):
    _patch_playwright(mocker, TWO_CARDS_HTML)
    lookup = _patch_location_lookup(mocker)

    DevjobsScraper().search("Python")

    lookup.assert_not_called()


def test_location_lookup_matches_ascii_umlaut_spelling(mocker):
    page = _patch_playwright(mocker, TWO_CARDS_HTML)
    _patch_location_lookup(mocker, {"id": "1", "slug": "muenchen-62428", "title": "München"})

    DevjobsScraper().search("Python", "Muenchen")

    assert _query(page)["locations"] == ["muenchen-62428"]


def test_pick_location_slug_parses_remix_payload():
    payload = _remix_locations_payload(
        {"id": "1", "slug": "berlin-62422", "title": "Berlin"},
        {"id": "2", "slug": "hamburg-62782", "title": "Hamburg"},
    )

    assert DevjobsScraper._pick_location_slug(payload, "Hamburg") == "hamburg-62782"
    assert DevjobsScraper._pick_location_slug(payload, "Nowhere") is None
    assert DevjobsScraper._pick_location_slug({"unexpected": True}, "Berlin") is None


def test_zero_cards_returns_empty_list(mocker):
    _patch_playwright(mocker, ZERO_CARDS_HTML)

    assert DevjobsScraper().search("Nonexistent Role") == []


def test_rendering_failure_returns_empty_list_without_raising(mocker):
    mocker.patch.object(shared_module, "sync_playwright", None)

    assert DevjobsScraper().search("Angular") == []


def test_one_malformed_card_does_not_discard_the_others(mocker):
    _patch_playwright(mocker, ONE_BROKEN_ONE_VALID_HTML)

    offers = DevjobsScraper().search("Safe")

    assert [offer.title for offer in offers] == ["Safe Job"]


def test_unsafe_result_url_is_rejected(mocker):
    html = """
    <html><body>
      <a href="javascript:alert(1)"><h2>Unsafe Job</h2></a>
      <a href="/job/safe-1"><h2>Safe Job</h2></a>
    </body></html>
    """
    _patch_playwright(mocker, html)

    offers = DevjobsScraper().search("Safe")

    assert [offer.title for offer in offers] == ["Safe Job"]
