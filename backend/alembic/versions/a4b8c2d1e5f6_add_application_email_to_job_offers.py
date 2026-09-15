"""add application_email to job_offers

Revision ID: a4b8c2d1e5f6
Revises: 5b1e9f7a2c3d
Create Date: 2026-09-15 00:00:00.000000+00:00

Persists the discovered application email and its source page on a saved
`JobOffer` so a later visit reuses it without re-scraping (R10/KTD5). Both
columns are nullable - a job with no discovered address keeps them `NULL`,
mirroring the nullable `location` column.

Parented on the current single head `5b1e9f7a2c3d`. Never rewrite an existing
revision's `down_revision` - a rebase silently strands already-migrated
databases (see docs/solutions/database-issues/
alembic-migration-rebase-silently-skips-sibling-branch.md).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b8c2d1e5f6'
down_revision: str | None = '5b1e9f7a2c3d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'job_offers',
        sa.Column('application_email', sa.String(length=320), nullable=True),
    )
    op.add_column(
        'job_offers',
        sa.Column('application_email_source_url', sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('job_offers', 'application_email_source_url')
    op.drop_column('job_offers', 'application_email')
