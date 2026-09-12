"""Tests für die geteilte Quellen-Schicht `job_sources/shared.py`.

Deckt die U1-Testszenarien des Plans ab:
docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.schemas.job_offer import JobOfferCreate
from app.services.job_sources import shared as shared_module

# Karten-Muster wie bei Xing: ein ganzkartiges, textloses Overlay-<a> steht
# im DOM VOR der sichtbaren <h2>-Überschrift.
HEURISTIC_HTML = """
<html><body>
  <article class="job-card">
    <a class="job-card__overlay-link" href="/jobs/angular-developer-123"></a>
    <div class="job-card__body">
      <h2>Angular Developer</h2>
      <span class="company">Acme GmbH</span>
      <span class="location">Berlin</span>
    </div>
  </article>
</body></html>
"""

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
    original = shared_module.playwright_launch_semaphore
    shared_module.playwright_launch_semaphore = threading.Semaphore(2)
    yield
    shared_module.playwright_launch_semaphore = original


# --- Board descriptor / adapter --------------------------------------------


def test_board_adapter_tags_offers_with_the_board_platform(mocker):
    """Happy path: ein Board-Descriptor liefert Angebote mit SEINEM
    `source_platform`, nicht dem generischen "web-scraper"."""
    mocker.patch.object(shared_module, "fetch_html", return_value=HEURISTIC_HTML)
    descriptor = shared_module.BoardDescriptor(
        source_platform="devjobs",
        build_search_url=lambda keywords, location: f"https://devjobs.de/jobs?q={keywords}",
    )

    offers = shared_module.BoardSourceAdapter(descriptor).search("Angular", "Berlin")

    assert len(offers) == 1
    assert offers[0].source_platform == "devjobs"
    assert offers[0].title == "Angular Developer"


def test_board_without_json_ld_falls_back_to_heuristic_extraction():
    """Edge: ohne eingebettetes JSON-LD greift die heuristische Extraktion."""
    offers = shared_module.extract_offers(
        HEURISTIC_HTML, "https://devjobs.de/jobs", "devjobs"
    )

    assert len(offers) == 1
    assert offers[0].title == "Angular Developer"
    assert offers[0].source_url == "https://devjobs.de/jobs/angular-developer-123"


def test_json_ld_takes_precedence_and_strips_html_description():
    offers = shared_module.extract_offers(
        JSON_LD_HTML, "https://devjobs.de/jobs", "devjobs"
    )

    assert len(offers) == 1
    assert offers[0].title == "Backend Engineer"
    assert offers[0].company == "Beta AG"
    assert offers[0].description_text == "Bewirb dich jetzt"


def test_json_ld_relative_url_is_resolved_against_the_page_url():
    html = """
    <html><body>
      <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Relative Role",
         "url": "/jobs/relative-1"}
      </script>
    </body></html>
    """

    offers = shared_module.extract_offers(html, "https://devjobs.de/jobs", "devjobs")

    assert len(offers) == 1
    assert offers[0].source_url == "https://devjobs.de/jobs/relative-1"


def test_json_ld_extraction_respects_max_results():
    items = ",".join(
        f'{{"@type": "JobPosting", "title": "Role {i}", "url": "https://devjobs.de/jobs/{i}"}}'
        for i in range(5)
    )
    html = f'<html><body><script type="application/ld+json">[{items}]</script></body></html>'

    offers = shared_module.extract_offers(
        html, "https://devjobs.de/jobs", "devjobs", max_results=2
    )

    assert len(offers) == 2
    assert [offer.title for offer in offers] == ["Role 0", "Role 1"]


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "http://192.168.1.5/jobs/1",
        "http://localhost:8000/jobs/1",
    ],
)
def test_json_ld_unsafe_url_is_dropped(unsafe_url):
    html = f"""
    <html><body>
      <script type="application/ld+json">
        {{"@type": "JobPosting", "title": "Unsafe Role", "url": "{unsafe_url}"}}
      </script>
    </body></html>
    """

    offers = shared_module.extract_offers(html, "https://devjobs.de/jobs", "devjobs")

    assert offers == []


# --- validate_source_url() --------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://example.com/jobs",
        "http://localhost:8000/jobs",
        "http://127.0.0.1/jobs",
        "http://192.168.0.10/jobs",
        "http://10.0.0.5/jobs",
        "http://169.254.0.1/jobs",
        "",
        None,
    ],
)
def test_validate_source_url_rejects_non_http_and_private_hosts(url):
    assert shared_module.validate_source_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://www.xing.com/stellenangebote/12345",
        "http://devjobs.de/jobs/42",
        "https://jobs.example.co.uk/role/1",
    ],
)
def test_validate_source_url_accepts_public_http_hosts(url):
    assert shared_module.validate_source_url(url) is True


# --- render_html() failure cleanup -----------------------------------------


def test_render_failure_closes_browser_and_returns_none(mocker):
    """Error: ein Render-Fehler schließt den Browser und liefert None,
    ohne einen Playwright-Prozess zu hinterlassen."""
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

    result = shared_module.render_html("https://example.com/jobs", timeout=0.01)

    assert result is None
    browser.close.assert_called_once()


# --- failure-log URL sanitization -------------------------------------------


def test_fetch_failure_log_strips_url_credentials_and_query(mocker, caplog):
    caplog.set_level(logging.WARNING)
    url = "https://user:secret@example.com/jobs?token=abc123"
    mocker.patch.object(
        shared_module.requests,
        "get",
        side_effect=shared_module.requests.RequestException(f"boom for {url}"),
    )

    result = shared_module.fetch_with_requests(url)

    assert result is None
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret" not in logs
    assert "abc123" not in logs
    assert "https://example.com/jobs" in logs


def test_render_failure_log_strips_url_credentials_and_query(mocker, caplog):
    caplog.set_level(logging.WARNING)
    url = "https://user:secret@example.com/jobs?token=abc123"

    @contextmanager
    def _raising_cm():
        raise RuntimeError(f"navigation failed for {url}")
        yield  # pragma: no cover - unreachable, satisfies generator shape

    mocker.patch.object(shared_module, "sync_playwright", _raising_cm)

    result = shared_module.render_html(url, timeout=0.01)

    assert result is None
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret" not in logs
    assert "abc123" not in logs
    assert "https://example.com/jobs" in logs


# --- semaphore serialization ------------------------------------------------


def test_concurrent_renders_serialize_on_the_shared_semaphore(mocker):
    """Integration: gleichzeitige Render-Aufrufe starten nie gleichzeitig
    einen Browser - das geteilte Semaphore serialisiert den Start."""
    shared_module.playwright_launch_semaphore = threading.Semaphore(1)

    concurrent_launches = 0
    max_concurrent_launches = 0
    lock = threading.Lock()
    fake_playwright = _fake_playwright(HEURISTIC_HTML)

    @contextmanager
    def _slow_cm():
        nonlocal concurrent_launches, max_concurrent_launches
        with lock:
            concurrent_launches += 1
            max_concurrent_launches = max(max_concurrent_launches, concurrent_launches)
        try:
            time.sleep(0.05)
            yield fake_playwright
        finally:
            with lock:
                concurrent_launches -= 1

    mocker.patch.object(shared_module, "sync_playwright", _slow_cm)

    threads = [
        threading.Thread(target=lambda: shared_module.render_html("https://example.com/jobs", timeout=1.0))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_concurrent_launches == 1


# --- salary/homeoffice prose helper ----------------------------------------


def test_salary_and_homeoffice_fold_into_description_text():
    """Salary/homeoffice werden als Prosa an `description_text` gehängt -
    ohne neues strukturiertes Feld."""
    folded = shared_module.fold_salary_homeoffice(
        "Bewirb dich bei uns.",
        salary="50.000 - 70.000 EUR",
        homeoffice="2 Tage/Woche",
    )

    assert "Bewirb dich bei uns." in folded
    assert "50.000 - 70.000 EUR" in folded
    assert "2 Tage/Woche" in folded
    assert "salary" not in JobOfferCreate.model_fields
    assert "homeoffice" not in JobOfferCreate.model_fields


def test_salary_helper_returns_none_when_nothing_to_fold():
    assert shared_module.fold_salary_homeoffice(None) is None


# --- HTML stripping ---------------------------------------------------------


def test_strip_html_removes_markup():
    assert shared_module.strip_html("<p>Bewerbung an <b>hr@example.de</b></p>") == (
        "Bewerbung an hr@example.de"
    )


def test_strip_html_returns_none_for_empty_input():
    assert shared_module.strip_html(None) is None
    assert shared_module.strip_html("") is None


# --- credential redaction ---------------------------------------------------


def test_redact_credentials_hides_api_keys_in_urls_and_bearer_tokens():
    redacted = shared_module.redact_credentials(
        "GET https://api.adzuna.com/v1/api/jobs/de/search/1"
        "?app_id=abc123&app_key=supersecret&what=python "
        "Authorization: Bearer tok_12345"
    )

    assert "supersecret" not in redacted
    assert "abc123" not in redacted
    assert "tok_12345" not in redacted
    assert "app_key=***" in redacted
    assert "Bearer ***" in redacted
