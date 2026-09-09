"""Service zum Versand von Bewerbungs-E-Mails inkl. PDF-Anhang via SMTP."""
from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


class MailSendError(Exception):
    """Wird ausgelöst, wenn der Mailversand fehlschlägt."""


def send_application_email(
    to_email: str,
    subject: str,
    body_text: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    extra_attachments: list[tuple[bytes, str]] | None = None,
) -> None:
    """Versendet eine Bewerbungsmail inkl. PDF-Anhang via SMTP.

    `attachment_bytes`/`attachment_filename` ist der Lebenslauf (Pflicht-
    Anhang). `extra_attachments` sind die zusätzlichen, im Profil hochgeladenen
    PDF-Anhänge (siehe `ProfileAttachment`, `app.api.profile`) - jeweils
    `(bytes, filename)`, optional und auf `MAX_PROFILE_ATTACHMENTS` begrenzt
    (die Begrenzung erfolgt bereits beim Upload, nicht hier).

    Nutzt STARTTLS, sofern `SMTP_USE_TLS` aktiv ist (Standard), sowie
    SMTP-Auth, falls Zugangsdaten konfiguriert sind.
    """
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise MailSendError(
            "SMTP ist nicht konfiguriert (SMTP_HOST/SMTP_FROM_EMAIL fehlen in der .env) "
            "- Mailversand ist nicht verfügbar."
        )

    message = MIMEMultipart()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body_text, "plain", "utf-8"))

    for attachment_data, filename in [(attachment_bytes, attachment_filename), *(extra_attachments or [])]:
        attachment = MIMEApplication(attachment_data, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(attachment)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.ehlo()
            if settings.SMTP_USE_TLS:
                server.starttls()
                server.ehlo()
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("SMTP-Mailversand fehlgeschlagen.")
        raise MailSendError(f"Mailversand fehlgeschlagen: {exc}") from exc

    logger.info("Bewerbungsmail erfolgreich an %s versendet.", to_email)
