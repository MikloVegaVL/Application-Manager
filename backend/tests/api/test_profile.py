"""Tests für die Profil-API-Route, insbesondere `POST /profile/upload-cv`
(siehe ce-debug-Untersuchung, 2026-08-18: ein CV-Import, der die KI-Antwort
teilweise leer zurückbekommt, ließ das Profil unverändert - ohne jede
Rückmeldung an den Nutzer, dass z. B. keine Berufserfahrung übernommen
wurde)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registriert Modelle in Base.metadata
from app.db.database import Base, get_db
from app.main import app
from app.models.master_profile import MasterProfile
from app.schemas.master_profile import ParsedCvProfile


@pytest.fixture
def client():
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
        yield TestClient(app), testing_session_local
    finally:
        app.dependency_overrides.clear()


def _upload(client: TestClient, mocker, parsed: ParsedCvProfile):
    mocker.patch("app.api.profile.parse_cv_pdf", return_value=parsed)
    return client.post(
        "/api/profile/upload-cv",
        files={"file": ("cv.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )


def test_upload_cv_with_full_data_returns_no_warnings(client, mocker):
    test_client, _ = client
    parsed = ParsedCvProfile(
        full_name="Max Mustermann",
        email="max@example.com",
        phone="0123456789",
        address="Musterstraße 1, Berlin",
        summary="Erfahrener Entwickler.",
        experiences=[
            {"company": "Acme GmbH", "role": "Entwickler", "start_date": "2020", "end_date": None}
        ],
        education=[{"institution": "TU Berlin", "degree": "B.Sc. Informatik"}],
        skills=["Python"],
    )

    response = _upload(test_client, mocker, parsed)

    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == []
    assert body["profile"]["full_name"] == "Max Mustermann"
    assert len(body["profile"]["experiences_json"]) == 1


def test_upload_cv_with_missing_experience_and_education_reports_warnings(client, mocker):
    """The core regression case: a parse that finds contact details/skills
    but no experience or education must still succeed (protecting existing
    data is correct behavior) but must tell the caller which fields were
    skipped, not silently report unconditional success."""
    test_client, _ = client
    parsed = ParsedCvProfile(
        full_name="Max Mustermann",
        email="max@example.com",
        experiences=[],
        education=[],
        skills=["Python"],
    )

    response = _upload(test_client, mocker, parsed)

    assert response.status_code == 200
    body = response.json()
    assert "Keine Berufserfahrung gefunden - vorhandene Angaben blieben unverändert." in body["warnings"]
    assert "Keine Ausbildung gefunden - vorhandene Angaben blieben unverändert." in body["warnings"]
    assert "Kein Kurzprofil/Zusammenfassung gefunden." in body["warnings"]
    # Skills wurden gefunden - dafür keine Warnung.
    assert "Keine Skills gefunden." not in body["warnings"]


def test_upload_cv_missing_experience_does_not_erase_existing_experience(client, mocker):
    """Locks in the pre-existing protective behavior this fix must not
    change: an empty parse result for a field must leave already-saved data
    untouched, only now with a visible warning explaining why."""
    test_client, session_local = client

    db = session_local()
    existing = MasterProfile(
        full_name="Bestehender Nutzer",
        email="bestehend@example.com",
        experiences_json=[{"company": "Alt GmbH", "role": "Alt-Rolle"}],
        education_json=[],
        skills_json=[],
    )
    db.add(existing)
    db.commit()
    db.close()

    parsed = ParsedCvProfile(full_name="Bestehender Nutzer", email="bestehend@example.com", experiences=[])

    response = _upload(test_client, mocker, parsed)

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["experiences_json"] == [{"company": "Alt GmbH", "role": "Alt-Rolle", "start_date": None, "end_date": None, "description": None}]
    assert "Keine Berufserfahrung gefunden - vorhandene Angaben blieben unverändert." in body["warnings"]
