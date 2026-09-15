"""Tests für `ArbeitnowJobsClient` (siehe backend/app/services/job_sources/arbeitnow.py).

Deckt die Testszenarien aus U2 des Plans ab:
docs/plans/2026-09-15-001-feat-job-search-source-consolidation-plan.md
"""
from __future__ import annotations

import pytest
import requests

from app.core.config import settings
from app.schemas.job_offer import JobOfferCreate
from app.services.job_search_service import JobSearchService, SourceRegistration
from app.services.job_sources.arbeitnow import ArbeitnowJobsClient


def _job(**overrides):
    base = {
        "slug": "angular-developer-1",
        "company_name": "Acme GmbH",
        "title": "Angular Developer",
        "description": "<p>Wir suchen einen Angular-Entwickler.</p>",
        "remote": False,
        "url": "https://www.arbeitnow.com/view/angular-developer-1",
        "tags": ["angular", "frontend"],
        "job_types": ["Full time"],
        "location": "Berlin",
        "created_at": 1757894400,
    }
    base.update(overrides)
    return base


def _payload(*jobs):
    return {
        "data": list(jobs),
        "links": {
            "first": ArbeitnowJobsClient.BASE_URL + "?page=1",
            "last": None,
            "prev": None,
            "next": None,
        },
        "meta": {"current_page": 1, "per_page": 250},
    }


def _reset_cooldown() -> None:
    ArbeitnowJobsClient._cooldown_until = 0.0  # noqa: SLF001 - bewusster Test-Reset


def setup_function() -> None:
    _reset_cooldown()


def teardown_function() -> None:
    _reset_cooldown()


# --- Happy path -------------------------------------------------------------


def test_happy_path_maps_matching_results_with_arbeitnow_platform(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(
            _job(),
            _job(
                slug="backend-engineer-2",
                title="Backend Engineer",
                description="<p>Wir suchen eine Backend-Entwicklerin.</p>",
            ),
        ),
    )

    offers = ArbeitnowJobsClient().search("Angular", "Berlin")

    assert len(offers) == 1
    assert offers[0].source_platform == "arbeitnow"
    assert offers[0].title == "Angular Developer"
    assert offers[0].company == "Acme GmbH"
    assert offers[0].location == "Berlin"
    assert offers[0].source_url == "https://www.arbeitnow.com/view/angular-developer-1"


def test_description_html_is_stripped(requests_mock):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, json=_payload(_job()))

    offers = ArbeitnowJobsClient().search("Angular")

    assert offers[0].description_text == "Wir suchen einen Angular-Entwickler."


def test_no_query_params_are_sent(requests_mock):
    """KTD3: die API kennt kein `keywords`/`location` - der Client fragt nur
    die unparametrisierte erste Seite ab und filtert client-seitig."""
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, json=_payload(_job()))

    ArbeitnowJobsClient().search("Angular", "Berlin")

    assert requests_mock.last_request.qs == {}


# --- Client-side filtering (KTD3) -------------------------------------------


def test_keyword_filter_requires_every_term_to_match(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(
            _job(title="Angular Developer"),
            _job(
                slug="ruby-2",
                title="Ruby Developer",
                company_name="Beta AG",
                description="<p>Wir suchen einen Ruby-Entwickler.</p>",
            ),
        ),
    )

    offers = ArbeitnowJobsClient().search("Angular Developer")

    assert [offer.title for offer in offers] == ["Angular Developer"]


def test_keyword_matches_against_description_and_company_too(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(_job(title="Software Engineer", company_name="Angular Consulting GmbH")),
    )

    offers = ArbeitnowJobsClient().search("Angular")

    assert len(offers) == 1


def test_location_filter_is_a_case_insensitive_substring_match(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(
            _job(slug="berlin-1", location="Berlin"),
            _job(slug="munich-1", title="Backend Engineer", location="Munich"),
        ),
    )

    offers = ArbeitnowJobsClient().search("", "berlin")

    assert [offer.location for offer in offers] == ["Berlin"]


def test_no_keywords_or_location_returns_all_results_up_to_the_cap(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(*[_job(slug=f"job-{i}", title=f"Job {i}") for i in range(3)]),
    )

    offers = ArbeitnowJobsClient().search("")

    assert len(offers) == 3


# --- Edge: malformed / unsafe records ---------------------------------------


def test_malformed_record_is_skipped_and_others_survive(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(
            _job(title=None),  # fehlender Titel -> übersprungen
            _job(slug="backend-2", title="Backend Engineer"),
        ),
    )

    offers = ArbeitnowJobsClient().search("")

    assert [offer.title for offer in offers] == ["Backend Engineer"]


def test_empty_tags_and_job_types_do_not_raise(requests_mock):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(_job(tags=[], job_types=[])),
    )

    offers = ArbeitnowJobsClient().search("")

    assert len(offers) == 1


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://192.168.1.5/view/1",  # privater Host
        "http://localhost:8000/view/1",  # Loopback
        "javascript:alert(1)",  # Nicht-http(s)
        "ftp://example.com/view/1",  # Nicht-http(s)
    ],
)
def test_unsafe_url_is_rejected(requests_mock, unsafe_url):
    requests_mock.get(
        ArbeitnowJobsClient.BASE_URL,
        json=_payload(_job(url=unsafe_url), _job(slug="survivor", title="Survivor")),
    )

    offers = ArbeitnowJobsClient().search("")

    assert [offer.title for offer in offers] == ["Survivor"]


def test_invalid_json_raises_a_runtime_error(requests_mock):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, text="<html>not json</html>")

    with pytest.raises(RuntimeError):
        ArbeitnowJobsClient().search("")


@pytest.mark.parametrize("status_code", [400, 404, 500, 502, 503])
def test_http_error_raises_a_runtime_error(requests_mock, status_code):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, status_code=status_code)

    with pytest.raises(RuntimeError):
        ArbeitnowJobsClient().search("")


def test_request_exception_raises_a_runtime_error(requests_mock):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, exc=requests.ConnectionError("boom"))

    with pytest.raises(RuntimeError):
        ArbeitnowJobsClient().search("")


def test_http_error_maps_to_error_reason_in_the_orchestrator(requests_mock):
    """Ein 5xx wird vom Orchestrator als `reason="error"` (nicht `empty`)
    gekennzeichnet, weil `search()` jetzt eine Exception wirft."""
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, status_code=500)

    service = JobSearchService(
        sources=[SourceRegistration(ArbeitnowJobsClient())],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    status = next(s for s in response.sources if s.platform == "arbeitnow")
    assert status.status == "unavailable"
    assert status.reason == "error"


# --- Rate limiting (KTD4) ----------------------------------------------------


def test_429_returns_empty_list_and_records_cooldown(requests_mock):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, status_code=429)

    offers = ArbeitnowJobsClient().search("")

    assert offers == []
    assert ArbeitnowJobsClient.is_cooldown_active() is True


def test_cooldown_skips_request_on_next_search(requests_mock):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, status_code=429)
    ArbeitnowJobsClient().search("")
    assert requests_mock.call_count == 1

    offers = ArbeitnowJobsClient().search("")

    assert offers == []
    assert requests_mock.call_count == 1


# --- No structured salary/homeoffice field (matches JobOfferCreate) --------


def test_no_new_structured_fields_are_introduced(requests_mock):
    requests_mock.get(ArbeitnowJobsClient.BASE_URL, json=_payload(_job()))

    ArbeitnowJobsClient().search("")

    assert "tags" not in JobOfferCreate.model_fields
    assert "job_types" not in JobOfferCreate.model_fields
    assert "remote" not in JobOfferCreate.model_fields


# --- Wiring into the settings-derived registry (KTD2: unconditional) -------


def test_registry_registers_arbeitnow_unconditionally():
    """KTD2: Arbeitnow braucht weder Enable-Flag noch Zugangsdaten und ist
    immer registriert, wie `arbeitsagentur`."""
    service = JobSearchService(deadline_seconds=1.0)

    registration = next(reg for reg in service._sources if reg.platform == "arbeitnow")  # noqa: SLF001
    assert getattr(registration.client, "is_configured", None) is None


def test_arbeitnow_registration_is_unaffected_by_other_source_flags(monkeypatch):
    monkeypatch.setattr(settings, "JOB_SEARCH_DEVJOBS_ENABLED", False)
    monkeypatch.setattr(settings, "JOB_SEARCH_LINKEDIN_ENABLED", False)

    service = JobSearchService(deadline_seconds=1.0)

    platforms = [reg.platform for reg in service._sources]  # noqa: SLF001
    assert "arbeitnow" in platforms
