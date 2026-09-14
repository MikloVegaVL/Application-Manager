"""Tests für `GET /sent-emails` (U3 des Plans:
docs/plans/2026-09-14-001-feat-application-email-log-plan.md).

Nutzt eine eigene In-Memory-SQLite-Engine, gleiches Muster wie
`tests/api/test_applications.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
from app.models.sent_email import SentEmail


@pytest.fixture
def db_session_local():
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


def _insert_sent_email(session, **overrides) -> SentEmail:
    defaults = dict(
        application_id=1,
        company="Acme GmbH",
        job_title="Backend Engineer",
        recipient_email="recruiter@example.com",
        sent_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        sender_email="absender@example.com",
        subject="Bewerbung",
        attachment_filename="lebenslauf.pdf",
    )
    defaults.update(overrides)
    entry = SentEmail(**defaults)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def test_list_with_no_filters_returns_all_entries_most_recent_first(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(
            session, application_id=1, recipient_email="a@example.com",
            sent_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        _insert_sent_email(
            session, application_id=2, recipient_email="b@example.com",
            sent_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    body = response.json()
    assert [entry["recipient_email"] for entry in body] == ["b@example.com", "a@example.com"]


def test_filter_by_company_returns_only_matching_entries(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, company="Acme GmbH")
        _insert_sent_email(session, application_id=2, company="Globex")
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"company": "Globex"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["company"] == "Globex"


def test_filter_by_company_matches_case_insensitive_substring(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, company="Acme GmbH")
        _insert_sent_email(session, application_id=2, company="Globex")
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"company": "acme"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["company"] == "Acme GmbH"


def test_filter_by_sender_email_returns_only_matching_entries(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, sender_email="primary@example.com")
        _insert_sent_email(session, application_id=2, sender_email="secondary@example.com")
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"sender_email": "secondary@example.com"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["sender_email"] == "secondary@example.com"


def test_filter_by_date_range_returns_only_entries_in_range(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, sent_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        _insert_sent_email(session, application_id=2, sent_at=datetime(2026, 9, 5, tzinfo=timezone.utc))
        _insert_sent_email(session, application_id=3, sent_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    finally:
        session.close()

    response = client.get(
        "/api/sent-emails", params={"date_from": "2026-09-01", "date_to": "2026-09-30"}
    )

    body = response.json()
    assert len(body) == 1
    assert body[0]["application_id"] == 2


def test_combining_company_and_date_range_returns_only_matching_entries(client, db_session_local) -> None:
    """Covers AE3."""
    session = db_session_local()
    try:
        _insert_sent_email(
            session, application_id=1, company="Acme GmbH",
            sent_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        _insert_sent_email(
            session, application_id=2, company="Acme GmbH",
            sent_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        _insert_sent_email(
            session, application_id=3, company="Globex",
            sent_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
    finally:
        session.close()

    response = client.get(
        "/api/sent-emails",
        params={"company": "Acme GmbH", "date_from": "2026-09-01", "date_to": "2026-09-30"},
    )

    body = response.json()
    assert len(body) == 1
    assert body[0]["application_id"] == 1


def test_backfilled_entry_returns_null_fields_not_omitted_or_erroring(client, db_session_local) -> None:
    """Covers AE5."""
    session = db_session_local()
    try:
        _insert_sent_email(
            session,
            application_id=1,
            sender_email=None,
            subject=None,
            attachment_filename=None,
        )
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["sender_email"] is None
    assert entry["subject"] is None
    assert entry["attachment_filename"] is None


def test_entry_with_deleted_application_is_still_returned_with_snapshot_intact(
    client, db_session_local
) -> None:
    """Covers KTD7."""
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=None, company="Acme GmbH", job_title="Backend Engineer")
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["application_id"] is None
    assert entry["company"] == "Acme GmbH"
    assert entry["job_title"] == "Backend Engineer"


def test_entry_with_existing_application_exposes_job_offer_id_for_link_through(
    client, db_session_local
) -> None:
    """R5: the frontend needs job_offer_id to link to /editor/:jobOfferId."""
    session = db_session_local()
    try:
        job_offer = JobOffer(
            title="Backend Engineer", company="Acme GmbH",
            source_url="https://example.com/job/x", source_platform="test",
        )
        session.add(job_offer)
        session.commit()
        session.refresh(job_offer)
        job_offer_id = job_offer.id

        application = Application(job_offer_id=job_offer_id, status=ApplicationStatus.SENT)
        session.add(application)
        session.commit()
        session.refresh(application)

        _insert_sent_email(session, application_id=application.id)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["job_offer_id"] == job_offer_id


# --- PDF export endpoints (U4) ----------------------------------------


def test_export_with_no_filters_returns_a_pdf_with_every_entry(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, recipient_email="a@example.com")
        _insert_sent_email(session, application_id=2, recipient_email="b@example.com")
    finally:
        session.close()

    response = client.get("/api/sent-emails/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_export_with_company_filter_returns_a_pdf_with_only_that_companys_entries(
    client, db_session_local
) -> None:
    """Covers AE4."""
    from io import BytesIO

    from pypdf import PdfReader

    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, company="Acme GmbH", recipient_email="a@example.com")
        _insert_sent_email(session, application_id=2, company="Globex", recipient_email="b@example.com")
    finally:
        session.close()

    response = client.get("/api/sent-emails/export", params={"company": "Acme GmbH"})

    assert response.status_code == 200
    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "a@example.com" in text
    assert "b@example.com" not in text


def test_export_all_ignores_active_filter_params_and_returns_every_entry(
    client, db_session_local
) -> None:
    """Covers AE4: /export/all must return every entry even when a filter
    param that would narrow GET /sent-emails is also supplied."""
    from io import BytesIO

    from pypdf import PdfReader

    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=1, company="Acme GmbH", recipient_email="a@example.com")
        _insert_sent_email(session, application_id=2, company="Globex", recipient_email="b@example.com")
    finally:
        session.close()

    response = client.get("/api/sent-emails/export/all", params={"company": "Acme GmbH"})

    assert response.status_code == 200
    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "a@example.com" in text
    assert "b@example.com" in text
