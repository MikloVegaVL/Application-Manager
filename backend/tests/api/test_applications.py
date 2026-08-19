"""Tests für die Applications-API-Route, insbesondere `GET /applications`
(Übersicht aller Bewerbungen für die Frontend-Seite "Bewerbungen" - siehe
`frontend/src/app/pages/applications/applications.component.ts`, die zuvor
nur ein Platzhalter ohne Datenanbindung war).

Nutzt eine eigene In-Memory-SQLite-Engine statt der App-Lifespan-
Initialisierung (`init_db()`), damit Tests keine echte `app.db`-Datei im
Repo anlegen (gleiches Muster wie `tests/api/test_jobs.py`).
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registriert Modelle in Base.metadata
from app.db.database import Base, get_db
from app.main import app
from app.models.application import Application, ApplicationStatus
from app.models.job_offer import JobOffer

# Minimaler, aber schema-gültiger `TailoredCv`-Inhalt (siehe
# `app.schemas.generation.TailoredCv`) - genügt `TailoredCv.model_validate()`
# in `update_application`, ohne echte KI-Generierung anzustoßen.
_VALID_TAILORED_CV_JSON = {
    "full_name": "Max Mustermann",
    "email": "max.mustermann@example.com",
    "phone": None,
    "address": None,
    "summary": "Erfahrener Backend-Entwickler.",
    "experiences": [],
    "education": [],
    "skills": [],
}


@pytest.fixture
def db_session_local():
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
    yield testing_session_local


@pytest.fixture
def client(db_session_local):
    def _override_get_db():
        db = db_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _create_job_offer(session, *, title: str, company: str, source_url: str) -> JobOffer:
    job_offer = JobOffer(
        title=title,
        company=company,
        location="Berlin",
        source_url=source_url,
        description_text=None,
        source_platform="arbeitsagentur",
    )
    session.add(job_offer)
    session.commit()
    session.refresh(job_offer)
    return job_offer


def _create_application(session, *, job_offer_id: int, status: ApplicationStatus = ApplicationStatus.DRAFT) -> Application:
    application = Application(
        job_offer_id=job_offer_id,
        cover_letter_text="Sehr geehrte Damen und Herren...",
        status=status,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def test_list_applications_returns_empty_list_when_none_exist(client: TestClient) -> None:
    response = client.get("/api/applications")

    assert response.status_code == 200
    assert response.json() == []


def test_list_applications_returns_saved_applications_with_job_offer_info(
    client: TestClient, db_session_local
) -> None:
    # Regression für den Bug: die Bewerbungsübersicht zeigte nach dem
    # Generieren/Speichern einer Bewerbung nichts an, weil weder ein
    # Backend-Endpunkt noch die Frontend-Komponente die gespeicherten
    # Bewerbungen tatsächlich abgerufen haben.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application = _create_application(session, job_offer_id=job_offer.id)
    finally:
        session.close()

    response = client.get("/api/applications")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == application.id
    assert body[0]["status"] == "draft"
    assert body[0]["job_offer"]["title"] == "Backend Engineer"
    assert body[0]["job_offer"]["company"] == "Acme GmbH"


def test_list_applications_orders_most_recently_created_first(client: TestClient, db_session_local) -> None:
    session = db_session_local()
    try:
        job_offer_1 = _create_job_offer(
            session, title="Job A", company="A GmbH", source_url="https://example.com/job/a"
        )
        job_offer_2 = _create_job_offer(
            session, title="Job B", company="B GmbH", source_url="https://example.com/job/b"
        )
        first_id = _create_application(session, job_offer_id=job_offer_1.id).id
        second_id = _create_application(session, job_offer_id=job_offer_2.id).id
    finally:
        session.close()

    response = client.get("/api/applications")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [second_id, first_id]


def test_delete_application_removes_it_and_its_pdf_file(client: TestClient, db_session_local, tmp_path) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application = _create_application(session, job_offer_id=job_offer.id)
        pdf_path = tmp_path / f"application_{application.id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        application.pdf_path = str(pdf_path)
        session.commit()
        application_id = application.id
    finally:
        session.close()

    response = client.delete(f"/api/applications/{application_id}")

    assert response.status_code == 204
    assert not pdf_path.exists()
    assert client.get(f"/api/applications/{application_id}").status_code == 404


def test_delete_application_returns_404_for_unknown_id(client: TestClient) -> None:
    response = client.delete("/api/applications/999")

    assert response.status_code == 404


def test_delete_application_also_frees_the_job_offer_for_resaving(client: TestClient, db_session_local) -> None:
    # Regression: `source_url` ist eindeutig (siehe JobOffer-Modell) - blieb
    # das Stellenangebot nach dem Löschen der Bewerbung bestehen, schlug ein
    # erneutes Speichern/Generieren für denselben Job dauerhaft mit 409 fehl,
    # während die Bewerbung selbst nirgends mehr auffindbar war.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        job_offer_id = job_offer.id
        application_id = _create_application(session, job_offer_id=job_offer.id).id
    finally:
        session.close()

    response = client.delete(f"/api/applications/{application_id}")
    assert response.status_code == 204

    assert client.get(f"/api/jobs/{job_offer_id}").status_code == 404

    resave_response = client.post(
        "/api/jobs/save",
        json={
            "title": "Backend Engineer",
            "company": "Acme GmbH",
            "location": "Berlin",
            "source_url": "https://example.com/job/1",
            "description_text": None,
            "source_platform": "arbeitsagentur",
        },
    )
    assert resave_response.status_code == 201


def test_update_application_with_changed_cover_letter_text_rerenders_pdf_via_cv_only_renderer(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    # Regression: die Trigger-Bedingung fürs Neu-Rendern (Änderung an
    # `cover_letter_text` ODER `tailored_cv_json`) bleibt unverändert - nur
    # der aufgerufene Renderer wechselt von `render_application_pdf` zu
    # `render_cv_pdf` (siehe U1/U2, cv-only-email-attachment-Plan).
    monkeypatch.setattr("app.core.config.settings.GENERATED_FILES_DIR", str(tmp_path))

    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application = _create_application(session, job_offer_id=job_offer.id)
        application.tailored_cv_json = _VALID_TAILORED_CV_JSON
        session.commit()
        application_id = application.id
    finally:
        session.close()

    mock_render_cv_pdf = Mock(return_value=b"%PDF-1.4 fake-cv-pdf-bytes")
    monkeypatch.setattr("app.api.applications.render_cv_pdf", mock_render_cv_pdf)

    response = client.put(
        f"/api/applications/{application_id}",
        json={"cover_letter_text": "Betreff: Neue Position\n\nSehr geehrte Damen und Herren,..."},
    )

    assert response.status_code == 200
    mock_render_cv_pdf.assert_called_once()
    body = response.json()
    assert body["cover_letter_text"] == "Betreff: Neue Position\n\nSehr geehrte Damen und Herren,..."
    assert body["pdf_path"] is not None
    assert (tmp_path / f"application_{application_id}.pdf").read_bytes() == b"%PDF-1.4 fake-cv-pdf-bytes"


def test_get_application_pdf_uses_lebenslauf_filename_in_content_disposition(
    client: TestClient, db_session_local, tmp_path
) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application = _create_application(session, job_offer_id=job_offer.id)
        pdf_path = tmp_path / f"application_{application.id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        application.pdf_path = str(pdf_path)
        session.commit()
        application_id = application.id
    finally:
        session.close()

    response = client.get(f"/api/applications/{application_id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'inline; filename="lebenslauf_{application_id}.pdf"'


def test_send_application_with_blank_subject_and_message_uses_reworded_fallback(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application = _create_application(session, job_offer_id=job_offer.id)
        pdf_path = tmp_path / f"application_{application.id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        application.pdf_path = str(pdf_path)
        session.commit()
        application_id = application.id
    finally:
        session.close()

    mock_send_application_email = Mock(return_value=None)
    monkeypatch.setattr("app.api.applications.send_application_email", mock_send_application_email)

    response = client.post(
        f"/api/applications/{application_id}/send",
        json={"to_email": "recruiter@example.com", "subject": "", "message": ""},
    )

    assert response.status_code == 200
    mock_send_application_email.assert_called_once()
    _, call_kwargs = mock_send_application_email.call_args
    assert call_kwargs["subject"] == "Bewerbung als Backend Engineer"
    assert call_kwargs["attachment_filename"] == f"lebenslauf_{application_id}.pdf"
    assert "Anschreiben" not in call_kwargs["body_text"]
    assert "Lebenslauf" in call_kwargs["body_text"]


def test_send_application_fallback_body_text_does_not_mention_anschreiben(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/2"
        )
        application = _create_application(session, job_offer_id=job_offer.id)
        pdf_path = tmp_path / f"application_{application.id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        application.pdf_path = str(pdf_path)
        session.commit()
        application_id = application.id
    finally:
        session.close()

    mock_send_application_email = Mock(return_value=None)
    monkeypatch.setattr("app.api.applications.send_application_email", mock_send_application_email)

    response = client.post(
        f"/api/applications/{application_id}/send",
        json={"to_email": "recruiter@example.com"},
    )

    assert response.status_code == 200
    _, call_kwargs = mock_send_application_email.call_args
    assert "Anschreiben" not in call_kwargs["body_text"]
