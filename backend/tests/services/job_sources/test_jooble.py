"""Tests für `JoobleJobsClient` (siehe backend/app/services/job_sources/jooble.py).

Deckt die Testszenarien aus U5 des Plans ab:
docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md
"""
from __future__ import annotations

import logging

import pytest
import requests

from app.core.config import settings
from app.schemas.job_offer import JobOfferCreate
from app.services.job_search_service import JobSearchService, SourceRegistration
from app.services.job_sources.jooble import JoobleJobsClient
from app.services.job_sources.shared import SourceNotConfiguredError

API_KEY = "test-jooble-key"
URL = JoobleJobsClient.BASE_URL_TEMPLATE.format(api_key=API_KEY)


def _job(**overrides):
    base = {
        "id": "1",
        "title": "Angular Developer",
        "company": "Acme GmbH",
        "location": "Berlin",
        "link": "https://de.jooble.org/desc/1",
        "snippet": "<b>Wir</b> suchen einen Angular-Entwickler.",
        "salary": None,
    }
    base.update(overrides)
    return base


def _client(**kwargs) -> JoobleJobsClient:
    kwargs.setdefault("api_key", API_KEY)
    return JoobleJobsClient(**kwargs)


def _reset_cooldown() -> None:
    JoobleJobsClient._cooldown_until = 0.0  # noqa: SLF001 - bewusster Test-Reset


def setup_function() -> None:
    _reset_cooldown()


def teardown_function() -> None:
    _reset_cooldown()


# --- Happy path -------------------------------------------------------------


def test_happy_path_maps_all_jobs_with_jooble_platform(requests_mock):
    payload = {
        "totalCount": 2,
        "jobs": [_job(), _job(id="2", title="Backend Engineer", link="https://de.jooble.org/desc/2")],
    }
    requests_mock.post(URL, json=payload)

    offers = _client().search("Angular", "Berlin")

    assert len(offers) == 2
    assert all(offer.source_platform == "jooble" for offer in offers)
    assert offers[0].title == "Angular Developer"
    assert offers[0].company == "Acme GmbH"
    assert offers[0].location == "Berlin"
    assert offers[0].source_url == "https://de.jooble.org/desc/1"


def test_request_posts_keywords_and_location_to_key_path(requests_mock):
    requests_mock.post(URL, json={"totalCount": 0, "jobs": []})

    _client().search("Angular", "Berlin")

    request = requests_mock.last_request
    assert request.method == "POST"
    assert request.path == f"/api/{API_KEY}"
    assert request.json() == {"keywords": "Angular", "location": "Berlin"}


def test_missing_location_defaults_to_germany(requests_mock):
    requests_mock.post(URL, json={"totalCount": 0, "jobs": []})

    _client().search("Angular")

    assert requests_mock.last_request.json()["location"] == "Germany"


def test_snippet_html_is_stripped(requests_mock):
    requests_mock.post(URL, json={"jobs": [_job()]})

    offers = _client().search("Angular")

    assert offers[0].description_text == "Wir suchen einen Angular-Entwickler."


def test_salary_prose_folds_into_description_text(requests_mock):
    requests_mock.post(URL, json={"jobs": [_job(salary="50000 - 70000 EUR")]})

    offers = _client().search("Angular")

    assert "Gehalt: 50000 - 70000 EUR" in offers[0].description_text
    # Kein neues strukturiertes Feld (KD8/KTD6).
    assert "salary" not in JobOfferCreate.model_fields
    assert "homeoffice" not in JobOfferCreate.model_fields


# --- Edge: id handling / malformed / unsafe records ------------------------


def test_large_numeric_id_is_preserved_as_a_string(requests_mock):
    large_id = 1234567890123456789
    requests_mock.post(URL, json={"jobs": [_job(id=large_id, link=None)]})

    offers = _client().search("Angular")

    assert offers[0].source_url == f"https://jooble.org/desc/{large_id}"


@pytest.mark.parametrize(
    "unsafe_link",
    [
        "http://192.168.1.5/job/1",  # privater Host
        "http://localhost:8000/job/1",  # Loopback
        "javascript:alert(1)",  # Nicht-http(s)
        "ftp://example.com/job/1",  # Nicht-http(s)
    ],
)
def test_unsafe_link_is_rejected(requests_mock, unsafe_link):
    payload = {
        "jobs": [
            _job(id=1234567890123456789, link=unsafe_link),  # wird verworfen
            _job(id="2", title="Survivor", link="https://de.jooble.org/desc/2"),
        ]
    }
    requests_mock.post(URL, json=payload)

    offers = _client().search("Angular")

    assert [offer.title for offer in offers] == ["Survivor"]


def test_malformed_record_is_skipped_and_others_survive(requests_mock):
    payload = {"jobs": [_job(title=None), _job(id="2", title="Survivor")]}
    requests_mock.post(URL, json=payload)

    offers = _client().search("Angular")

    assert [offer.title for offer in offers] == ["Survivor"]


# --- Error: credential handling --------------------------------------------


def test_no_key_reports_not_configured_without_http(requests_mock):
    client = JoobleJobsClient(api_key="")

    assert client.is_configured() is False
    with pytest.raises(SourceNotConfiguredError):
        client.search("Angular")
    # Kein HTTP-Call bei fehlendem Key (KTD4).
    assert requests_mock.call_count == 0


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_key_raises_source_not_configured(requests_mock, status_code):
    requests_mock.post(URL, status_code=status_code)

    with pytest.raises(SourceNotConfiguredError):
        _client().search("Angular")


def test_429_returns_empty_list_and_records_cooldown(requests_mock):
    requests_mock.post(URL, status_code=429)

    offers = _client().search("Angular")

    assert offers == []
    assert JoobleJobsClient.is_cooldown_active() is True


def test_cooldown_skips_request_on_next_search(requests_mock):
    requests_mock.post(URL, status_code=429)
    _client().search("Angular")
    assert requests_mock.call_count == 1

    offers = _client().search("Angular")

    assert offers == []
    assert requests_mock.call_count == 1


def test_malformed_json_raises_for_error_status(requests_mock):
    requests_mock.post(URL, text="<html>not json</html>")

    with pytest.raises(RuntimeError):
        _client().search("Angular")


def test_malformed_json_maps_to_error_reason_via_orchestrator(requests_mock):
    requests_mock.post(URL, text="<html>not json</html>")
    service = JobSearchService(
        sources=[SourceRegistration(_client())],
        deadline_seconds=1.0,
    )

    response = service.search("Angular")

    status = next(s for s in response.sources if s.platform == "jooble")
    assert status.status == "unavailable"
    assert status.reason == "error"


def test_network_error_raises_without_leaking_the_key(requests_mock):
    requests_mock.post(URL, exc=requests.ConnectionError(f"boom {URL}"))

    with pytest.raises(RuntimeError) as excinfo:
        _client().search("Angular")

    assert API_KEY not in str(excinfo.value)


# --- Integration: log redaction + registry wiring ---------------------------


def test_key_never_appears_in_debug_logs(requests_mock, caplog):
    caplog.set_level(logging.DEBUG)
    requests_mock.post(URL, json={"jobs": []})

    _client().search("Angular", "Berlin")

    assert requests_mock.call_count == 1
    # Nur die Logs des Clients prüfen: `requests_mock`s Test-Adapter loggt die
    # rohe URL selbst, was in Produktion nicht passiert (Root-Logger ist dort
    # nicht auf DEBUG).
    client_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.job_sources.jooble"
    )
    assert API_KEY not in client_logs
    assert "https://jooble.org/api/***" in client_logs


def test_registry_registers_jooble_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "JOB_SEARCH_JOOBLE_ENABLED", True)
    monkeypatch.setattr(settings, "JOOBLE_API_KEY", API_KEY)

    service = JobSearchService(deadline_seconds=1.0)

    registration = next(reg for reg in service._sources if reg.platform == "jooble")  # noqa: SLF001
    assert registration.client.is_configured() is True
