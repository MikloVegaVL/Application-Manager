"""Tests für `DevjobsScraper` (siehe backend/app/services/job_sources/devjobs.py).

devjobs.de blockt einen einfachen `requests`-Abruf per Cloudflare und rendert
seine Job-Karten als reine Tailwind-Utility-Markup ohne "job"/"company"-
artige Klassennamen (ce-debug-Untersuchung, 2026-09-13) - daher eigener
Playwright-Client statt des generischen `BoardSource`-Pfads.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

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


def _fake_playwright(html: str) -> MagicMock:
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
    playwright = _fake_playwright(html)

    @contextmanager
    def _cm():
        yield playwright

    return _cm


@pytest.fixture(autouse=True)
def _restore_semaphore():
    import threading

    original = shared_module.playwright_launch_semaphore
    shared_module.playwright_launch_semaphore = threading.Semaphore(2)
    yield
    shared_module.playwright_launch_semaphore = original


def test_happy_path_returns_mapped_offers(mocker):
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(TWO_CARDS_HTML))

    offers = DevjobsScraper().search("Angular", "Berlin")

    assert len(offers) == 2
    assert all(offer.source_platform == "devjobs" for offer in offers)
    assert offers[0].title == "Applied AI Engineer"
    assert offers[0].company == "SIXT SE"
    assert offers[0].location == "Pullach im Isartal"
    assert offers[0].description_text == "Baut KI-Lösungen."
    assert offers[0].source_url == "https://devjobs.de/job/aaa111"


def test_zero_cards_returns_empty_list(mocker):
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(ZERO_CARDS_HTML))

    assert DevjobsScraper().search("Nonexistent Role") == []


def test_rendering_failure_returns_empty_list_without_raising(mocker):
    mocker.patch.object(shared_module, "sync_playwright", None)

    assert DevjobsScraper().search("Angular") == []


def test_one_malformed_card_does_not_discard_the_others(mocker):
    mocker.patch.object(
        shared_module, "sync_playwright", _fake_sync_playwright_factory(ONE_BROKEN_ONE_VALID_HTML)
    )

    offers = DevjobsScraper().search("Angular")

    assert [offer.title for offer in offers] == ["Safe Job"]


def test_unsafe_result_url_is_rejected(mocker):
    html = """
    <html><body>
      <a href="javascript:alert(1)"><h2>Unsafe Job</h2></a>
      <a href="/job/safe-1"><h2>Safe Job</h2></a>
    </body></html>
    """
    mocker.patch.object(shared_module, "sync_playwright", _fake_sync_playwright_factory(html))

    offers = DevjobsScraper().search("Angular")

    assert [offer.title for offer in offers] == ["Safe Job"]
