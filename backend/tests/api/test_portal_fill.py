"""Tests für die Fill-API der Browser-Erweiterung (U3,
docs/plans/2026-09-22-003-feat-browser-extension-application-autofill-plan.md).

Nutzt die `StaticPool` + Non-Context-Manager-`TestClient`-Fixture aus
`tests/api/test_jobs.py` (kein Lifespan/`init_db()` gegen die echte App-DB).
`llm_client.generate_structured` wird gemockt - kein echter Ollama-Aufruf.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registriert Modelle in Base.metadata
from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app
from app.models.application import Application
from app.models.job_offer import JobOffer
from app.models.master_profile import MasterProfile
from app.models.portal_submission import PortalSubmission
from app.services import llm_client, portal_fill_requests

LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs/view/1234567890"
LINKEDIN_JOB_URL_TRACKED = LINKEDIN_JOB_URL + "/?trackingId=abc&refId=xyz#frag"
SECRET = "test-portal-fill-secret"
SECRET_HEADER = {"X-Portal-Fill-Secret": SECRET}


@pytest.fixture
def db_session_local():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    yield testing_session_local


@pytest.fixture
def client(db_session_local, monkeypatch):
    def _override_get_db():
        db = db_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "PORTAL_FILL_SECRET", SECRET)
    portal_fill_requests.clear()
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app, base_url="http://localhost")
    finally:
        app.dependency_overrides.clear()
        portal_fill_requests.clear()


def _seed(db_session_local, *, source_platform: str = "linkedin") -> int:
    db = db_session_local()
    try:
        job_offer = JobOffer(
            title="Backend Engineer",
            company="Acme GmbH",
            location="Berlin",
            source_url=LINKEDIN_JOB_URL,
            description_text="Wir suchen einen Backend Engineer.",
            source_platform=source_platform,
        )
        db.add(job_offer)
        db.flush()
        application = Application(job_offer_id=job_offer.id, cover_letter_text="Sehr geehrte Damen und Herren,")
        db.add(application)
        db.add(MasterProfile(full_name="Max Mustermann", email="max@example.com", phone="+49 30 1234"))
        db.commit()
        db.refresh(application)
        return application.id
    finally:
        db.close()


def _create_fill_request(client: TestClient, application_id: int) -> str:
    response = client.post(f"/api/applications/{application_id}/fill-request", json={})
    assert response.status_code == 200
    return response.json()["job_url"]


def _count_submissions(db_session_local) -> int:
    db = db_session_local()
    try:
        return db.query(PortalSubmission).count()
    finally:
        db.close()


# --- Happy path + AE3 ------------------------------------------------------


def test_fill_request_and_context_return_packet_once(client, db_session_local):
    application_id = _seed(db_session_local)

    job_url = _create_fill_request(client, application_id)
    assert job_url == LINKEDIN_JOB_URL

    context = client.get(
        "/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL_TRACKED}, headers=SECRET_HEADER
    )
    assert context.status_code == 200
    packet = context.json()
    assert packet["application_id"] == application_id
    assert packet["job_title"] == "Backend Engineer"
    assert packet["company"] == "Acme GmbH"
    assert packet["job_description"] == "Wir suchen einen Backend Engineer."
    assert packet["cover_letter_text"] == "Sehr geehrte Damen und Herren,"
    assert packet["profile"]["full_name"] == "Max Mustermann"
    assert packet["profile"]["email"] == "max@example.com"

    # Single-use: ein zweiter Kontext-Abruf findet nichts mehr (AE3).
    second = client.get("/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER)
    assert second.status_code == 404


def test_context_without_matching_request_returns_404(client, db_session_local):
    _seed(db_session_local)

    response = client.get(
        "/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER
    )

    assert response.status_code == 404
    assert "detail" in response.json()


def test_context_validation_error_does_not_consume_the_request(client, db_session_local):
    # P3: ein Validierungsfehler (hier: kein Profil) darf den einmaligen
    # Request nicht verbrauchen - sonst müsste der Nutzer den Fill neu starten,
    # nur um denselben Fehler erneut zu sehen.
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)

    db = db_session_local()
    try:
        db.query(MasterProfile).delete()
        db.commit()
    finally:
        db.close()

    first = client.get(
        "/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER
    )
    assert first.status_code == 422

    db = db_session_local()
    try:
        db.add(MasterProfile(full_name="Max Mustermann", email="max@example.com", phone="+49 30 1234"))
        db.commit()
    finally:
        db.close()

    # Derselbe Request ist noch offen und liefert jetzt das Paket.
    second = client.get(
        "/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER
    )
    assert second.status_code == 200


def test_fill_request_unknown_application_returns_404(client, db_session_local):
    response = client.post("/api/applications/999999/fill-request", json={})

    assert response.status_code == 404


# --- AE7: no duplicate request --------------------------------------------


def test_second_fill_request_does_not_create_a_duplicate(client, db_session_local):
    application_id = _seed(db_session_local)

    first = client.post(f"/api/applications/{application_id}/fill-request", json={})
    second = client.post(f"/api/applications/{application_id}/fill-request", json={})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_url"] == second.json()["job_url"]
    with portal_fill_requests._requests_lock:
        assert len(portal_fill_requests._requests) == 1


# --- R2: non-LinkedIn rejected --------------------------------------------


def test_fill_request_rejects_non_linkedin_application(client, db_session_local):
    application_id = _seed(db_session_local, source_platform="arbeitsagentur")

    response = client.post(f"/api/applications/{application_id}/fill-request", json={})

    assert response.status_code == 422
    assert portal_fill_requests.get_active(application_id) is None


# --- Expired request -------------------------------------------------------


def test_expired_request_returns_404(client, db_session_local):
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)

    with portal_fill_requests._requests_lock:
        portal_fill_requests._requests[application_id].expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )

    response = client.get(
        "/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER
    )

    assert response.status_code == 404


# --- Answer endpoint -------------------------------------------------------


def test_answer_returns_mocked_llm_result(client, db_session_local, monkeypatch):
    application_id = _seed(db_session_local)
    monkeypatch.setattr(
        llm_client,
        "generate_structured",
        lambda model_cls, messages, **kwargs: model_cls(answer="Weil ich Sie kenne.", insufficient_information=False),
    )

    response = client.post(
        "/api/portal-fill/answer",
        json={"application_id": application_id, "question": "Warum möchten Sie bei uns arbeiten?"},
        headers=SECRET_HEADER,
    )

    assert response.status_code == 200
    assert response.json() == {"answer": "Weil ich Sie kenne.", "insufficient_information": False}


def test_answer_maps_llm_failure_to_502(client, db_session_local, monkeypatch):
    application_id = _seed(db_session_local)

    def _raise(*args, **kwargs):
        raise llm_client.LlmUnavailableError("Ollama ist nicht erreichbar.")

    monkeypatch.setattr(llm_client, "generate_structured", _raise)

    response = client.post(
        "/api/portal-fill/answer",
        json={"application_id": application_id, "question": "Warum?"},
        headers=SECRET_HEADER,
    )

    assert response.status_code == 502
    assert "Ollama" in response.json()["detail"]


# --- Submission: happy path + summary -------------------------------------


def test_submission_writes_row_and_exposes_summary(client, db_session_local):
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)
    client.get("/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER)

    response = client.post(
        "/api/portal-fill/submission",
        json={
            "report_id": "report-1",
            "job_offer_id": _job_offer_id(db_session_local, application_id),
            "portal_url": LINKEDIN_JOB_URL,
        },
        headers=SECRET_HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] == application_id
    assert body["company"] == "Acme GmbH"
    assert body["job_title"] == "Backend Engineer"
    assert body["platform"] == "linkedin"
    assert body["portal_url"] == LINKEDIN_JOB_URL
    assert body["submitted_at"] is not None

    application = client.get(f"/api/applications/{application_id}").json()
    assert application["submission"] is not None
    assert application["submission"]["platform"] == "linkedin"
    assert application["submission"]["portal_url"] == LINKEDIN_JOB_URL
    assert _count_submissions(db_session_local) == 1


def test_duplicate_report_id_returns_existing_row(client, db_session_local):
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)
    client.get("/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER)
    job_offer_id = _job_offer_id(db_session_local, application_id)
    payload = {"report_id": "report-dup", "job_offer_id": job_offer_id, "portal_url": LINKEDIN_JOB_URL}

    first = client.post("/api/portal-fill/submission", json=payload, headers=SECRET_HEADER)
    second = client.post("/api/portal-fill/submission", json=payload, headers=SECRET_HEADER)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["submitted_at"] == second.json()["submitted_at"]
    assert _count_submissions(db_session_local) == 1


def test_submission_after_application_deleted_is_accepted(client, db_session_local):
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)
    client.get("/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER)
    job_offer_id = _job_offer_id(db_session_local, application_id)

    db = db_session_local()
    try:
        db.query(Application).filter(Application.id == application_id).delete()
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/portal-fill/submission",
        json={"report_id": "report-orphan", "job_offer_id": job_offer_id, "portal_url": LINKEDIN_JOB_URL},
        headers=SECRET_HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] is None
    assert body["company"] == "Acme GmbH"
    assert body["job_title"] == "Backend Engineer"


def test_submission_rejects_a_mismatched_linkedin_url(client, db_session_local):
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)
    client.get("/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER)
    job_offer_id = _job_offer_id(db_session_local, application_id)

    response = client.post(
        "/api/portal-fill/submission",
        json={
            "report_id": "report-mismatch",
            "job_offer_id": job_offer_id,
            "portal_url": "https://www.linkedin.com/jobs/view/9999999999",
        },
        headers=SECRET_HEADER,
    )

    assert response.status_code == 422


def test_submission_requires_a_consumed_fill_request(client, db_session_local):
    # P3: ohne vorausgegangenen, konsumierten Fill-Request wird kein Report
    # akzeptiert.
    application_id = _seed(db_session_local)
    job_offer_id = _job_offer_id(db_session_local, application_id)

    response = client.post(
        "/api/portal-fill/submission",
        json={"report_id": "report-no-request", "job_offer_id": job_offer_id, "portal_url": LINKEDIN_JOB_URL},
        headers=SECRET_HEADER,
    )

    assert response.status_code == 422
    assert _count_submissions(db_session_local) == 0


def test_submission_accepts_an_external_portal_url_for_the_consumed_request(client, db_session_local):
    # R4-Fallback: die gemeldete URL ist die externe Arbeitgeber-Seite und
    # normalisiert zu None; sie wird akzeptiert, weil ein konsumierter Request
    # existiert.
    application_id = _seed(db_session_local)
    _create_fill_request(client, application_id)
    client.get("/api/portal-fill/context", params={"url": LINKEDIN_JOB_URL}, headers=SECRET_HEADER)
    job_offer_id = _job_offer_id(db_session_local, application_id)

    response = client.post(
        "/api/portal-fill/submission",
        json={
            "report_id": "report-external",
            "job_offer_id": job_offer_id,
            "portal_url": "https://jobs.example.com/apply/42",
        },
        headers=SECRET_HEADER,
    )

    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://jobs.example.com/apply/42"


# --- Security boundary -----------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/api/portal-fill/context", None),
        ("post", "/api/portal-fill/answer", {"application_id": 1, "question": "Warum?"}),
        ("post", "/api/portal-fill/submission", {"report_id": "r", "job_offer_id": 1, "portal_url": LINKEDIN_JOB_URL}),
    ],
)
def test_secret_gated_routes_reject_missing_secret(client, method, path, json_body):
    if method == "get":
        response = client.get(path, params={"url": LINKEDIN_JOB_URL})
    else:
        response = client.post(path, json=json_body)

    assert response.status_code == 401


def test_secret_gated_route_rejects_wrong_secret(client):
    response = client.get(
        "/api/portal-fill/context",
        params={"url": LINKEDIN_JOB_URL},
        headers={"X-Portal-Fill-Secret": "wrong"},
    )

    assert response.status_code == 401


# --- Multi-worker startup guard -------------------------------------------


def test_multi_worker_configuration_fails_loudly(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")

    with pytest.raises(portal_fill_requests.MultiWorkerConfigurationError):
        portal_fill_requests.assert_single_worker()


def test_single_worker_configuration_is_accepted(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    monkeypatch.delenv("GUNICORN_WORKERS", raising=False)

    portal_fill_requests.assert_single_worker()  # darf nicht werfen


# --- URL normalization -----------------------------------------------------


def test_normalize_linkedin_job_url_strips_tracking_params():
    assert (
        portal_fill_requests.normalize_linkedin_job_url(LINKEDIN_JOB_URL_TRACKED)
        == LINKEDIN_JOB_URL
    )
    assert (
        portal_fill_requests.normalize_linkedin_job_url("https://de.linkedin.com/jobs/view/42")
        == "https://www.linkedin.com/jobs/view/42"
    )
    assert portal_fill_requests.normalize_linkedin_job_url("https://example.com/jobs/view/42") is None
    assert portal_fill_requests.normalize_linkedin_job_url("https://www.linkedin.com/feed/") is None


def _job_offer_id(db_session_local, application_id: int) -> int:
    db = db_session_local()
    try:
        application = db.get(Application, application_id)
        return application.job_offer_id
    finally:
        db.close()
