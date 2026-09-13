"""add document_language to master_profiles

Revision ID: e2b7c9a41f60
Revises: c3d5e7f9a1b2
Create Date: 2026-09-13 00:00:00.000000+00:00

Adds the `document_language` preference used by the CV Builder to render the
generated CV's fixed chrome in German or English (see
docs/plans/2026-09-13-002-feat-cv-document-language-plan.md, U1). The column is
nullable: `None` means "no choice yet" and renders English, mirroring
`template_id`.

Parented on the current single head `c3d5e7f9a1b2`. Never rewrite an existing
revision's `down_revision` - a rebase silently strands already-migrated
databases (see docs/solutions/database-issues/
alembic-migration-rebase-silently-skips-sibling-branch.md).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7c9a41f60'
down_revision: str | None = 'c3d5e7f9a1b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "document_language" not in existing_columns:
        op.add_column(
            'master_profiles',
            sa.Column('document_language', sa.String(length=10), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "document_language" in existing_columns:
        op.drop_column('master_profiles', 'document_language')
