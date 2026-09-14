"""add sent_emails table

Revision ID: 40770d5086f1
Revises: b3a9c1d2e4f5
Create Date: 2026-09-14 12:19:26.334678+00:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40770d5086f1'
down_revision: str | None = 'b3a9c1d2e4f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'sent_emails',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('company', sa.String(length=255), nullable=True),
        sa.Column('job_title', sa.String(length=255), nullable=True),
        sa.Column('recipient_email', sa.String(length=320), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sender_email', sa.String(length=320), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('attachment_filename', sa.String(length=255), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sent_emails_id'), 'sent_emails', ['id'], unique=False)
    op.create_index(
        op.f('ix_sent_emails_application_id'), 'sent_emails', ['application_id'], unique=False
    )
    op.create_index(op.f('ix_sent_emails_sent_at'), 'sent_emails', ['sent_at'], unique=False)

    _backfill_already_sent_applications(op.get_bind())


def _backfill_already_sent_applications(bind: sa.engine.Connection) -> None:
    """Ein `SentEmail`-Log-Eintrag pro bereits vor diesem Feature versendeter
    `Application`, aus deren `sent_at`/`sent_to_email`; `subject`/
    `sender_email`/`attachment_filename` bleiben `NULL` ("unknown" in UI/PDF),
    da für Altbestand nie erfasst (siehe R10, docs/plans/2026-09-14-001-feat-
    application-email-log-plan.md).

    Filtert auf `sent_at IS NOT NULL` statt `status = 'sent'` (Review-Fund):
    `PUT /applications/{id}` lässt den Status danach frei auf
    `accepted`/`rejected`/`interview` weiterschalten, ohne `sent_at`/
    `sent_to_email` zu löschen - eine Filterung auf den *aktuellen* Status
    hätte genau die Applications übersprungen, die die Nutzerin über den
    normalen Workflow (Bewerbung -> Ergebnis) längst weitergeschaltet hat,
    obwohl sie tatsächlich versendet wurden. Die zusätzliche
    `sent_to_email IS NOT NULL`-Bedingung schützt vor einem `NOT NULL`-
    Constraint-Fehler, falls (z. B. über dasselbe PUT) `sent_at` gesetzt,
    `sent_to_email` aber nie gepflegt wurde - eine solche Zeile wird beim
    Backfill übersprungen statt die ganze Migration abzubrechen.

    Der `already_logged`-Guard verhindert Duplikate bei erneutem `upgrade`
    (z. B. nach einem zuvor abgebrochenen Lauf) - ohne ihn würde ein zweiter
    Durchlauf pro Application einen weiteren Log-Eintrag anlegen.
    """
    metadata = sa.MetaData()
    applications = sa.Table('applications', metadata, autoload_with=bind)
    job_offers = sa.Table('job_offers', metadata, autoload_with=bind)
    sent_emails = sa.Table('sent_emails', metadata, autoload_with=bind)

    already_logged = {
        row[0]
        for row in bind.execute(sa.select(sent_emails.c.application_id))
        if row[0] is not None
    }

    query = (
        sa.select(
            applications.c.id,
            applications.c.sent_at,
            applications.c.sent_to_email,
            job_offers.c.company,
            job_offers.c.title,
        )
        .select_from(
            applications.join(job_offers, applications.c.job_offer_id == job_offers.c.id)
        )
        .where(
            applications.c.sent_at.is_not(None),
            applications.c.sent_to_email.is_not(None),
        )
    )

    rows_to_insert = [
        {
            'application_id': row.id,
            'company': row.company,
            'job_title': row.title,
            'recipient_email': row.sent_to_email,
            'sent_at': row.sent_at,
        }
        for row in bind.execute(query)
        if row.id not in already_logged
    ]
    if rows_to_insert:
        bind.execute(sa.insert(sent_emails), rows_to_insert)


def downgrade() -> None:
    op.drop_index(op.f('ix_sent_emails_sent_at'), table_name='sent_emails')
    op.drop_index(op.f('ix_sent_emails_application_id'), table_name='sent_emails')
    op.drop_index(op.f('ix_sent_emails_id'), table_name='sent_emails')
    op.drop_table('sent_emails')
