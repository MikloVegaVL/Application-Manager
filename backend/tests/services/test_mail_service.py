"""Tests für `app.services.mail_service.send_application_email`s Rückgabewert
(U2 des Plans: docs/plans/2026-09-14-001-feat-application-email-log-plan.md,
KTD2) - der tatsächlich genutzte SMTP-Account muss zurückgegeben werden,
nicht nur die angefragte Absenderadresse, da beide bei einem Fallback auf
den Primär-Account voneinander abweichen können."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services.mail_service import MailSendError, send_application_email


@pytest.fixture(autouse=True)
def _smtp_accounts(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.primary.example")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USERNAME", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "primary@example.com")
    monkeypatch.setattr(settings, "SMTP2_HOST", "smtp.secondary.example")
    monkeypatch.setattr(settings, "SMTP2_PORT", 465)
    monkeypatch.setattr(settings, "SMTP2_USERNAME", None)
    monkeypatch.setattr(settings, "SMTP2_PASSWORD", None)
    monkeypatch.setattr(settings, "SMTP2_USE_SSL", True)
    monkeypatch.setattr(settings, "SMTP2_FROM_EMAIL", "secondary@example.com")


def _mock_smtp_cls(monkeypatch, target: str) -> MagicMock:
    server = MagicMock()
    server.__enter__.return_value = server
    smtp_cls = MagicMock(return_value=server)
    monkeypatch.setattr(f"app.services.mail_service.smtplib.{target}", smtp_cls)
    return smtp_cls


def _send(**overrides) -> str:
    kwargs = dict(
        to_email="recruiter@example.com",
        subject="Bewerbung",
        body_text="Text",
        attachment_bytes=b"%PDF-1.4",
        attachment_filename="cv.pdf",
    )
    kwargs.update(overrides)
    return send_application_email(**kwargs)


def test_send_returns_requested_primary_accounts_from_email(monkeypatch) -> None:
    _mock_smtp_cls(monkeypatch, "SMTP")

    result = _send(from_email="primary@example.com")

    assert result == "primary@example.com"


def test_send_falls_back_to_primary_account_and_returns_its_from_email(monkeypatch) -> None:
    """`from_email` passt zu keinem konfigurierten Account -> `_account_for`
    fällt auf den Primär-Account zurück; die Rückgabe muss dessen
    `from_email` sein, nicht die angefragte (unbekannte) Adresse."""
    _mock_smtp_cls(monkeypatch, "SMTP")

    result = _send(from_email="unknown@example.com")

    assert result == "primary@example.com"


def test_send_returns_secondary_accounts_from_email_when_selected(monkeypatch) -> None:
    _mock_smtp_cls(monkeypatch, "SMTP_SSL")

    result = _send(from_email="secondary@example.com")

    assert result == "secondary@example.com"


def test_send_raises_when_no_account_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", None)
    monkeypatch.setattr(settings, "SMTP2_HOST", None)
    monkeypatch.setattr(settings, "SMTP2_FROM_EMAIL", None)

    with pytest.raises(MailSendError):
        _send(from_email=None)


def test_send_raises_on_smtp_failure_without_a_return_value(monkeypatch) -> None:
    import smtplib

    smtp_cls = _mock_smtp_cls(monkeypatch, "SMTP")
    smtp_cls.return_value.__enter__.side_effect = smtplib.SMTPException("boom")

    with pytest.raises(MailSendError):
        _send(from_email="primary@example.com")


def test_send_uses_correct_content_type_for_image_and_doc_attachments(monkeypatch) -> None:
    """Zusätzliche Anhänge (seit der Erweiterung um JPEG/PNG/DOC/DOCX) müssen
    mit ihrem echten Media-Type angehängt werden, nicht pauschal als
    `application/pdf` - sonst würden Bild-/Word-Anhänge bei manchen
    Mail-Clients nicht korrekt angezeigt."""
    smtp_cls = _mock_smtp_cls(monkeypatch, "SMTP")

    _send(
        extra_attachments=[
            (b"\xff\xd8\xff fake-jpeg", "foto.jpg"),
            (b"\x89PNG fake-png", "scan.png"),
            (b"fake-doc", "zeugnis.doc"),
            (b"fake-docx", "zeugnis.docx"),
        ],
    )

    server = smtp_cls.return_value.__enter__.return_value
    raw_message = server.sendmail.call_args[0][2]

    # Der Lebenslauf bleibt PDF, die zusätzlichen Anhänge tragen ihren echten Typ.
    assert "application/pdf" in raw_message
    assert "image/jpeg" in raw_message
    assert "image/png" in raw_message
    assert "application/msword" in raw_message
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in raw_message
