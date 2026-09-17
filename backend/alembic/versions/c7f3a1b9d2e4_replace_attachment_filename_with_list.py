"""replace sent_emails.attachment_filename with attachment_filenames

Revision ID: c7f3a1b9d2e4
Revises: a4b8c2d1e5f6
Create Date: 2026-09-15 14:00:00.000000+00:00

The sent-emails log used to persist only the CV filename
(`attachment_filename`), while `send_application_email` actually sends the CV
plus the profile's extra attachments (see
`app.services.mail_service`). Replace the single column with
`attachment_filenames` (JSON list, CV first) so the log records every
attachment that was really sent. Existing rows are backfilled with their old
single value as a one-element list; rows where it was `NULL` (pre-feature
backfill) stay an empty list.

Parented on the current single head `a4b8c2d1e5f6`. Never rewrite an existing
revision's `down_revision` - a rebase silently strands already-migrated
databases (see docs/solutions/database-issues/
alembic-migration-rebase-silently-skips-sibling-branch.md).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f3a1b9d2e4'
down_revision: str | None = 'a4b8c2d1e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("sent_emails")}

    if "attachment_filenames" not in existing_columns:
        # `server_default` only so the `ADD COLUMN nullable=False` statement
        # has a value for already-existing rows; dropped right after so it
        # doesn't diverge from the model (Python-side `default=list` only -
        # `tests/test_migrations.py` fails on exactly such a mismatch).
        op.add_column(
            'sent_emails',
            sa.Column('attachment_filenames', sa.JSON(), nullable=False, server_default='[]'),
        )
        _backfill_attachment_filenames(bind)
        with op.batch_alter_table('sent_emails') as batch_op:
            batch_op.alter_column('attachment_filenames', server_default=None)

    if "attachment_filename" in existing_columns:
        op.drop_column('sent_emails', 'attachment_filename')


def _backfill_attachment_filenames(bind: sa.engine.Connection) -> None:
    """Überführt den alten Einzelwert (`attachment_filename`) in die neue
    Liste - `NULL` (Altbestand, nie erfasst) bleibt eine leere Liste."""
    sent_emails = sa.Table('sent_emails', sa.MetaData(), autoload_with=bind)
    rows = bind.execute(
        sa.select(sent_emails.c.id, sent_emails.c.attachment_filename)
    ).fetchall()
    for row in rows:
        if row.attachment_filename:
            bind.execute(
                sent_emails.update()
                .where(sent_emails.c.id == row.id)
                .values(attachment_filenames=[row.attachment_filename])
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("sent_emails")}

    if "attachment_filename" not in existing_columns:
        op.add_column(
            'sent_emails',
            sa.Column('attachment_filename', sa.String(length=255), nullable=True),
        )
        _restore_single_attachment_filename(bind)

    if "attachment_filenames" in existing_columns:
        op.drop_column('sent_emails', 'attachment_filenames')


def _restore_single_attachment_filename(bind: sa.engine.Connection) -> None:
    """Best-effort-Umkehrung: nur der erste Listen-Eintrag (der Lebenslauf)
    lässt sich in die alte Einzelspalte zurückschreiben."""
    sent_emails = sa.Table('sent_emails', sa.MetaData(), autoload_with=bind)
    rows = bind.execute(
        sa.select(sent_emails.c.id, sent_emails.c.attachment_filenames)
    ).fetchall()
    for row in rows:
        filenames = row.attachment_filenames or []
        if filenames:
            bind.execute(
                sent_emails.update()
                .where(sent_emails.c.id == row.id)
                .values(attachment_filename=filenames[0])
            )
