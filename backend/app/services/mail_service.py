"""Service zum Versand von Bewerbungs-E-Mails inkl. PDF-Anhang via SMTP."""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


class MailSendError(Exception):
    """Wird ausgelöst, wenn der Mailversand fehlschlägt."""


@dataclass(frozen=True)
class _SmtpAccount:
    """Ein SMTP-Postfach-Account (Host/Zugangsdaten/Absender)."""

    host: str
    port: int
    username: str | None
    password: str | None
    use_ssl: bool  # implizites SSL (Port 465) - schließt STARTTLS aus
    use_tls: bool  # STARTTLS (nur relevant, wenn `use_ssl` False ist)
    from_email: str


def _account_for(sender_email: str | None) -> _SmtpAccount | None:
    """Wählt den SMTP-Account, der zur im Profil gewählten Absenderadresse
    passt (siehe `MasterProfile.sender_email`).

    Zwei feste Accounts sind konfiguriert (siehe `app.core.config`): der
    Primär-Account (`SMTP_*`, aktuell mail.de, STARTTLS auf Port 587) sowie
    ein zweiter Account (`SMTP2_*`, All-Inkl/KAS, implizites SSL auf Port
    465). Passt `sender_email` zu keinem der beiden `*_FROM_EMAIL`-Werte
    (z. B. weil noch kein Profil-Feld gesetzt ist), greift der Primär-Account
    als Fallback - identisch zum bisherigen Verhalten vor Einführung der
    Absender-Auswahl.
    """
    if sender_email and sender_email == settings.SMTP2_FROM_EMAIL and settings.SMTP2_HOST:
        return _SmtpAccount(
            host=settings.SMTP2_HOST,
            port=settings.SMTP2_PORT,
            username=settings.SMTP2_USERNAME,
            password=settings.SMTP2_PASSWORD,
            use_ssl=settings.SMTP2_USE_SSL,
            use_tls=False,
            from_email=settings.SMTP2_FROM_EMAIL,
        )
    if settings.SMTP_HOST and settings.SMTP_FROM_EMAIL:
        return _SmtpAccount(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            use_ssl=False,
            use_tls=settings.SMTP_USE_TLS,
            from_email=settings.SMTP_FROM_EMAIL,
        )
    return None


def send_application_email(
    to_email: str,
    subject: str,
    body_text: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    extra_attachments: list[tuple[bytes, str]] | None = None,
    from_email: str | None = None,
) -> str:
    """Versendet eine Bewerbungsmail inkl. PDF-Anhang via SMTP.

    `attachment_bytes`/`attachment_filename` ist der Lebenslauf (Pflicht-
    Anhang). `extra_attachments` sind die zusätzlichen, im Profil hochgeladenen
    PDF-Anhänge (siehe `ProfileAttachment`, `app.api.profile`) - jeweils
    `(bytes, filename)`, optional und auf `MAX_PROFILE_ATTACHMENTS` begrenzt
    (die Begrenzung erfolgt bereits beim Upload, nicht hier). `from_email` ist
    die im Profil gewählte Absenderadresse (`MasterProfile.sender_email`) -
    sie bestimmt über `_account_for`, welcher SMTP-Account tatsächlich zum
    Versand genutzt wird, nicht nur den sichtbaren From-Header: nur so landet
    die Mail im Sent-Ordner des passenden Postfachs, statt nur mit fremdem
    Absender-Header über einen anderen Account zu laufen.

    Nutzt je Account STARTTLS oder implizites SSL (siehe `_SmtpAccount`),
    sowie SMTP-Auth, falls Zugangsdaten konfiguriert sind.

    Gibt die tatsächlich genutzte Absenderadresse (`account.from_email`)
    zurück - kann von `from_email` abweichen, wenn `_account_for` auf den
    Primär-Account zurückfällt. Aufrufer (siehe `app.api.applications`)
    protokollieren damit den wirklich genutzten Account, nicht nur den
    angefragten (KTD2, docs/plans/2026-09-14-001-feat-application-email-log-
    plan.md).
    """
    account = _account_for(from_email)
    if account is None:
        raise MailSendError(
            "SMTP ist nicht konfiguriert (SMTP_HOST/SMTP_FROM_EMAIL fehlen in der .env) "
            "- Mailversand ist nicht verfügbar."
        )

    message = MIMEMultipart()
    message["From"] = account.from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body_text, "plain", "utf-8"))

    for attachment_data, filename in [(attachment_bytes, attachment_filename), *(extra_attachments or [])]:
        attachment = MIMEApplication(attachment_data, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(attachment)

    smtp_cls = smtplib.SMTP_SSL if account.use_ssl else smtplib.SMTP
    try:
        with smtp_cls(account.host, account.port, timeout=15) as server:
            server.ehlo()
            if account.use_tls:
                server.starttls()
                server.ehlo()
            if account.username and account.password:
                server.login(account.username, account.password)
            server.sendmail(account.from_email, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("SMTP-Mailversand fehlgeschlagen.")
        raise MailSendError(f"Mailversand fehlgeschlagen: {exc}") from exc

    logger.info("Bewerbungsmail erfolgreich an %s versendet.", to_email)
    return account.from_email
