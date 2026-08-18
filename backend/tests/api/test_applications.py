"""Tests für die Applications-API-Route, insbesondere `GET /applications`
(Übersicht aller Bewerbungen für die Frontend-Seite "Bewerbungen" - siehe
`frontend/src/app/pages/applications/applications.component.ts`, die zuvor
nur ein Platzhalter ohne Datenanbindung war).

Nutzt eine eigene In-Memory-SQLite-Engine statt der App-Lifespan-
Initialisierung (`init_db()`), damit Tests keine echte `app.db`-Datei im
Repo anlegen (gleiches Muster wie `tests/api/test_jobs.py`).
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
from app.models.application import Application, ApplicationStatus
from app.models.job_offer import JobOffer


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
