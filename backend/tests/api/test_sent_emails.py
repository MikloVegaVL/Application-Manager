"""Tests für `GET /sent-emails` (U3 des Plans:
docs/plans/2026-09-14-001-feat-application-email-log-plan.md).

Nutzt eine eigene In-Memory-SQLite-Engine, gleiches Muster wie
`tests/api/test_applications.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

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
        attachment_filenames=["lebenslauf.pdf"],
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
            attachment_filenames=[],
        )
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["sender_email"] is None
    assert entry["subject"] is None
    assert entry["attachment_filenames"] == []


def test_entry_returns_all_attachment_filenames_not_just_the_cv(client, db_session_local) -> None:
    """Regression: the log records every attachment actually sent (CV plus
    extra profile attachments), so the API must expose the whole list."""
    session = db_session_local()
    try:
        _insert_sent_email(
            session,
            attachment_filenames=["lebenslauf.pdf", "zeugnis.pdf", "anschreiben.pdf"],
        )
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    assert response.json()[0]["attachment_filenames"] == [
        "lebenslauf.pdf",
        "zeugnis.pdf",
        "anschreiben.pdf",
    ]


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


def test_entry_with_existing_application_exposes_ad_url_for_link_through(
    client, db_session_local
) -> None:
    session = db_session_local()
    try:
        job_offer = JobOffer(
            title="Backend Engineer", company="Acme GmbH",
            source_url="https://example.com/job/x", source_platform="test",
        )
        session.add(job_offer)
        session.commit()
        session.refresh(job_offer)

        application = Application(job_offer_id=job_offer.id, status=ApplicationStatus.SENT)
        session.add(application)
        session.commit()
        session.refresh(application)

        _insert_sent_email(session, application_id=application.id)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["ad_url"] == "https://example.com/job/x"


def test_entry_with_deleted_application_returns_null_ad_url(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=None)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    assert response.json()[0]["ad_url"] is None


# --- outcome (U2, R3/R4) ------------------------------------------------


def _insert_sent_email_for_application_status(session, status: ApplicationStatus) -> None:
    # `source_url` is unique on `job_offers` - `uuid4` keeps this callable
    # safely more than once per test (e.g. one REJECTED + one ACCEPTED entry
    # in the same outcome-filter test).
    job_offer = JobOffer(
        title="Backend Engineer", company="Acme GmbH",
        source_url=f"https://example.com/job/{uuid4()}", source_platform="test",
    )
    session.add(job_offer)
    session.commit()
    session.refresh(job_offer)

    application = Application(job_offer_id=job_offer.id, status=status)
    session.add(application)
    session.commit()
    session.refresh(application)

    _insert_sent_email(session, application_id=application.id)


def test_entry_with_rejected_application_has_outcome_rejection(client, db_session_local) -> None:
    """Covers AE1."""
    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, ApplicationStatus.REJECTED)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    assert response.json()[0]["outcome"] == "rejection"


def test_entry_with_accepted_application_has_outcome_offer(client, db_session_local) -> None:
    """Covers AE2."""
    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, ApplicationStatus.ACCEPTED)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    assert response.json()[0]["outcome"] == "offer"


@pytest.mark.parametrize(
    "status", [ApplicationStatus.DRAFT, ApplicationStatus.SENT, ApplicationStatus.INTERVIEW]
)
def test_entry_with_undecided_application_has_outcome_pending(
    client, db_session_local, status
) -> None:
    """Covers AE3."""
    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, status)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    assert response.json()[0]["outcome"] == "pending"


def test_entry_with_deleted_application_has_outcome_pending(client, db_session_local) -> None:
    """Covers AE4."""
    session = db_session_local()
    try:
        _insert_sent_email(session, application_id=None)
    finally:
        session.close()

    response = client.get("/api/sent-emails")

    assert response.status_code == 200
    assert response.json()[0]["outcome"] == "pending"


# --- outcome filter (U3, R5) --------------------------------------------


def test_filter_by_invalid_outcome_value_returns_422(client) -> None:
    """Regression: `outcome` is typed `Literal["offer", "rejection", "pending"]`
    (review finding), so an unrecognized value must be rejected by FastAPI/
    Pydantic instead of silently falling into the "pending" branch."""
    response = client.get("/api/sent-emails", params={"outcome": "bogus"})

    assert response.status_code == 422


def test_filter_by_outcome_rejection_returns_only_rejected_entries(client, db_session_local) -> None:
    """Covers AE5."""
    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, ApplicationStatus.REJECTED)
        _insert_sent_email_for_application_status(session, ApplicationStatus.ACCEPTED)
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"outcome": "rejection"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["outcome"] == "rejection"


def test_filter_by_outcome_offer_returns_only_accepted_entries(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, ApplicationStatus.REJECTED)
        _insert_sent_email_for_application_status(session, ApplicationStatus.ACCEPTED)
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"outcome": "offer"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["outcome"] == "offer"


def test_filter_by_outcome_pending_returns_undecided_and_deleted_application_entries(
    client, db_session_local
) -> None:
    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, ApplicationStatus.SENT)
        _insert_sent_email(session, application_id=None)
        _insert_sent_email_for_application_status(session, ApplicationStatus.REJECTED)
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"outcome": "pending"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(entry["outcome"] == "pending" for entry in body)


def test_outcome_filter_combines_with_company_filter(client, db_session_local) -> None:
    session = db_session_local()
    try:
        _insert_sent_email(
            session, application_id=None, company="Acme GmbH", recipient_email="a@example.com"
        )
        job_offer = JobOffer(
            title="Backend Engineer", company="Globex",
            source_url="https://example.com/job/z", source_platform="test",
        )
        session.add(job_offer)
        session.commit()
        session.refresh(job_offer)
        application = Application(job_offer_id=job_offer.id, status=ApplicationStatus.REJECTED)
        session.add(application)
        session.commit()
        session.refresh(application)
        _insert_sent_email(
            session, application_id=application.id, company="Globex", recipient_email="b@example.com"
        )
    finally:
        session.close()

    response = client.get("/api/sent-emails", params={"outcome": "pending", "company": "Globex"})

    assert response.status_code == 200
    assert response.json() == []


def test_export_with_outcome_filter_returns_the_same_row_set_as_the_list(
    client, db_session_local
) -> None:
    """Covers KTD2: filter parity extends to `outcome`, even though the PDF
    itself never renders an Outcome column (R6)."""
    from io import BytesIO

    from pypdf import PdfReader

    session = db_session_local()
    try:
        _insert_sent_email_for_application_status(session, ApplicationStatus.REJECTED)
    finally:
        session.close()
    session2 = db_session_local()
    try:
        _insert_sent_email(session2, application_id=None, recipient_email="unfiltered@example.com")
    finally:
        session2.close()

    list_response = client.get("/api/sent-emails", params={"outcome": "rejection"})
    assert [entry["recipient_email"] for entry in list_response.json()] == ["recruiter@example.com"]

    export_response = client.get("/api/sent-emails/export", params={"outcome": "rejection"})

    assert export_response.status_code == 200
    reader = PdfReader(BytesIO(export_response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "recruiter@example.com" in text
    assert "unfiltered@example.com" not in text


# --- DELETE /sent-emails/{id} ------------------------------------------


def test_delete_sent_email_removes_it(client, db_session_local) -> None:
    session = db_session_local()
    try:
        entry_id = _insert_sent_email(session, application_id=None).id
    finally:
        session.close()

    response = client.delete(f"/api/sent-emails/{entry_id}")

    assert response.status_code == 204
    assert client.get("/api/sent-emails").json() == []


def test_delete_sent_email_returns_404_for_unknown_id(client) -> None:
    response = client.delete("/api/sent-emails/999")

    assert response.status_code == 404


def test_delete_sent_email_does_not_delete_the_linked_application(client, db_session_local) -> None:
    session = db_session_local()
    try:
        job_offer = JobOffer(
            title="Backend Engineer", company="Acme GmbH",
            source_url="https://example.com/job/y", source_platform="test",
        )
        session.add(job_offer)
        session.commit()
        session.refresh(job_offer)

        application = Application(job_offer_id=job_offer.id, status=ApplicationStatus.SENT)
        session.add(application)
        session.commit()
        session.refresh(application)
        application_id = application.id

        entry_id = _insert_sent_email(session, application_id=application_id).id
    finally:
        session.close()

    response = client.delete(f"/api/sent-emails/{entry_id}")

    assert response.status_code == 204
    assert client.get(f"/api/applications/{application_id}").status_code == 200


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
