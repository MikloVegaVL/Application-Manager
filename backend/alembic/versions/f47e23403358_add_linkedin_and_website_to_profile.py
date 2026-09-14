"""add linkedin and website to profile

Revision ID: f47e23403358
Revises: 581736b96da4
Create Date: 2026-09-14 00:00:00.000000+00:00

Adds `linkedin`/`website` to `MasterProfile` (see `ce-debug`, 2026-09-14):
two more contact channels for the CV header, treated exactly like the
existing `phone`/`address` identity fields (nullable, `PUT /profile`-only -
see `_IDENTITY_FIELDS` in `app.api.profile`).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f47e23403358'
down_revision: str | None = '581736b96da4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "linkedin" not in existing_columns:
        op.add_column('master_profiles', sa.Column('linkedin', sa.String(length=255), nullable=True))
    if "website" not in existing_columns:
        op.add_column('master_profiles', sa.Column('website', sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "website" in existing_columns:
        op.drop_column('master_profiles', 'website')
    if "linkedin" in existing_columns:
        op.drop_column('master_profiles', 'linkedin')
