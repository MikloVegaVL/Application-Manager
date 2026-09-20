"""add action_needed_detail to applications

Revision ID: 9c1d2e3f4a5b
Revises: a41edaf603a3
Create Date: 2026-09-20 10:00:00.000000+00:00

Adds the nullable `applications.action_needed_detail` column (`String(80)`)
U7/R9 needs to carry the concrete field/question label of a pause. Uses the
same inspector-guard pattern as `a41edaf603a3_add_portal_automation_state.py`
so a partially-migrated database does not error on re-run.

Parented on the current single head `a41edaf603a3`. Never rewrite an existing
revision's `down_revision` - a rebase silently strands already-migrated
databases (see docs/solutions/database-issues/
alembic-migration-rebase-silently-skips-sibling-branch.md).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c1d2e3f4a5b'
down_revision: str | None = 'a41edaf603a3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}

    if "action_needed_detail" not in existing_columns:
        op.add_column(
            'applications', sa.Column('action_needed_detail', sa.String(length=80), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}

    if "action_needed_detail" in existing_columns:
        op.drop_column('applications', 'action_needed_detail')
