"""add channel and nullable recipient to sent_emails

Revision ID: e4c9a1b2d3f6
Revises: f71a8d3d7876
Create Date: 2026-10-20 12:00:00.000000+00:00

The "Mark sent via website form" action (`ApplicationStatus.WEBFORM`) records a
`SentEmail` log entry so it appears in the Sent Emails overview - but a website
form submission has no actual email, so there is no recipient/sender/subject/
attachment. Two schema changes support that:

- `channel` ("email" | "webform") distinguishes a real mail send from a website
  form submission. Existing rows all represent email sends, so the column is
  added non-null with a `server_default` of "email" (dropped right after, so it
  doesn't diverge from the model's Python-side `default="email"` only - see the
  same guard in `c7f3a1b9d2e4`).
- `recipient_email` becomes nullable, since a website form submission has none.

Guarded-column style mirrors `c7f3a1b9d2e4` / `5b1e9f7a2c3d`, so a partially-
migrated database or a second `alembic upgrade head` run does not error.
Parented on the verified single head `f71a8d3d7876`; an existing revision's
`down_revision` is never rewritten.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4c9a1b2d3f6'
down_revision: str | None = 'f71a8d3d7876'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("sent_emails")}

    if "channel" not in existing_columns:
        # `server_default` only so the `ADD COLUMN nullable=False` statement has
        # a value for already-existing rows; dropped right after so it doesn't
        # diverge from the model (Python-side `default="email"` only).
        op.add_column(
            'sent_emails',
            sa.Column('channel', sa.String(length=20), nullable=False, server_default='email'),
        )
        with op.batch_alter_table('sent_emails') as batch_op:
            batch_op.alter_column('channel', server_default=None)

    with op.batch_alter_table('sent_emails') as batch_op:
        batch_op.alter_column(
            'recipient_email', existing_type=sa.String(length=320), nullable=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("sent_emails")}

    if "channel" in existing_columns:
        op.drop_column('sent_emails', 'channel')

    with op.batch_alter_table('sent_emails') as batch_op:
        batch_op.alter_column(
            'recipient_email', existing_type=sa.String(length=320), nullable=False
        )
