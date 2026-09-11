"""Tests für `AdzunaJobsClient` (siehe backend/app/services/job_sources/adzuna.py).

Deckt die Testszenarien aus U4 des Plans ab:
docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md
"""
from __future__ import annotations

import logging

import pytest
import requests

from app.core.config import settings
from app.schemas.job_offer import JobOfferCreate
from app.services.job_search_service import JobSearchService
from app.services.job_sources.adzuna import AdzunaJobsClient
from app.services.job_sources.shared import SourceNotConfiguredError

APP_ID = "test-app-id"
APP_KEY = "test-app-key"


def _result(**overrides):
    base = {
        "id": "1",
        "title": "Angular Developer",
        "company": {"display_name": "Acme GmbH"},
        "location": {"display_name": "Berlin, Deutschland"},
        "redirect_url": "https://www.adzuna.de/details/1",
        "description": "<p>Wir suchen einen Angular-Entwickler.</p>",
    }
    base.update(overrides)
    return base


def _client(**kwargs) -> AdzunaJobsClient:
    kwargs.setdefault("app_id", APP_ID)
    kwargs.setdefault("app_key", APP_KEY)
    return AdzunaJobsClient(**kwargs)


def _reset_cooldown() -> None:
    AdzunaJobsClient._cooldown_until = 0.0  # noqa: SLF001 - bewusster Test-Reset


def setup_function() -> None:
    _reset_cooldown()


def teardown_function() -> None:
    _reset_cooldown()


# --- Happy path -------------------------------------------------------------


def test_happy_path_maps_all_results_with_adzuna_platform(requests_mock):
    payload = {"count": 2, "results": [_result(), _result(id="2", title="Backend Engineer")]}
    requests_mock.get(AdzunaJobsClient.BASE_URL, json=payload)

    offers = _client().search("Angular", "Berlin")

    assert len(offers) == 2
    assert all(offer.source_platform == "adzuna" for offer in offers)
    assert offers[0].title == "Angular Developer"
    assert offers[0].company == "Acme GmbH"
    assert offers[0].location == "Berlin, Deutschland"
    assert offers[0].source_url == "https://www.adzuna.de/details/1"


def test_request_targets_germany_path_and_sends_required_params(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, json={"results": []})

    _client().search("Angular", "Berlin")

    request = requests_mock.last_request
    assert request.path == "/v1/api/jobs/de/search/1"
    assert request.qs["app_id"] == [APP_ID]
    assert request.qs["app_key"] == [APP_KEY]
    assert request.qs["what"][0].lower() == "angular"
    assert "results_per_page" in request.qs
    assert request.qs["where"] == ["berlin"]


def test_missing_where_omits_the_param(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, json={"results": []})

    _client().search("Angular")

    assert "where" not in requests_mock.last_request.qs


def test_description_html_is_stripped(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, json={"results": [_result()]})

    offers = _client().search("Angular")

    assert offers[0].description_text == "Wir suchen einen Angular-Entwickler."


# --- Edge: malformed / unsafe records --------------------------------------


def test_malformed_record_is_skipped_and_others_survive(requests_mock):
    payload = {
        "results": [
            _result(title=None),  # fehlender Titel -> übersprungen
            _result(id="2", title="Backend Engineer"),
        ]
    }
    requests_mock.get(AdzunaJobsClient.BASE_URL, json=payload)

    offers = _client().search("Angular")

    assert [offer.title for offer in offers] == ["Backend Engineer"]


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://192.168.1.5/job/1",  # privater Host
        "http://localhost:8000/job/1",  # Loopback
        "javascript:alert(1)",  # Nicht-http(s)
        "ftp://example.com/job/1",  # Nicht-http(s)
    ],
)
def test_unsafe_redirect_url_is_rejected(requests_mock, unsafe_url):
    payload = {"results": [_result(redirect_url=unsafe_url), _result(id="2", title="Survivor")]}
    requests_mock.get(AdzunaJobsClient.BASE_URL, json=payload)

    offers = _client().search("Angular")

    assert [offer.title for offer in offers] == ["Survivor"]


def test_invalid_json_returns_empty_list(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, text="<html>not json</html>")

    assert _client().search("Angular") == []


def test_other_http_error_returns_empty_list(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, status_code=500)

    assert _client().search("Angular") == []


def test_request_exception_returns_empty_list_without_raising(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, exc=requests.ConnectionError("boom"))

    assert _client().search("Angular") == []


# --- Error: credential handling --------------------------------------------


def test_no_credentials_reports_not_configured_without_http(requests_mock):
    client = AdzunaJobsClient(app_id="", app_key="")

    assert client.is_configured() is False
    with pytest.raises(SourceNotConfiguredError):
        client.search("Angular")
    # Kein HTTP-Call bei fehlenden Zugangsdaten (KTD4).
    assert requests_mock.call_count == 0


def test_partial_credentials_are_treated_as_not_configured(requests_mock):
    client = AdzunaJobsClient(app_id=APP_ID, app_key="")

    assert client.is_configured() is False
    with pytest.raises(SourceNotConfiguredError):
        client.search("Angular")
    assert requests_mock.call_count == 0


@pytest.mark.parametrize("status_code", [401, 403, 410])
def test_rejected_credentials_raise_source_not_configured(requests_mock, status_code):
    requests_mock.get(AdzunaJobsClient.BASE_URL, status_code=status_code)

    with pytest.raises(SourceNotConfiguredError):
        _client().search("Angular")


def test_429_returns_empty_list_and_records_cooldown(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, status_code=429)

    offers = _client().search("Angular")

    assert offers == []
    assert AdzunaJobsClient.is_cooldown_active() is True


def test_cooldown_skips_request_on_next_search(requests_mock):
    requests_mock.get(AdzunaJobsClient.BASE_URL, status_code=429)
    _client().search("Angular")
    assert requests_mock.call_count == 1

    offers = _client().search("Angular")

    assert offers == []
    assert requests_mock.call_count == 1


# --- Integration: salary prose + log redaction ------------------------------


def test_salary_prose_folds_into_description_text(requests_mock):
    payload = {
        "results": [
            _result(salary_min=50000.0, salary_max=70000.0, salary_is_predicted="0")
        ]
    }
    requests_mock.get(AdzunaJobsClient.BASE_URL, json=payload)

    offers = _client().search("Angular")

    assert "Gehalt: 50.000 - 70.000 EUR" in offers[0].description_text
    # Kein neues strukturiertes Feld (KD8/KTD6).
    assert "salary" not in JobOfferCreate.model_fields
    assert "homeoffice" not in JobOfferCreate.model_fields


def test_predicted_salary_is_marked(requests_mock):
    payload = {"results": [_result(salary_min=42000.0, salary_max=42000.0, salary_is_predicted="1")]}
    requests_mock.get(AdzunaJobsClient.BASE_URL, json=payload)

    offers = _client().search("Angular")

    assert "(geschätzt)" in offers[0].description_text


def test_app_key_never_appears_in_debug_logs(requests_mock, caplog):
    caplog.set_level(logging.DEBUG)
    requests_mock.get(AdzunaJobsClient.BASE_URL, json={"results": []})

    _client(app_key="super-secret-key").search("Angular", "Berlin")

    assert requests_mock.call_count == 1
    # Nur die Logs des Clients prüfen: `requests_mock`s Test-Adapter loggt die
    # rohe URL selbst, was in Produktion nicht passiert (Root-Logger ist dort
    # nicht auf DEBUG).
    client_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.job_sources.adzuna"
    )
    assert "super-secret-key" not in client_logs
    assert "app_key=***" in client_logs


# --- Wiring into the settings-derived registry ------------------------------


def test_registry_registers_adzuna_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "JOB_SEARCH_ADZUNA_ENABLED", True)
    monkeypatch.setattr(settings, "ADZUNA_APP_ID", APP_ID)
    monkeypatch.setattr(settings, "ADZUNA_APP_KEY", APP_KEY)

    service = JobSearchService(deadline_seconds=1.0)

    registration = next(reg for reg in service._sources if reg.platform == "adzuna")  # noqa: SLF001
    assert registration.client.is_configured() is True
