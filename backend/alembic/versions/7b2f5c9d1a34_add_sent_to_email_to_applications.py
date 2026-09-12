"""add sent_to_email to applications

Revision ID: 7b2f5c9d1a34
Revises: 17c15ce91b4e
Create Date: 2026-09-11 00:00:00.000000+00:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7b2f5c9d1a34'
# Rebased onto 17c15ce91b4e (add cv builder fields) instead of a merge
# revision: both migrations branched independently off 3cf25349329e when
# feat/cv-builder-editor and develop diverged, and a real alembic-merge node
# there makes `alembic downgrade -1` ambiguous (two parents) - see
# test_migration_upgrade_downgrade_upgrade_round_trips. A linear chain avoids
# that entirely; the two migrations don't touch overlapping tables/columns.
down_revision: str | None = '17c15ce91b4e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'applications',
        sa.Column('sent_to_email', sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('applications', 'sent_to_email')
