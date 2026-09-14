"""add source_platform to sent_emails

Revision ID: 5b1e9f7a2c3d
Revises: 40770d5086f1
Create Date: 2026-09-14 14:00:00.000000+00:00

Adds `source_platform` (job board the offer came from, e.g. "linkedin") as a
snapshot column, same treatment as `company`/`job_title` (see
`app.models.sent_email.SentEmail`) - stays readable even after the
`Application`/`JobOffer` it came from is deleted. Backfills existing rows via
a live join through `applications` -> `job_offers`, mirroring the backfill in
`40770d5086f1_add_sent_emails_table.py`.

Parented on the current single head `40770d5086f1`. Never rewrite an existing
revision's `down_revision` - a rebase silently strands already-migrated
databases (see docs/solutions/database-issues/
alembic-migration-rebase-silently-skips-sibling-branch.md).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b1e9f7a2c3d'
down_revision: str | None = '40770d5086f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("sent_emails")}

    if "source_platform" not in existing_columns:
        op.add_column(
            'sent_emails',
            sa.Column('source_platform', sa.String(length=100), nullable=True),
        )
        _backfill_source_platform(bind)


def _backfill_source_platform(bind: sa.engine.Connection) -> None:
    metadata = sa.MetaData()
    applications = sa.Table('applications', metadata, autoload_with=bind)
    job_offers = sa.Table('job_offers', metadata, autoload_with=bind)
    sent_emails = sa.Table('sent_emails', metadata, autoload_with=bind)

    query = (
        sa.select(sent_emails.c.id, job_offers.c.source_platform)
        .select_from(
            sent_emails.join(applications, sent_emails.c.application_id == applications.c.id).join(
                job_offers, applications.c.job_offer_id == job_offers.c.id
            )
        )
        .where(sent_emails.c.application_id.is_not(None))
    )

    for row in bind.execute(query):
        bind.execute(
            sa.update(sent_emails)
            .where(sent_emails.c.id == row.id)
            .values(source_platform=row.source_platform)
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("sent_emails")}

    if "source_platform" in existing_columns:
        op.drop_column('sent_emails', 'source_platform')
