"""add sent_to_email to applications

Revision ID: 7b2f5c9d1a34
Revises: 3cf25349329e
Create Date: 2026-09-11 00:00:00.000000+00:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7b2f5c9d1a34'
# Branches independently off 3cf25349329e, same as 17c15ce91b4e - do NOT
# rebase this onto 17c15ce91b4e; a real merge revision (d98463c22408) joins
# them instead. See that file for why (ce-debug, 2026-09-12).
down_revision: str | None = '3cf25349329e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'applications',
        sa.Column('sent_to_email', sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('applications', 'sent_to_email')
