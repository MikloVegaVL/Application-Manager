"""Tests für `JobSearchService`s Multi-Source-Fan-out (siehe U4 des Plans:
docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).
"""
from __future__ import annotations

import time

import pytest
from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate, SourceStatus
from app.services.job_search_service import (
    ArbeitsagenturJobsClient,
    GenericJobScraper,
    JobSearchService,
    SourceRegistration,
)
from app.services.job_sources.shared import SourceNotConfiguredError


class _FakeClient:
    """Test-Double mit derselben `.search(keywords, location=None)`-Signatur
    wie die echten Source-Clients."""

    SOURCE_PLATFORM = "fake"

    def __init__(
        self,
        offers=None,
        exc: Exception | None = None,
        delay: float = 0.0,
        platform: str = "fake",
        configured: bool = True,
        cooldown_active: bool = False,
    ):
        self.SOURCE_PLATFORM = platform
        self._offers = offers or []
        self._exc = exc
        self._delay = delay
        self._configured = configured
        self._cooldown_active = cooldown_active
        self.calls: list[tuple] = []
        self.is_configured_calls = 0

    def is_configured(self) -> bool:
        self.is_configured_calls += 1
        return self._configured

    def is_cooldown_active(self) -> bool:
        return self._cooldown_active

    def search(self, keywords, location=None):
        self.calls.append((keywords, location))
        if self._delay:
            time.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return self._offers


def _offer(platform: str, title: str = "Some Job") -> JobOfferCreate:
    return JobOfferCreate(
        title=title,
        company="Acme",
        location=None,
        source_url=f"https://example.com/{platform}/{title}",
        description_text=None,
        source_platform=platform,
    )


class _NoOpFallback:
    """Fallback-Scraper-Double - zählt Aufrufe, ohne echtes HTTP zu machen."""

    def __init__(self, offers=None):
        self._offers = offers or []
        self.calls: list[dict] = []

    def search(self, url, keywords=None, location=None):
        self.calls.append({"url": url, "keywords": keywords, "location": location})
        return self._offers


def _service(
    aa_offers=None,
    aa_exc=None,
    li_offers=None,
    li_exc=None,
    li_delay=0.0,
    xi_offers=None,
    xi_exc=None,
    xi_delay=0.0,
    fallback_offers=None,
    deadline_seconds=5.0,
):
    aa_client = _FakeClient(offers=aa_offers, exc=aa_exc, platform="arbeitsagentur")
    li_client = _FakeClient(offers=li_offers, exc=li_exc, delay=li_delay, platform="linkedin")
    xi_client = _FakeClient(offers=xi_offers, exc=xi_exc, delay=xi_delay, platform="xing")
    fallback = _NoOpFallback(offers=fallback_offers)

    sources = [
        SourceRegistration(aa_client),
        SourceRegistration(li_client),
        SourceRegistration(xi_client),
    ]

    return (
        JobSearchService(
            fallback_scraper=fallback,
            deadline_seconds=deadline_seconds,
            sources=sources,
        ),
        aa_client,
        li_client,
        xi_client,
        fallback,
    )


def test_happy_path_combines_results_and_marks_all_sources_ok():
    service, *_ = _service(
        aa_offers=[_offer("arbeitsagentur")],
        li_offers=[_offer("linkedin")],
        xi_offers=[_offer("xing")],
    )

    response = service.search("Angular", "Berlin")

    assert len(response.results) == 3
    assert {s.status for s in response.sources} == {"ok"}
    assert {s.platform for s in response.sources} == {"arbeitsagentur", "linkedin", "xing"}


def test_timeout_marks_source_unavailable_and_returns_promptly():
    """Covers AE1: der LinkedIn-Client überschreitet die Deadline, die
    Antwort kommt trotzdem zeitnah mit den anderen beiden Quellen zurück."""
    service, *_ = _service(
        aa_offers=[_offer("arbeitsagentur")],
        xi_offers=[_offer("xing")],
        li_delay=2.0,  # deutlich länger als die konfigurierte Deadline
        deadline_seconds=0.2,
    )

    started = time.monotonic()
    response = service.search("Angular", "Berlin")
    elapsed = time.monotonic() - started

    linkedin_status = next(s for s in response.sources if s.platform == "linkedin")
    assert linkedin_status.status == "unavailable"
    assert linkedin_status.reason == "timeout"
    # Antwort kam nahe an der Deadline zurück, nicht erst nach den vollen 2s
    # Verzögerung - beweist, dass der Executor-Teardown nicht blockiert (KTD1).
    assert elapsed < 1.0

    platforms_with_results = {offer.source_platform for offer in response.results}
    assert platforms_with_results == {"arbeitsagentur", "xing"}


def test_error_isolation_one_client_failing_does_not_affect_others():
    service, *_ = _service(
        aa_offers=[_offer("arbeitsagentur")],
        li_exc=RuntimeError("simulated unexpected failure"),
        xi_offers=[_offer("xing")],
    )

    response = service.search("Angular")

    linkedin_status = next(s for s in response.sources if s.platform == "linkedin")
    assert linkedin_status.status == "unavailable"
    assert linkedin_status.reason == "error"

    aa_status = next(s for s in response.sources if s.platform == "arbeitsagentur")
    xi_status = next(s for s in response.sources if s.platform == "xing")
    assert aa_status.status == "ok"
    assert xi_status.status == "ok"


def test_anonymous_only_no_credential_or_session_passed_to_any_client():
    """Covers AE3: keiner der Such-Aufrufe erhält ein Credential-/Session-Argument."""
    service, aa_client, li_client, xi_client, _ = _service(
        aa_offers=[_offer("arbeitsagentur")],
        li_offers=[_offer("linkedin")],
        xi_offers=[_offer("xing")],
    )

    service.search("Angular", "Berlin")

    for client in (aa_client, li_client, xi_client):
        for call_args in client.calls:
            assert "credential" not in repr(call_args).lower()
            assert "session" not in repr(call_args).lower()
            assert "cookie" not in repr(call_args).lower()
        # Nur keywords/location wurden übergeben - keine weiteren Argumente.
        assert client.calls[0] == ("Angular", "Berlin")


def test_fallback_only_triggers_when_arbeitsagentur_empty_and_fallback_url_given():
    service, *_client, fallback = _service(
        aa_offers=[],
        li_offers=[_offer("linkedin")],
        xi_offers=[_offer("xing")],
        fallback_offers=[_offer("web-scraper")],
    )

    response = service.search("Angular", fallback_url="https://example.com/jobs")

    assert len(fallback.calls) == 1
    assert any(offer.source_platform == "web-scraper" for offer in response.results)
    # Der Fallback-Pfad braucht einen eigenen Status-Eintrag - sonst verletzt
    # die Antwort ihre eigene Zusicherung, dass `sources` jede zu `results`
    # beitragende Quelle abdeckt.
    fallback_status = next(s for s in response.sources if s.platform == "web-scraper")
    assert fallback_status.status == "ok"


def test_fallback_with_no_results_still_gets_a_source_status():
    service, *_client, fallback = _service(aa_offers=[], fallback_offers=[])

    response = service.search("Angular", fallback_url="https://example.com/jobs")

    fallback_status = next(s for s in response.sources if s.platform == "web-scraper")
    assert fallback_status.status == "unavailable"
    assert fallback_status.reason == "empty"


def test_fallback_does_not_trigger_without_fallback_url():
    service, *_client, fallback = _service(aa_offers=[])

    service.search("Angular")

    assert fallback.calls == []


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://127.0.0.1/jobs",  # Loopback
        "http://localhost:8000/jobs",  # Loopback
        "http://192.168.1.5/jobs",  # privater Host
        "http://10.0.0.7/jobs",  # privater Host
        "http://169.254.169.254/latest/meta-data/",  # Cloud-Metadata (link-local)
        "javascript:alert(1)",  # Nicht-http(s)
        "ftp://example.com/jobs",  # Nicht-http(s)
    ],
)
def test_unsafe_fallback_url_is_rejected_before_the_scraper_fetches(unsafe_url):
    """R3/KTD10: eine unsichere `fallback_url` darf nie serverseitig
    abgerufen werden."""
    service, *_client, fallback = _service(aa_offers=[])

    response = service.search("Angular", fallback_url=unsafe_url)

    assert fallback.calls == []
    fallback_status = next(s for s in response.sources if s.platform == "web-scraper")
    assert fallback_status.status == "unavailable"
    assert fallback_status.reason == "error"


def test_fallback_does_not_trigger_when_arbeitsagentur_has_results():
    service, *_client, fallback = _service(
        aa_offers=[_offer("arbeitsagentur")],
    )

    service.search("Angular", fallback_url="https://example.com/jobs")

    assert fallback.calls == []


# --- U2: injectable source registry ----------------------------------------
#
# Siehe docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md
# (U2, KTD3/KTD9/KTD11). Tests injizieren die Registry statt den gecachten
# `settings`-Singleton zu verändern.


def test_registry_skips_disabled_source_and_never_calls_it():
    """Edge: `enabled=False` nimmt eine Quelle aus Registry und Antwort, ohne
    dass `search()` aufgerufen wird."""
    disabled = _FakeClient(offers=[_offer("disabled")], platform="disabled")
    enabled = _FakeClient(offers=[_offer("enabled")], platform="enabled")
    service = JobSearchService(
        sources=[SourceRegistration(disabled, enabled=False), SourceRegistration(enabled)],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    assert disabled.calls == []
    assert {s.platform for s in response.sources} == {"enabled"}
    assert {offer.source_platform for offer in response.results} == {"enabled"}


def test_unconfigured_source_yields_not_configured_without_a_search_call():
    """KTD9: `is_configured()` wird vor dem Submit befragt; bei `False` wird
    die Quelle übersprungen und als `not-configured` markiert."""
    unconfigured = _FakeClient(offers=[_offer("adzuna")], platform="adzuna", configured=False)
    configured = _FakeClient(offers=[_offer("arbeitsagentur")], platform="arbeitsagentur")
    service = JobSearchService(
        sources=[SourceRegistration(unconfigured), SourceRegistration(configured)],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    assert unconfigured.calls == []
    assert unconfigured.is_configured_calls == 1
    status = next(s for s in response.sources if s.platform == "adzuna")
    assert status.status == "unavailable"
    assert status.reason == "not-configured"


def test_source_not_configured_error_maps_to_not_configured_reason():
    """KTD9: eine mitten im Request abgelehnte Zugangsberechtigung
    (`SourceNotConfiguredError`) wird auf denselben Reason gemappt."""
    raising = _FakeClient(exc=SourceNotConfiguredError("credential rejected"), platform="jooble")
    service = JobSearchService(
        sources=[SourceRegistration(raising)],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    assert raising.calls == [("Angular", None)]
    status = next(s for s in response.sources if s.platform == "jooble")
    assert status.status == "unavailable"
    assert status.reason == "not-configured"


def test_registry_error_isolation_one_source_raising_does_not_affect_others():
    """Error: eine werfende Quelle bekommt `reason=error`, die übrigen
    liefern weiterhin Treffer."""
    failing = _FakeClient(exc=RuntimeError("simulated unexpected failure"), platform="linkedin")
    healthy = _FakeClient(offers=[_offer("arbeitsagentur")], platform="arbeitsagentur")
    service = JobSearchService(
        sources=[SourceRegistration(failing), SourceRegistration(healthy)],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    assert next(s for s in response.sources if s.platform == "linkedin").reason == "error"
    assert next(s for s in response.sources if s.platform == "arbeitsagentur").status == "ok"
    assert {offer.source_platform for offer in response.results} == {"arbeitsagentur"}


def test_two_registrations_with_the_same_platform_both_get_a_status():
    """Zwei Registrierungen mit identischem Plattform-Schlüssel dürfen sich
    nicht gegenseitig aus dem Futures-Mapping verdrängen - beide müssen einen
    Status und ihre Treffer beitragen."""
    first = _FakeClient(offers=[_offer("dup", "First")], platform="dup")
    second = _FakeClient(offers=[_offer("dup", "Second")], platform="dup")
    service = JobSearchService(
        sources=[SourceRegistration(first), SourceRegistration(second)],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    dup_statuses = [s for s in response.sources if s.platform == "dup"]
    assert len(dup_statuses) == 2
    assert {s.status for s in dup_statuses} == {"ok"}
    assert {offer.title for offer in response.results} == {"First", "Second"}


def test_registry_deadline_timeout_marks_source_and_returns_promptly():
    """Timeout: eine langsame Quelle wird `reason=timeout`, die Antwort kommt
    trotzdem zeitnah zurück (KTD8)."""
    slow = _FakeClient(offers=[_offer("slow")], platform="slow", delay=2.0)
    healthy = _FakeClient(offers=[_offer("arbeitsagentur")], platform="arbeitsagentur")
    service = JobSearchService(
        sources=[SourceRegistration(slow), SourceRegistration(healthy)],
        deadline_seconds=0.2,
    )

    started = time.monotonic()
    response = service.search("Angular")
    elapsed = time.monotonic() - started

    assert next(s for s in response.sources if s.platform == "slow").reason == "timeout"
    assert elapsed < 1.0


def test_empty_source_with_active_cooldown_is_labeled_rate_limited():
    """Die frühere LinkedIn-Sonderbehandlung ist jetzt generisch: jede Quelle
    mit `is_cooldown_active()` und leerem Ergebnis wird `rate-limited`."""
    limited = _FakeClient(offers=[], platform="linkedin", cooldown_active=True)
    service = JobSearchService(
        sources=[SourceRegistration(limited)],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    status = next(s for s in response.sources if s.platform == "linkedin")
    assert status.status == "unavailable"
    assert status.reason == "rate-limited"


def test_default_registry_is_built_from_settings_without_injection():
    """KTD11: ohne Injektion baut der Service die settings-abgeleitete
    Registry (Primärquellen plus die per Flag aktivierten API-Quellen)."""
    service = JobSearchService(deadline_seconds=1.0)

    platforms = [reg.platform for reg in service._sources]  # noqa: SLF001 - white-box wiring check
    assert platforms[0] == "arbeitsagentur"
    assert set(platforms) <= {
        "arbeitsagentur",
        "linkedin",
        "xing",
        "adzuna",
        "jooble",
        "devjobs",
        "kimeta",
        "stepstone",
        "germantechjobs",
        "indeed",
        "jobware",
        "programmiererjobboerse",
        "it-entwickler-jobs",
    }
    assert "adzuna" in platforms
    assert "jooble" in platforms
    # U6: alle acht HTML-Boards sind standardmäßig registriert und tragen je
    # einen eigenen Plattform-Schlüssel - keiner ist "web-scraper" (R4/R6).
    for board in (
        "devjobs",
        "kimeta",
        "stepstone",
        "germantechjobs",
        "indeed",
        "jobware",
        "programmiererjobboerse",
        "it-entwickler-jobs",
    ):
        assert board in platforms
    assert "web-scraper" not in platforms
    assert all(reg.enabled for reg in service._sources)  # noqa: SLF001


def test_default_xing_client_inner_timeout_never_exceeds_the_search_deadline():
    """Per KTD6, Xing's inner Playwright timeout must be derived from (and
    never exceed) the outer search deadline - otherwise a Xing render can
    still be running well after the response already returned."""
    service = JobSearchService(deadline_seconds=12.0)

    assert service._xing_client._inner_timeout < 12.0  # noqa: SLF001 - white-box wiring check
    assert service._xing_client._inner_timeout >= 1.0  # noqa: SLF001


@pytest.mark.parametrize("deadline_seconds", [1.0, 0.5, 0.2])
def test_inner_timeout_is_strictly_below_the_outer_deadline_for_small_deadlines(
    deadline_seconds,
):
    """KTD8: auch bei einer sehr kleinen Deadline bleibt der innere Timeout
    strikt unter der äußeren - die frühere `max(1.0, deadline - 1.0)`-Formel
    konnte bei `deadline <= 1.0` genau der Deadline entsprechen (oder sie
    überschreiten)."""
    service = JobSearchService(deadline_seconds=deadline_seconds)

    assert service._xing_client._inner_timeout < deadline_seconds  # noqa: SLF001


# --- GenericJobScraper: heuristische Extraktion (kein JSON-LD) --------------
#
# Bislang ungetestet (siehe residual-review-findings/5498abb.md). Dieselbe
# Karten-Struktur wie bei Xing: ein ganzkartiges, textloses Overlay-<a>
# (Klick-Link) steht im DOM VOR der sichtbaren <h2>-Überschrift - ein
# verbreitetes barrierefreies Karten-Muster, nicht Xing-spezifisch.
_OVERLAY_LINK_BEFORE_HEADING_HTML = """
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


def test_heuristic_extraction_prefers_heading_over_a_leading_empty_overlay_link():
    """A card whose first descendant is a text-less full-card overlay <a>
    (common accessible-card markup) must still yield the real <h2> title,
    not the empty anchor text - `find()` over a tag list matches document
    order, not list priority, so the heading has to be searched first."""
    soup = BeautifulSoup(_OVERLAY_LINK_BEFORE_HEADING_HTML, "html.parser")

    offers = GenericJobScraper()._extract_heuristic_offers(soup, source_url="https://example.com/jobs")

    assert len(offers) == 1
    assert offers[0].title == "Angular Developer"
    assert offers[0].source_url == "https://example.com/jobs/angular-developer-123"


# --- ArbeitsagenturJobsClient.fetch_description() (lazy detail-page load) --
#
# Covers the ce-debug follow-up (2026-08-20): search results themselves are
# never persisted (KTD2), so a description can only be fetched once a
# JobOffer is actually saved and reopened (see `GET /jobs/{id}` /
# `JobSearchService.enrich_description`), never eagerly for every one of up
# to 25 search hits (that would blow the shared search deadline, KTD1).

_ENCODED_REFNR = "MTAwMDEtMTAwMjcxNjkyMi1T"  # base64("10001-1002716922-S")


def test_fetch_description_happy_path_decodes_and_strips_html(requests_mock):
    detail_url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1002716922-S"
    requests_mock.get(
        f"{ArbeitsagenturJobsClient.DETAIL_BASE_URL}/{_ENCODED_REFNR}",
        json={"stellenangebotsBeschreibung": "<p>Bewerbung an <b>hr@example.de</b></p>"},
    )

    description = ArbeitsagenturJobsClient().fetch_description(detail_url)

    assert description == "Bewerbung an hr@example.de"


def test_fetch_description_falls_back_to_the_legacy_field_name(requests_mock):
    detail_url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1002716922-S"
    requests_mock.get(
        f"{ArbeitsagenturJobsClient.DETAIL_BASE_URL}/{_ENCODED_REFNR}",
        json={"stellenbeschreibung": "Nur der alte Feldname ist gesetzt."},
    )

    description = ArbeitsagenturJobsClient().fetch_description(detail_url)

    assert description == "Nur der alte Feldname ist gesetzt."


def test_fetch_description_returns_none_for_an_external_career_page_url():
    """`source_url` zeigt auf die Karriereseite eines Drittanbieters
    (`externeURL`, siehe `_map_offer`) - ohne Referenznummer lässt sich kein
    Detail-Call bauen."""
    description = ArbeitsagenturJobsClient().fetch_description("https://acme-careers.example/jobs/42")

    assert description is None


def test_fetch_description_returns_none_on_http_error(requests_mock):
    detail_url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1002716922-S"
    requests_mock.get(f"{ArbeitsagenturJobsClient.DETAIL_BASE_URL}/{_ENCODED_REFNR}", status_code=404)

    description = ArbeitsagenturJobsClient().fetch_description(detail_url)

    assert description is None


def test_fetch_description_returns_none_when_the_field_is_missing_or_empty(requests_mock):
    detail_url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1002716922-S"
    requests_mock.get(f"{ArbeitsagenturJobsClient.DETAIL_BASE_URL}/{_ENCODED_REFNR}", json={})

    description = ArbeitsagenturJobsClient().fetch_description(detail_url)

    assert description is None


# --- JobSearchService.enrich_description() (source dispatch) --------------


def test_enrich_description_dispatches_to_the_arbeitsagentur_client(mocker):
    service = JobSearchService()
    mocker.patch.object(service._arbeitsagentur_client, "fetch_description", return_value="Text")  # noqa: SLF001

    result = service.enrich_description("arbeitsagentur", "https://example.com/job/1")

    assert result == "Text"
    service._arbeitsagentur_client.fetch_description.assert_called_once_with(  # noqa: SLF001
        "https://example.com/job/1"
    )


def test_enrich_description_dispatches_to_the_xing_client(mocker):
    service = JobSearchService()
    mocker.patch.object(service._xing_client, "fetch_description", return_value="Text")  # noqa: SLF001

    result = service.enrich_description("xing", "https://xing.com/jobs/1")

    assert result == "Text"


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://127.0.0.1/job/1",
        "http://localhost:8000/job/1",
        "http://192.168.1.5/job/1",
        "http://169.254.169.254/latest/meta-data/",
        "javascript:alert(1)",
    ],
)
def test_enrich_description_rejects_unsafe_source_url_without_calling_client(
    mocker, unsafe_url
):
    """R3/KTD10: eine unsicher gespeicherte `source_url` darf keinen
    serverseitigen Render/Detail-Abruf auslösen."""
    service = JobSearchService()
    xing_spy = mocker.patch.object(service._xing_client, "fetch_description", return_value="Text")  # noqa: SLF001
    aa_spy = mocker.patch.object(service._arbeitsagentur_client, "fetch_description", return_value="Text")  # noqa: SLF001

    assert service.enrich_description("xing", unsafe_url) is None
    assert service.enrich_description("arbeitsagentur", unsafe_url) is None
    xing_spy.assert_not_called()
    aa_spy.assert_not_called()


def test_enrich_description_is_a_no_op_for_unsupported_sources():
    """LinkedIn und der generische Fallback-Scraper haben keinen
    Detail-Call (LinkedIn) bzw. füllen `description_text` bereits beim
    Scrapen (Fallback) - beide liefern hier `None` statt einer Exception."""
    service = JobSearchService()

    assert service.enrich_description("linkedin", "https://linkedin.com/jobs/1") is None
    assert service.enrich_description("web-scraper", "https://example.com/jobs/1") is None


# --- U3: per-source enable flags, credential settings, not-configured -------
#
# Siehe docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md
# (U3, KTD5/KTD7/KTD9).

_NEW_SOURCE_FLAGS = (
    "JOB_SEARCH_DEVJOBS_ENABLED",
    "JOB_SEARCH_KIMETA_ENABLED",
    "JOB_SEARCH_STEPSTONE_ENABLED",
    "JOB_SEARCH_GERMANTECHJOBS_ENABLED",
    "JOB_SEARCH_INDEED_ENABLED",
    "JOB_SEARCH_JOBWARE_ENABLED",
    "JOB_SEARCH_PROGRAMMIERERJOBBOERSE_ENABLED",
    "JOB_SEARCH_IT_ENTWICKLER_JOBS_ENABLED",
    "JOB_SEARCH_ADZUNA_ENABLED",
    "JOB_SEARCH_JOOBLE_ENABLED",
)


def test_new_source_enable_flags_resolve_and_default_to_true(monkeypatch):
    """U3 happy path: jede neue Quelle hat ein eigenes Enable-Flag, das aus
    der Umgebung aufgelöst wird und standardmäßig aktiv ist (KTD7)."""
    from app.core.config import Settings

    for flag in _NEW_SOURCE_FLAGS:
        monkeypatch.delenv(flag, raising=False)

    fresh = Settings(_env_file=None)

    for flag in _NEW_SOURCE_FLAGS:
        assert getattr(fresh, flag) is True


def test_api_credentials_default_to_empty_strings(monkeypatch):
    """U3 edge: ungesetzte Zugangsdaten lösen zu einem leeren String auf -
    die Grundlage dafür, dass Adzuna/Jooble `not-configured` melden, ohne
    die Suche fehlschlagen zu lassen (R9/KD7)."""
    from app.core.config import Settings

    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    fresh = Settings(_env_file=None)

    assert fresh.ADZUNA_APP_ID == ""
    assert fresh.ADZUNA_APP_KEY == ""
    assert fresh.JOOBLE_API_KEY == ""


def test_source_status_accepts_not_configured_reason():
    """U3: das Backend-Schema erlaubt den neuen, eigenständigen Reason, damit
    die API-Clients aus U4/U5 ihn emittieren können (KTD5)."""
    status = SourceStatus(platform="adzuna", status="unavailable", reason="not-configured")

    assert status.reason == "not-configured"

