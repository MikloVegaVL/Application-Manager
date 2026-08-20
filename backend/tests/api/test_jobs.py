"""Tests für die Jobs-API-Route (siehe U5 des Plans:
docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).

Nutzt eine eigene In-Memory-SQLite-Engine statt der App-Lifespan-
Initialisierung (`init_db()`), damit Tests keine echte `app.db`-Datei im
Repo anlegen.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registriert Modelle in Base.metadata
from app.db.database import Base, get_db
from app.main import app
from app.schemas.job_offer import JobOfferCreate, JobSearchResponse, SourceStatus
from app.services.job_search_service import get_job_search_service


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
