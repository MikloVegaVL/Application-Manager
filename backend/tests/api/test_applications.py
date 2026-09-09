"""Tests für die Applications-API-Route, insbesondere `GET /applications`
(Übersicht aller Bewerbungen für die Frontend-Seite "Bewerbungen" - siehe
`frontend/src/app/pages/applications/applications.component.ts`, die zuvor
nur ein Platzhalter ohne Datenanbindung war).

Nutzt eine eigene In-Memory-SQLite-Engine statt der App-Lifespan-
Initialisierung (`init_db()`), damit Tests keine echte `app.db`-Datei im
Repo anlegen (gleiches Muster wie `tests/api/test_jobs.py`).
"""
from __future__ import annotations

import threading
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
from app.models.master_profile import MasterProfile
from app.models.profile_attachment import ProfileAttachment
from app.services.ai_generator import ApplicationGenerationError


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


def _create_profile(session) -> MasterProfile:
    profile = MasterProfile(full_name="Max Mustermann", email="max.mustermann@example.com")
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def _create_profile_with_cv_file(session, tmp_path, *, filename: str = "lebenslauf.pdf") -> MasterProfile:
    """Legt ein Profil MIT hochgeladener Lebenslauf-Anhang-Datei an - das ist
    seit dem Wegfall der KI-CV-Generierung Voraussetzung für `POST
    /{id}/send` (siehe `app.api.applications.send_application`)."""
    cv_path = tmp_path / "cv.pdf"
    cv_path.write_bytes(b"%PDF-1.4 fake-cv")
    profile = MasterProfile(
        full_name="Max Mustermann",
        email="max.mustermann@example.com",
        cv_file_path=str(cv_path),
        cv_filename=filename,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


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


def test_list_applications_includes_a_job_saved_without_generating_yet(client: TestClient) -> None:
    # Regression: "Job speichern" in der Jobsuche legte bislang nur ein
    # JobOffer an, aber nie eine Application - ein gespeicherter, aber noch
    # nicht generierter Job erschien dadurch nirgends auf der
    # Bewerbungsübersicht (ce-debug-Untersuchung, 2026-08-20). `POST
    # /jobs/save` muss dafür sofort eine Bewerbung im Status "draft" ohne
    # Anschreiben anlegen.
    payload = {
        "title": "Backend Engineer",
        "company": "Acme GmbH",
        "location": "Berlin",
        "source_url": "https://example.com/job/saved-only",
        "description_text": None,
        "source_platform": "arbeitsagentur",
    }
    save_response = client.post("/api/jobs/save", json=payload)
    assert save_response.status_code == 201

    response = client.get("/api/applications")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "draft"
    assert body[0]["cover_letter_text"] is None
    assert body[0]["job_offer"]["title"] == "Backend Engineer"


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


def test_delete_application_removes_it(client: TestClient, db_session_local) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
    finally:
        session.close()

    response = client.delete(f"/api/applications/{application_id}")

    assert response.status_code == 204
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


def test_update_application_updates_cover_letter_text_without_ai_call(
    client: TestClient, db_session_local
) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
    finally:
        session.close()

    response = client.put(
        f"/api/applications/{application_id}",
        json={"cover_letter_text": "Betreff: Neue Position\n\nSehr geehrte Damen und Herren,..."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cover_letter_text"] == "Betreff: Neue Position\n\nSehr geehrte Damen und Herren,..."


def test_generate_application_returns_409_for_an_overlapping_request_on_the_same_job_offer(
    client: TestClient, db_session_local, monkeypatch
) -> None:
    # Regression (ce-debug-Untersuchung, 2026-08-28): Der Editor stößt bei
    # jedem Mounten mit noch leerem `cover_letter_text` erneut eine
    # Generierung an (z. B. nach Browser-Zurück oder Reload, bevor die erste
    # Generierung fertig ist). Ohne diese Sperre lief für dasselbe
    # Stellenangebot eine zweite, überlappende KI-Generierung los, die das
    # Ergebnis der ersten überschrieb - der Editor wirkte dadurch, als würde
    # er endlos ohne Ergebnis laufen.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/generate-dup"
        )
        job_offer_id = job_offer.id
        _create_profile(session)
    finally:
        session.close()

    first_call_started = threading.Event()
    release_first_call = threading.Event()

    def slow_generate(profile, job_offer):
        first_call_started.set()
        assert release_first_call.wait(timeout=2), "Test-Deadlock"
        return "Betreff: Bewerbung als Backend Engineer\n\nSehr geehrte Damen und Herren,..."

    monkeypatch.setattr("app.api.applications.generate_application_content", slow_generate)

    first_response: dict[str, object] = {}

    def call_generate() -> None:
        first_response["response"] = client.post(
            "/api/applications/generate", json={"job_offer_id": job_offer_id}
        )

    first_thread = threading.Thread(target=call_generate)
    first_thread.start()
    assert first_call_started.wait(timeout=2), "erste Generierung ist nicht gestartet"

    duplicate_response = client.post("/api/applications/generate", json={"job_offer_id": job_offer_id})

    release_first_call.set()
    first_thread.join(timeout=2)

    assert duplicate_response.status_code == 409
    assert "bereits eine Generierung" in duplicate_response.json()["detail"]
    assert first_response["response"].status_code == 200  # type: ignore[union-attr]

    # Die Sperre muss nach Abschluss wieder freigegeben sein - ein Folgeaufruf
    # darf nicht dauerhaft mit 409 blockiert bleiben.
    monkeypatch.setattr(
        "app.api.applications.generate_application_content",
        lambda profile, job_offer: "Zweite Generierung",
    )
    follow_up_response = client.post("/api/applications/generate", json={"job_offer_id": job_offer_id})
    assert follow_up_response.status_code == 200


def test_generate_application_guard_is_scoped_per_job_offer_not_global(
    client: TestClient, db_session_local, monkeypatch
) -> None:
    # Die Sperre (`_generating_job_offer_ids`) ist ein `set`, das per
    # `job_offer.id` prüft - ein laufender Aufruf für Stellenangebot A darf
    # einen Aufruf für ein ANDERES Stellenangebot B nicht mit 409 blockieren
    # (ce-code-review-Fund, 2026-08-28: mehrere Reviewer bemängelten, dass
    # nur die Docstring/Kommentare das behaupten, kein Test es beweist).
    session = db_session_local()
    try:
        job_offer_a = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/generate-scope-a"
        )
        job_offer_b = _create_job_offer(
            session, title="Frontend Engineer", company="Acme GmbH", source_url="https://example.com/job/generate-scope-b"
        )
        job_offer_a_id = job_offer_a.id
        job_offer_b_id = job_offer_b.id
        _create_profile(session)
    finally:
        session.close()

    first_call_started = threading.Event()
    release_first_call = threading.Event()

    def slow_generate(profile, job_offer):
        first_call_started.set()
        assert release_first_call.wait(timeout=2), "Test-Deadlock"
        return "Betreff: Bewerbung als Backend Engineer\n\nSehr geehrte Damen und Herren,..."

    monkeypatch.setattr("app.api.applications.generate_application_content", slow_generate)

    first_response: dict[str, object] = {}

    def call_generate_for_a() -> None:
        first_response["response"] = client.post(
            "/api/applications/generate", json={"job_offer_id": job_offer_a_id}
        )

    first_thread = threading.Thread(target=call_generate_for_a)
    first_thread.start()
    assert first_call_started.wait(timeout=2), "Generierung für Job A ist nicht gestartet"

    # Job A läuft noch (im Test-Deadlock via release_first_call) - ein
    # gleichzeitiger Aufruf für Job B muss trotzdem durchlaufen, nicht 409.
    monkeypatch.setattr(
        "app.api.applications.generate_application_content",
        lambda profile, job_offer: "Betreff: Bewerbung als Frontend Engineer\n\nSehr geehrte Damen und Herren,...",
    )
    other_job_response = client.post("/api/applications/generate", json={"job_offer_id": job_offer_b_id})

    release_first_call.set()
    first_thread.join(timeout=2)

    assert other_job_response.status_code == 200
    assert first_response["response"].status_code == 200  # type: ignore[union-attr]


def test_generate_application_releases_the_lock_when_generation_fails(
    client: TestClient, db_session_local, monkeypatch
) -> None:
    # Die Sperre wird in einem `finally` freigegeben (siehe
    # `app.api.applications.generate_application`) - andernfalls bliebe ein
    # Stellenangebot nach einem fehlgeschlagenen KI-Aufruf dauerhaft mit 409
    # blockiert, obwohl gar keine Generierung mehr läuft.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/generate-fail"
        )
        job_offer_id = job_offer.id
        _create_profile(session)
    finally:
        session.close()

    def failing_generate(profile, job_offer):
        raise ApplicationGenerationError("Ollama ist nicht erreichbar")

    monkeypatch.setattr("app.api.applications.generate_application_content", failing_generate)

    failed_response = client.post("/api/applications/generate", json={"job_offer_id": job_offer_id})
    assert failed_response.status_code == 502

    monkeypatch.setattr(
        "app.api.applications.generate_application_content",
        lambda profile, job_offer: "Erfolgreiche Generierung nach vorherigem Fehler",
    )
    retry_response = client.post("/api/applications/generate", json={"job_offer_id": job_offer_id})
    assert retry_response.status_code == 200


def test_send_application_fails_when_no_cv_file_uploaded(client: TestClient, db_session_local) -> None:
    # Regression: seit Wegfall der KI-CV-Generierung braucht der Versand die
    # im Profil hochgeladene Lebenslauf-Datei statt eines gerenderten PDFs.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
    finally:
        session.close()

    response = client.post(
        f"/api/applications/{application_id}/send",
        json={"to_email": "recruiter@example.com"},
    )

    assert response.status_code == 422
    assert "Lebenslauf" in response.json()["detail"]


def test_send_application_with_blank_subject_and_message_uses_reworded_fallback(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/1"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
        _create_profile_with_cv_file(session, tmp_path, filename="mein-lebenslauf.pdf")
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
    assert call_kwargs["attachment_filename"] == "mein-lebenslauf.pdf"
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
        application_id = _create_application(session, job_offer_id=job_offer.id).id
        _create_profile_with_cv_file(session, tmp_path)
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


def test_send_application_marks_application_as_sent(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/3"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
        _create_profile_with_cv_file(session, tmp_path)
    finally:
        session.close()

    monkeypatch.setattr("app.api.applications.send_application_email", Mock(return_value=None))

    response = client.post(
        f"/api/applications/{application_id}/send",
        json={"to_email": "recruiter@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert body["sent_at"] is not None


def test_send_application_includes_profile_attachments_alongside_cv(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    # Regression: zusätzliche PDF-Anhänge im Profil (siehe `ProfileAttachment`,
    # `app.api.profile`) müssen neben dem Lebenslauf mitgeschickt werden, ohne
    # den Lebenslauf-Anhang selbst zu verdrängen.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/4"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
        profile = _create_profile_with_cv_file(session, tmp_path)

        attachment_path = tmp_path / "zeugnis.pdf"
        attachment_path.write_bytes(b"%PDF-1.4 fake-zeugnis")
        session.add(
            ProfileAttachment(profile_id=profile.id, file_path=str(attachment_path), filename="zeugnis.pdf")
        )
        session.commit()
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
    assert call_kwargs["attachment_filename"] == "lebenslauf.pdf"
    assert call_kwargs["extra_attachments"] == [(b"%PDF-1.4 fake-zeugnis", "zeugnis.pdf")]


def test_send_application_skips_missing_attachment_files(
    client: TestClient, db_session_local, tmp_path, monkeypatch
) -> None:
    # Eine am Profil hängende, aber von der Platte verschwundene Anhang-Datei
    # darf den Versand nicht blockieren - der Lebenslauf bleibt der einzige
    # Pflicht-Anhang.
    session = db_session_local()
    try:
        job_offer = _create_job_offer(
            session, title="Backend Engineer", company="Acme GmbH", source_url="https://example.com/job/5"
        )
        application_id = _create_application(session, job_offer_id=job_offer.id).id
        profile = _create_profile_with_cv_file(session, tmp_path)
        session.add(
            ProfileAttachment(
                profile_id=profile.id, file_path=str(tmp_path / "missing.pdf"), filename="missing.pdf"
            )
        )
        session.commit()
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
    assert call_kwargs["extra_attachments"] == []
