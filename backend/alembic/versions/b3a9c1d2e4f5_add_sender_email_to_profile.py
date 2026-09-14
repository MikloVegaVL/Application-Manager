"""add sender_email to profile

Revision ID: b3a9c1d2e4f5
Revises: f47e23403358
Create Date: 2026-09-14 00:00:00.000000+00:00

Adds `sender_email` to `MasterProfile` (see `ce-debug`, 2026-09-14): the
selectable "From" address used when sending an application email, treated
like `linkedin`/`website` - nullable, `PUT /profile`-only (see
`_IDENTITY_FIELDS` in `app.api.profile`).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3a9c1d2e4f5'
down_revision: str | None = 'f47e23403358'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "sender_email" not in existing_columns:
        op.add_column('master_profiles', sa.Column('sender_email', sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "sender_email" in existing_columns:
        op.drop_column('master_profiles', 'sender_email')
