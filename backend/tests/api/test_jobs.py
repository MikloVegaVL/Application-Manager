"""Tests für die Jobs-API-Route (siehe U5 des Plans:
docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).

Nutzt eine eigene In-Memory-SQLite-Engine statt der App-Lifespan-
Initialisierung (`init_db()`), damit Tests keine echte `app.db`-Datei im
Repo anlegen.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registriert Modelle in Base.metadata
from app.db.database import Base, get_db
from app.main import app
from app.schemas.job_offer import JobOfferCreate, JobSearchResponse, SourceStatus
from app.services.job_search_service import (
    JobSearchService,
    SourceRegistration,
    get_job_search_service,
)


@pytest.fixture
def client():
    # StaticPool: eine In-Memory-SQLite-DB existiert sonst nur pro
    # Connection - ohne StaticPool würde `create_all()` auf einer anderen
    # Connection laufen als spätere Requests und "no such table" werfen.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _fake_search_response() -> JobSearchResponse:
    return JobSearchResponse(
        results=[
            JobOfferCreate(
                title="Angular Developer",
                company="Acme",
                location="Berlin",
                source_url="https://example.com/job/1",
                description_text=None,
                source_platform="arbeitsagentur",
            )
        ],
        sources=[
            SourceStatus(platform="arbeitsagentur", status="ok"),
            SourceStatus(platform="linkedin", status="unavailable", reason="timeout"),
            SourceStatus(platform="xing", status="unavailable", reason="empty"),
        ],
    )


class _FakeJobSearchService:
    def search(self, keywords, location=None, fallback_url=None):
        return _fake_search_response()


def test_search_returns_envelope_with_results_and_sources(client):
    app.dependency_overrides[get_job_search_service] = lambda: _FakeJobSearchService()

    response = client.get("/api/jobs/search", params={"keywords": "Angular"})

    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert "sources" in body
    assert len(body["results"]) == 1
    assert len(body["sources"]) == 3
    assert {s["platform"] for s in body["sources"]} == {"arbeitsagentur", "linkedin", "xing"}


# --- U8: End-to-end multi-source verification (2026-09-11 plan) -------------
#
# These tests override `get_job_search_service` with a REAL `JobSearchService`
# wired to a fake 12-source registry through the U2 injection seam
# (`sources=`). Reusing `_FakeJobSearchService` above would make the envelope
# assertions tautological - U8 exists to exercise the real fan-out, deadline
# participation, and per-source status mapping (KTD3/KTD8/KTD9/KTD11).

_ALL_SOURCE_PLATFORMS = (
    "arbeitsagentur",
    "linkedin",
    "xing",
    "devjobs",
    "kimeta",
    "stepstone",
    "germantechjobs",
    "indeed",
    "programmiererjobboerse",
    "it-entwickler-jobs",
    "adzuna",
    "jooble",
)

_NOT_OK_PLATFORMS = {"xing", "indeed", "adzuna", "jooble"}


class _FakeSourceClient:
    """Test-Double mit dem Standard-Vertrag `SOURCE_PLATFORM` + `search()`
    (KTD3/KTD9) - bewusst KEIN `JobSearchService`, damit der echte Fan-out
    und die echte Status-Mapping-Logik laufen."""

    def __init__(
        self,
        platform: str,
        offers: list[JobOfferCreate] | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
        configured: bool = True,
    ) -> None:
        self.SOURCE_PLATFORM = platform
        self._offers = offers or []
        self._exc = exc
        self._delay = delay
        self._configured = configured
        self.calls: list[tuple] = []

    def is_configured(self) -> bool:
        return self._configured

    def search(self, keywords, location=None):
        self.calls.append((keywords, location))
        if self._delay:
            time.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return self._offers


def _source_offer(platform: str) -> JobOfferCreate:
    return JobOfferCreate(
        title=f"{platform} Angular Developer",
        company="Acme",
        location="Berlin",
        source_url=f"https://example.com/{platform}/job/1",
        description_text=None,
        source_platform=platform,
    )


def _mixed_multi_source_service(deadline_seconds: float = 5.0):
    """Ein echter `JobSearchService` über alle 12 Quellen mit gemischten
    Ergebnissen: ok / empty / error / not-configured (U8)."""
    registrations: list[SourceRegistration] = []
    clients: dict[str, _FakeSourceClient] = {}
    for platform in _ALL_SOURCE_PLATFORMS:
        if platform in ("adzuna", "jooble"):
            client = _FakeSourceClient(platform, configured=False)
        elif platform == "xing":
            client = _FakeSourceClient(platform, offers=[])
        elif platform == "indeed":
            client = _FakeSourceClient(platform, exc=RuntimeError("simulated source failure"))
        else:
            client = _FakeSourceClient(platform, offers=[_source_offer(platform)])
        clients[platform] = client
        registrations.append(SourceRegistration(client))
    return JobSearchService(sources=registrations, deadline_seconds=deadline_seconds), clients


def test_real_service_fans_out_over_all_12_sources_with_per_source_status(client):
    service, clients = _mixed_multi_source_service()
    app.dependency_overrides[get_job_search_service] = lambda: service

    response = client.get("/api/jobs/search", params={"keywords": "Angular"})

    assert response.status_code == 200
    body = response.json()

    # One status entry per registered source, no source silently dropped (R5).
    assert len(body["sources"]) == len(_ALL_SOURCE_PLATFORMS)
    assert {s["platform"] for s in body["sources"]} == set(_ALL_SOURCE_PLATFORMS)

    by_platform = {s["platform"]: s for s in body["sources"]}
    assert by_platform["xing"] == {
        "platform": "xing",
        "status": "unavailable",
        "reason": "empty",
    }
    assert by_platform["indeed"] == {
        "platform": "indeed",
        "status": "unavailable",
        "reason": "error",
    }
    # The unconfigured Adzuna/Jooble pair appears as not-configured alongside
    # the ok sources (KTD9/R9) - without ever calling `search()`.
    assert by_platform["adzuna"] == {
        "platform": "adzuna",
        "status": "unavailable",
        "reason": "not-configured",
    }
    assert by_platform["jooble"] == {
        "platform": "jooble",
        "status": "unavailable",
        "reason": "not-configured",
    }
    assert clients["adzuna"].calls == []
    assert clients["jooble"].calls == []

    ok_platforms = set(_ALL_SOURCE_PLATFORMS) - _NOT_OK_PLATFORMS
    assert {s["platform"] for s in body["sources"] if s["status"] == "ok"} == ok_platforms

    # Merged results carry their responding source's own `source_platform`.
    assert len(body["results"]) == len(ok_platforms)
    assert {r["source_platform"] for r in body["results"]} == ok_platforms
    for result in body["results"]:
        assert result["source_url"].startswith("https://example.com/")
        assert result["source_platform"] in ok_platforms


def test_real_service_timeout_does_not_delay_response_beyond_deadline(client):
    """KTD8: a timing-out source is labeled `timeout` and the response comes
    back at the shared deadline, not after the slow source finishes."""
    registrations: list[SourceRegistration] = []
    for platform in _ALL_SOURCE_PLATFORMS:
        if platform in ("adzuna", "jooble"):
            registrations.append(
                SourceRegistration(_FakeSourceClient(platform, configured=False))
            )
        elif platform == "indeed":
            registrations.append(SourceRegistration(_FakeSourceClient(platform, delay=2.0)))
        else:
            registrations.append(
                SourceRegistration(_FakeSourceClient(platform, offers=[_source_offer(platform)]))
            )
    service = JobSearchService(sources=registrations, deadline_seconds=0.3)
    app.dependency_overrides[get_job_search_service] = lambda: service

    started = time.monotonic()
    response = client.get("/api/jobs/search", params={"keywords": "Angular"})
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    body = response.json()
    assert len(body["sources"]) == len(_ALL_SOURCE_PLATFORMS)
    indeed_status = next(s for s in body["sources"] if s["platform"] == "indeed")
    assert indeed_status["status"] == "unavailable"
    assert indeed_status["reason"] == "timeout"
    assert elapsed < 1.0


def test_save_job_returns_201(client):
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/42",
        "description_text": None,
        "source_platform": "linkedin",
    }

    response = client.post("/api/jobs/save", json=payload)

    assert response.status_code == 201
    assert response.json()["source_url"] == payload["source_url"]


def test_save_job_duplicate_source_url_returns_409(client):
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/dup",
        "description_text": None,
        "source_platform": "linkedin",
    }
    client.post("/api/jobs/save", json=payload)

    response = client.post("/api/jobs/save", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["job_offer_id"] is not None


def test_save_job_duplicate_backfills_missing_application(client):
    """Regression test (ce-debug, 2026-08-24): a `JobOffer` saved before the
    `98d31c0` atomic-insert fix has no `Application` row. Re-saving it (the
    "Bewerbung generieren" flow re-hitting `POST /jobs/save` for a job the
    frontend no longer has cached) must backfill the missing draft
    `Application` instead of leaving it permanently absent from
    `GET /applications`."""
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/legacy-orphan",
        "description_text": None,
        "source_platform": "linkedin",
    }
    job_offer_id = client.post("/api/jobs/save", json=payload).json()["id"]

    # Simulates a legacy orphan: a JobOffer that predates the fix and has no
    # paired Application row (see also `test_save_job_returns_201`, which
    # already covers the happy path's atomic insert).
    engine = app.dependency_overrides[get_db]
    session = next(engine())
    from app.models.application import Application

    session.query(Application).filter(Application.job_offer_id == job_offer_id).delete()
    session.commit()
    session.close()
    assert client.get("/api/applications").json() == []

    response = client.post("/api/jobs/save", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["job_offer_id"] == job_offer_id
    applications = client.get("/api/applications").json()
    assert len(applications) == 1
    assert applications[0]["job_offer"]["id"] == job_offer_id


def test_get_job_not_found_returns_404(client):
    response = client.get("/api/jobs/999999")

    assert response.status_code == 404


def test_get_job_returns_saved_job(client):
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/fetch-me",
        "description_text": None,
        "source_platform": "linkedin",
    }
    saved = client.post("/api/jobs/save", json=payload).json()

    response = client.get(f"/api/jobs/{saved['id']}")

    assert response.status_code == 200
    assert response.json()["source_url"] == payload["source_url"]


# --- Lazy description enrichment (ce-debug follow-up, 2026-08-20) ---------
#
# `description_text` is empty for every job offer sourced through
# Arbeitsagentur/LinkedIn/Xing's search (KTD2: search hits are never
# persisted with a full detail fetch, see `JobSearchService.search`) - GET
# /jobs/{id} lazily fetches and caches it the first time a saved job offer
# with no description_text is reopened.


def test_get_job_lazily_enriches_and_persists_a_missing_description(client):
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/needs-description",
        "description_text": None,
        "source_platform": "arbeitsagentur",
    }
    saved = client.post("/api/jobs/save", json=payload).json()

    class _FakeEnrichingService:
        def __init__(self):
            self.calls: list[tuple] = []

        def enrich_description(self, source_platform, source_url):
            self.calls.append((source_platform, source_url))
            return "Bitte sende deine Bewerbung an bewerbung@acme.example."

    fake_service = _FakeEnrichingService()
    app.dependency_overrides[get_job_search_service] = lambda: fake_service

    first_response = client.get(f"/api/jobs/{saved['id']}")
    second_response = client.get(f"/api/jobs/{saved['id']}")

    assert first_response.json()["description_text"] == "Bitte sende deine Bewerbung an bewerbung@acme.example."
    assert second_response.json()["description_text"] == "Bitte sende deine Bewerbung an bewerbung@acme.example."
    # Nur beim ersten Aufruf war description_text leer - der zweite Aufruf
    # darf den externen Call nicht wiederholen.
    assert fake_service.calls == [("arbeitsagentur", "https://example.com/job/needs-description")]


def test_get_job_stays_empty_when_enrichment_finds_nothing(client):
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/no-description-available",
        "description_text": None,
        "source_platform": "xing",
    }
    saved = client.post("/api/jobs/save", json=payload).json()

    class _FakeEmptyService:
        def enrich_description(self, source_platform, source_url):
            return None

    app.dependency_overrides[get_job_search_service] = lambda: _FakeEmptyService()

    response = client.get(f"/api/jobs/{saved['id']}")

    assert response.status_code == 200
    assert response.json()["description_text"] is None


def test_get_job_does_not_call_enrichment_when_description_already_present(client):
    payload = {
        "title": "Angular Developer",
        "company": "Acme",
        "location": "Berlin",
        "source_url": "https://example.com/job/already-has-description",
        "description_text": "Schon vorhanden.",
        "source_platform": "arbeitsagentur",
    }
    saved = client.post("/api/jobs/save", json=payload).json()

    class _FailingService:
        def enrich_description(self, source_platform, source_url):
            raise AssertionError("enrich_description must not be called when description_text is already set")

    app.dependency_overrides[get_job_search_service] = lambda: _FailingService()

    response = client.get(f"/api/jobs/{saved['id']}")

    assert response.status_code == 200
    assert response.json()["description_text"] == "Schon vorhanden."
