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
from app.api import cv_builder as cv_builder_module
from app.db.database import Base, get_db
from app.main import app
from app.models.master_profile import MasterProfile
from app.schemas.master_profile import ParsedCvProfile
from app.services import pdf_service
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


@pytest.fixture
def client_with_session():
    """Wie `client`, liefert zusätzlich die Session-Factory zurück, damit
    Tests (siehe Preview/Export unten) direkt ein `MasterProfile` anlegen
    können, ohne den Umweg über `PUT /api/profile`."""
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


def _create_profile(session_local, **overrides) -> MasterProfile:
    db = session_local()
    defaults = dict(full_name="Max Mustermann", email="max@example.com")
    defaults.update(overrides)
    profile = MasterProfile(**defaults)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    db.close()
    return profile


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


# --- GET /cv-builder/templates --------------------------------------------
#
# R9: kleine, feste Auswahl wählbarer visueller CV-Vorlagen.


def test_list_templates_returns_the_configured_template_ids(client):
    response = client.get("/api/cv-builder/templates")

    assert response.status_code == 200
    body = response.json()
    ids = {template["id"] for template in body}
    assert ids == {"classic", "modern"}
    assert all("label" in template for template in body)


# --- POST /cv-builder/preview & /export -----------------------------------
#
# R10/R11, KTD7, KTD11: dieselbe Rendering-Pipeline für Vorschau und Export,
# Identitätsfelder werden serverseitig aus dem gespeicherten Profil gemergt,
# nicht aus dem Request-Body gelesen.

_RENDER_PAYLOAD = {
    "template_id": "classic",
    "summary": "Erfahrener Entwickler.",
    "experiences_json": [
        {"company": "Acme GmbH", "role": "Entwickler", "start_date": "2020", "end_date": None}
    ],
    "education_json": [{"institution": "TU Berlin", "degree": "B.Sc. Informatik"}],
    "skills_json": [{"name": "Python", "level": "Experte"}],
    "languages_json": [{"name": "Deutsch", "level": "C2"}],
    "projects_json": [{"title": "Portfolio", "description": "Persönliche Seite."}],
}


def test_preview_requires_existing_profile(client_with_session):
    test_client, _ = client_with_session

    response = test_client.post("/api/cv-builder/preview", json=_RENDER_PAYLOAD)

    assert response.status_code == 404


def test_export_requires_existing_profile(client_with_session):
    test_client, _ = client_with_session

    response = test_client.post("/api/cv-builder/export", json=_RENDER_PAYLOAD)

    assert response.status_code == 404


def test_preview_returns_inline_pdf_with_merged_identity(client_with_session, mocker):
    test_client, session_local = client_with_session
    _create_profile(
        session_local,
        full_name="Max Mustermann",
        email="max@example.com",
        phone="0176 123456",
        address="Musterstraße 1, Berlin",
    )
    render_spy = mocker.spy(cv_builder_module, "render_cv_pdf")

    response = test_client.post("/api/cv-builder/preview", json=_RENDER_PAYLOAD)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    # Identitätsfelder kommen aus dem gespeicherten Profil, nicht aus dem
    # Request-Body (der Payload enthält gar keine Identitätsfelder).
    assert render_spy.call_args.kwargs["full_name"] == "Max Mustermann"
    assert render_spy.call_args.kwargs["email"] == "max@example.com"
    assert render_spy.call_args.kwargs["phone"] == "0176 123456"
    assert render_spy.call_args.kwargs["address"] == "Musterstraße 1, Berlin"


def test_export_returns_attachment_disposition_with_sanitized_filename(client_with_session):
    test_client, session_local = client_with_session
    _create_profile(session_local, full_name="Max Müller/Mustermann", email="max@example.com")

    response = test_client.post("/api/cv-builder/export", json=_RENDER_PAYLOAD)

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "Max_M_ller_Mustermann" in disposition
    assert "/" not in disposition.split("filename=")[1]
    assert response.content.startswith(b"%PDF")


def test_preview_and_export_use_the_same_rendering_pipeline(client_with_session, mocker):
    """KTD7: Preview liefert dieselben PDF-Bytes, die der Export für denselben
    Inhalt erzeugen würde (eine WeasyPrint-Pipeline für beide)."""
    test_client, session_local = client_with_session
    _create_profile(session_local)
    mocker.patch.object(pdf_service, "HTML").return_value.write_pdf.return_value = b"%PDF-1.4 identical bytes"

    preview_response = test_client.post("/api/cv-builder/preview", json=_RENDER_PAYLOAD)
    export_response = test_client.post("/api/cv-builder/export", json=_RENDER_PAYLOAD)

    assert preview_response.content == export_response.content == b"%PDF-1.4 identical bytes"


def test_render_rejects_unknown_template_id(client_with_session):
    test_client, session_local = client_with_session
    _create_profile(session_local)
    payload = {**_RENDER_PAYLOAD, "template_id": "does-not-exist"}

    response = test_client.post("/api/cv-builder/preview", json=payload)

    assert response.status_code == 422


def test_render_surfaces_pdf_render_error_as_http_error(client_with_session, mocker):
    test_client, session_local = client_with_session
    _create_profile(session_local)
    mocker.patch.object(
        pdf_service, "HTML"
    ).return_value.write_pdf.side_effect = RuntimeError("boom")

    response = test_client.post("/api/cv-builder/preview", json=_RENDER_PAYLOAD)

    assert response.status_code == 500
