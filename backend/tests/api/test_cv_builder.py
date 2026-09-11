"""Tests für `POST /cv-builder/parse` (R5-R8, KTD1) - die reine
CV-Parse-Vorschau des Builders, Nachfolger des entfernten
`POST /profile/upload-cv` (siehe U3 des CV-Builder-Plans:
docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md).

Anders als das frühere `upload_cv` schreibt dieser Endpunkt NICHTS in die
Datenbank (R6) - jeder Test hier prüft daher ausschließlich die Antwort,
nie einen DB-Seiteneffekt."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registriert Modelle in Base.metadata
from app.db.database import Base, get_db
from app.main import app
from app.schemas.master_profile import ParsedCvProfile
from app.services.pdf_parser import CvAnalysisError, PdfParsingError


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
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _parse(test_client: TestClient, mocker, parsed: ParsedCvProfile | None = None, side_effect=None):
    mocker.patch(
        "app.api.cv_builder.parse_cv_pdf",
        return_value=parsed,
        side_effect=side_effect,
    )
    return test_client.post(
        "/api/cv-builder/parse",
        files={"file": ("cv.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )


def test_parse_cv_with_full_data_returns_no_warnings(client, mocker):
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
        projects=[{"title": "Portfolio-Website", "description": "Persönliche Portfolio-Seite."}],
    )

    response = _parse(client, mocker, parsed)

    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == []
    # Name/Kontakt sind reine Anzeigefelder (R5/KTD1) - hier nur geprüft,
    # dass sie im Parse-Ergebnis überhaupt vorkommen (Anzeige obliegt dem
    # Frontend-Formular, nicht diesem Endpunkt).
    assert body["parsed"]["full_name"] == "Max Mustermann"
    assert body["parsed"]["email"] == "max@example.com"
    assert len(body["parsed"]["experiences"]) == 1
    assert len(body["parsed"]["projects"]) == 1
    assert body["parsed"]["projects"][0]["title"] == "Portfolio-Website"


def test_parse_cv_with_no_identifiable_project_returns_empty_list_and_warning(client, mocker):
    parsed = ParsedCvProfile(
        full_name="Max Mustermann",
        email="max@example.com",
        experiences=[{"company": "Acme GmbH", "role": "Entwickler"}],
        education=[{"institution": "TU Berlin", "degree": "B.Sc. Informatik"}],
        summary="Erfahrener Entwickler.",
        skills=["Python"],
        projects=[],
    )

    response = _parse(client, mocker, parsed)

    assert response.status_code == 200
    body = response.json()
    assert body["parsed"]["projects"] == []
    assert "Keine Projekte gefunden." in body["warnings"]


def test_parse_cv_with_missing_experience_and_education_reports_warnings(client, mocker):
    parsed = ParsedCvProfile(
        full_name="Max Mustermann",
        email="max@example.com",
        experiences=[],
        education=[],
        skills=["Python"],
        projects=[],
    )

    response = _parse(client, mocker, parsed)

    assert response.status_code == 200
    body = response.json()
    assert "Keine Berufserfahrung gefunden." in body["warnings"]
    assert "Keine Ausbildung gefunden." in body["warnings"]
    assert "Kein Kurzprofil/Zusammenfassung gefunden." in body["warnings"]
    assert "Keine Projekte gefunden." in body["warnings"]
    # Skills wurden gefunden - dafür keine Warnung.
    assert "Keine Skills gefunden." not in body["warnings"]


def test_parse_cv_does_not_write_to_the_database(client, mocker):
    """R6: nichts wird gespeichert - auch nicht, wenn zuvor noch kein Profil
    existierte (anders als das frühere `upload_cv`, das in diesem Fall ein
    neues Profil anlegte)."""
    parsed = ParsedCvProfile(full_name="Max Mustermann", email="max@example.com")

    response = _parse(client, mocker, parsed)

    assert response.status_code == 200
    assert client.get("/api/profile").status_code == 404


def test_parse_cv_rejects_non_pdf_upload(client, mocker):
    mocker.patch("app.api.cv_builder.parse_cv_pdf")
    response = client.post(
        "/api/cv-builder/parse",
        files={"file": ("cv.docx", b"not a pdf", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_parse_cv_returns_422_on_unreadable_pdf(client, mocker):
    response = _parse(client, mocker, side_effect=PdfParsingError("kein Text extrahierbar"))

    assert response.status_code == 422


def test_parse_cv_returns_502_when_ai_unavailable(client, mocker):
    response = _parse(client, mocker, side_effect=CvAnalysisError("Ollama nicht erreichbar"))

    assert response.status_code == 502
