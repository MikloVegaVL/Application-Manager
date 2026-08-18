"""Tests für `JobSearchService`s Multi-Source-Fan-out (siehe U4 des Plans:
docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).
"""
from __future__ import annotations

import time

from app.schemas.job_offer import JobOfferCreate
from app.services.job_search_service import JobSearchService


class _FakeClient:
    """Test-Double mit derselben `.search(keywords, location=None)`-Signatur
    wie die echten Source-Clients."""

    SOURCE_PLATFORM = "fake"

    def __init__(self, offers=None, exc: Exception | None = None, delay: float = 0.0):
        self._offers = offers or []
        self._exc = exc
        self._delay = delay
        self.calls: list[tuple] = []

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
    aa_client = _FakeClient(offers=aa_offers, exc=aa_exc)
    li_client = _FakeClient(offers=li_offers, exc=li_exc, delay=li_delay)
    xi_client = _FakeClient(offers=xi_offers, exc=xi_exc, delay=xi_delay)
    fallback = _NoOpFallback(offers=fallback_offers)

    return (
        JobSearchService(
            arbeitsagentur_client=aa_client,
            fallback_scraper=fallback,
            linkedin_client=li_client,
            xing_client=xi_client,
            deadline_seconds=deadline_seconds,
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


def test_fallback_does_not_trigger_when_arbeitsagentur_has_results():
    service, *_client, fallback = _service(
        aa_offers=[_offer("arbeitsagentur")],
    )

    service.search("Angular", fallback_url="https://example.com/jobs")

    assert fallback.calls == []


def test_default_xing_client_inner_timeout_never_exceeds_the_search_deadline():
    """Per KTD6, Xing's inner Playwright timeout must be derived from (and
    never exceed) the outer search deadline - otherwise a Xing render can
    still be running well after the response already returned."""
    service = JobSearchService(deadline_seconds=12.0)

    assert service._xing_client._inner_timeout < 12.0  # noqa: SLF001 - white-box wiring check
    assert service._xing_client._inner_timeout >= 1.0  # noqa: SLF001
