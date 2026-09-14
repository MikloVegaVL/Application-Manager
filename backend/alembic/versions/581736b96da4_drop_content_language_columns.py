"""drop content_language/content_translations_json columns

Revision ID: 581736b96da4
Revises: 9a7b6c5d4e3f
Create Date: 2026-09-13 12:30:00.000000+00:00

Remove Translation Functionality (docs/plans/2026-09-13-005-refactor-remove-
translation-functionality-plan.md, U4/R5/KTD4): the app now runs English-
only, so `content_language` and `content_translations_json` (added by
`9a7b6c5d4e3f` for per-language CV content) are dropped rather than left
dormant - there's no translated data worth preserving since that feature
merged the same day.

Both directions are idempotent via the `sa.inspect(...).get_columns` guard
used by `4e9f0a320779`/`9a7b6c5d4e3f`. Parented on the current single head
`9a7b6c5d4e3f`; an existing revision's `down_revision` is never rewritten.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '581736b96da4'
down_revision: str | None = '9a7b6c5d4e3f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "content_translations_json" in existing_columns:
        op.drop_column('master_profiles', 'content_translations_json')
    if "content_language" in existing_columns:
        op.drop_column('master_profiles', 'content_language')


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    added_content_language = "content_language" not in existing_columns
    added_translations = "content_translations_json" not in existing_columns

    if added_content_language:
        op.add_column(
            'master_profiles',
            sa.Column('content_language', sa.String(length=10), nullable=False, server_default='de'),
        )
    if added_translations:
        op.add_column(
            'master_profiles',
            sa.Column('content_translations_json', sa.JSON(), nullable=False, server_default='{}'),
        )

    # `server_default` was only needed so the `ADD COLUMN nullable=False`
    # statements above have a value for already-existing rows - drop it
    # afterwards so it doesn't diverge from the model (which has no
    # `server_default`; see `tests/test_migrations.py`).
    with op.batch_alter_table('master_profiles') as batch_op:
        if added_content_language:
            batch_op.alter_column('content_language', server_default=None)
        if added_translations:
            batch_op.alter_column('content_translations_json', server_default=None)
