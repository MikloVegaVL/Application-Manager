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


# --- POST/GET/DELETE /profile/cv-file -----------------------------------
#
# Die Lebenslauf-Anhang-Datei ist unabhängig vom KI-gestützten CV-Import
# (`upload-cv`, oben): sie wird nicht analysiert, sondern unverändert als
# E-Mail-Anhang verwendet (siehe `app.api.applications.send_application`).


def _create_profile(session_local) -> MasterProfile:
    db = session_local()
    profile = MasterProfile(full_name="Max Mustermann", email="max@example.com")
    db.add(profile)
    db.commit()
    db.refresh(profile)
    db.close()
    return profile


def test_upload_cv_file_requires_existing_profile(client, tmp_path, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))

    response = test_client.post(
        "/api/profile/cv-file",
        files={"file": ("lebenslauf.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 404


def test_upload_cv_file_rejects_non_pdf(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = test_client.post(
        "/api/profile/cv-file",
        files={"file": ("lebenslauf.docx", b"not a pdf", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_upload_cv_file_stores_file_and_sets_filename(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = test_client.post(
        "/api/profile/cv-file",
        files={"file": ("mein-lebenslauf.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cv_filename"] == "mein-lebenslauf.pdf"

    download_response = test_client.get("/api/profile/cv-file")
    assert download_response.status_code == 200
    assert download_response.content == b"%PDF-1.4 fake content"
    assert 'filename="mein-lebenslauf.pdf"' in download_response.headers["content-disposition"]


def test_download_cv_file_returns_404_when_none_uploaded(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = test_client.get("/api/profile/cv-file")

    assert response.status_code == 404


def test_delete_cv_file_clears_it(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)
    test_client.post(
        "/api/profile/cv-file",
        files={"file": ("lebenslauf.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    response = test_client.delete("/api/profile/cv-file")

    assert response.status_code == 200
    assert response.json()["cv_filename"] is None
    assert test_client.get("/api/profile/cv-file").status_code == 404


# --- POST/GET/DELETE /profile/attachments -------------------------------
#
# Zusätzliche PDF-Anhänge (max. 3, siehe `MAX_PROFILE_ATTACHMENTS` in
# `app.api.profile`) - unabhängig vom Lebenslauf-Anhang oben, werden beim
# Versand zusätzlich zum Lebenslauf mitgeschickt, nicht anstelle davon.


def _upload_attachment(test_client: TestClient, filename: str = "zeugnis.pdf"):
    return test_client.post(
        "/api/profile/attachments",
        files={"file": (filename, b"%PDF-1.4 fake content", "application/pdf")},
    )


def test_upload_attachment_requires_existing_profile(client, tmp_path, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))

    response = _upload_attachment(test_client)

    assert response.status_code == 404


def test_upload_attachment_rejects_non_pdf(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = test_client.post(
        "/api/profile/attachments",
        files={"file": ("zeugnis.docx", b"not a pdf", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_upload_attachment_stores_file_and_lists_it(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = _upload_attachment(test_client, filename="zeugnis.pdf")

    assert response.status_code == 200
    attachments = response.json()["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "zeugnis.pdf"

    attachment_id = attachments[0]["id"]
    download_response = test_client.get(f"/api/profile/attachments/{attachment_id}")
    assert download_response.status_code == 200
    assert download_response.content == b"%PDF-1.4 fake content"
    assert 'filename="zeugnis.pdf"' in download_response.headers["content-disposition"]


def test_upload_attachment_rejects_a_fourth_file(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    for index in range(3):
        assert _upload_attachment(test_client, filename=f"anhang-{index}.pdf").status_code == 200

    response = _upload_attachment(test_client, filename="anhang-4.pdf")

    assert response.status_code == 400
    assert "maximal 3" in response.json()["detail"]


def test_delete_attachment_removes_it_and_frees_up_a_slot(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    for index in range(3):
        assert _upload_attachment(test_client, filename=f"anhang-{index}.pdf").status_code == 200

    profile_attachments = test_client.get("/api/profile").json()["attachments"]
    delete_response = test_client.delete(f"/api/profile/attachments/{profile_attachments[0]['id']}")

    assert delete_response.status_code == 200
    remaining = delete_response.json()["attachments"]
    assert len(remaining) == 2

    # Nach dem Löschen ist wieder ein Slot frei.
    assert _upload_attachment(test_client, filename="ersatz.pdf").status_code == 200


def test_download_attachment_returns_404_when_missing(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = test_client.get("/api/profile/attachments/999")

    assert response.status_code == 404


# --- POST/GET/DELETE /profile/photo -------------------------------------
#
# Profilfoto für den CV-Builder (R3, KTD4) - mirrors `cv-file` oben, nur mit
# Bild- statt PDF-Validierung inkl. Magic-Byte-Prüfung.

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 20  # gültiger JPEG-Header
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20  # gültiger PNG-Header


def test_upload_photo_valid_jpeg_stores_file(client, tmp_path, monkeypatch):
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    profile = _create_profile(session_local)

    response = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["photo_filename"] == "foto.jpg"

    expected_path = profile_dir / f"photo_{profile.id}.jpg"
    assert expected_path.exists()
    assert expected_path.read_bytes() == _JPEG_BYTES


def test_upload_photo_valid_png_stores_file(client, tmp_path, monkeypatch):
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    profile = _create_profile(session_local)

    response = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.png", _PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    expected_path = profile_dir / f"photo_{profile.id}.png"
    assert expected_path.exists()
    assert expected_path.read_bytes() == _PNG_BYTES


def test_upload_photo_requires_existing_profile(client, tmp_path, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))

    response = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    assert response.status_code == 404


def test_upload_photo_rejects_non_image_content_type(client, tmp_path, monkeypatch):
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    profile = _create_profile(session_local)

    response = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 422
    assert not (profile_dir / f"photo_{profile.id}.pdf").exists()


def test_upload_photo_rejects_content_mismatching_declared_type(client, tmp_path, monkeypatch):
    """A file whose bytes don't match its claimed Content-Type must be
    rejected - the magic-byte check exists precisely so a mislabeled header
    doesn't slip through (KTD4)."""
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    profile = _create_profile(session_local)

    response = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", b"this is not actually a jpeg", "image/jpeg")},
    )

    assert response.status_code == 422
    assert not (profile_dir / f"photo_{profile.id}.jpg").exists()
    assert test_client.get("/api/profile").json()["photo_filename"] is None


def test_upload_photo_rejects_oversized_file(client, tmp_path, monkeypatch):
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    _create_profile(session_local)

    oversized = _JPEG_BYTES + b"\x00" * (5 * 1024 * 1024)  # > 5 MB

    response = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", oversized, "image/jpeg")},
    )

    assert response.status_code == 422


def test_upload_photo_reupload_in_different_format_removes_old_file(client, tmp_path, monkeypatch):
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    profile = _create_profile(session_local)

    first = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", _JPEG_BYTES, "image/jpeg")},
    )
    assert first.status_code == 200
    jpg_path = profile_dir / f"photo_{profile.id}.jpg"
    assert jpg_path.exists()

    second = test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.png", _PNG_BYTES, "image/png")},
    )
    assert second.status_code == 200

    png_path = profile_dir / f"photo_{profile.id}.png"
    assert png_path.exists()
    assert not jpg_path.exists()


def test_download_photo_returns_404_when_none_uploaded(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)

    response = test_client.get("/api/profile/photo")

    assert response.status_code == 404


def test_download_photo_returns_stored_file(client, tmp_path, monkeypatch):
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)
    test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    response = test_client.get("/api/profile/photo")

    assert response.status_code == 200
    assert response.content == _JPEG_BYTES
    assert response.headers["content-type"] == "image/jpeg"
    assert 'filename="foto.jpg"' in response.headers["content-disposition"]


def test_delete_photo_clears_it(client, tmp_path, monkeypatch):
    test_client, session_local = client
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(profile_dir))
    profile = _create_profile(session_local)
    test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    response = test_client.delete("/api/profile/photo")

    assert response.status_code == 200
    assert response.json()["photo_filename"] is None
    assert not (profile_dir / f"photo_{profile.id}.jpg").exists()
    assert test_client.get("/api/profile/photo").status_code == 404


def test_delete_photo_twice_matches_cv_file_delete_behavior(client, tmp_path, monkeypatch):
    """A repeat DELETE with no photo present must behave exactly like the
    existing `cv-file` DELETE endpoint's "already deleted" case (404, not a
    silent no-op 200) - see KTD4."""
    test_client, session_local = client
    monkeypatch.setattr("app.core.config.settings.PROFILE_FILES_DIR", str(tmp_path / "profile"))
    _create_profile(session_local)
    test_client.post(
        "/api/profile/photo",
        files={"file": ("foto.jpg", _JPEG_BYTES, "image/jpeg")},
    )

    first_delete = test_client.delete("/api/profile/photo")
    second_delete = test_client.delete("/api/profile/photo")

    assert first_delete.status_code == 200
    assert second_delete.status_code == 404
