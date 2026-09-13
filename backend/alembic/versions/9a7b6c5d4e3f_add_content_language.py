"""add content_language/content_translations_json and drop document_language

Revision ID: 9a7b6c5d4e3f
Revises: e2b7c9a41f60
Create Date: 2026-09-13 12:00:00.000000+00:00

Global Language Unification (docs/plans/2026-09-13-003-feat-global-language-
unification-plan.md, U1/U2/KTD1/KTD3):

- Adds `content_language` (which language the active content fields hold;
  default `de`, existing rows are treated as German) and
  `content_translations_json` (the other language's prose snapshot,
  `{field_name: translated_text}`).
- Drops the per-profile `document_language` column: the CV document language
  now comes from the request/global selector, not from a persisted profile
  field.

Both directions are idempotent via the `sa.inspect(...).get_columns` guard
used by `17c15ce91b4e`. Parented on the current single head `e2b7c9a41f60`;
an existing revision's `down_revision` is never rewritten.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a7b6c5d4e3f'
down_revision: str | None = 'e2b7c9a41f60'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    # `server_default`, only Python-side `default="de"`/`default=dict`; see
    # `tests/test_migrations.py`, which fails on exactly such a mismatch).
    with op.batch_alter_table('master_profiles') as batch_op:
        if added_content_language:
            batch_op.alter_column('content_language', server_default=None)
        if added_translations:
            batch_op.alter_column('content_translations_json', server_default=None)

    if "document_language" in existing_columns:
        op.drop_column('master_profiles', 'document_language')


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "content_translations_json" in existing_columns:
        op.drop_column('master_profiles', 'content_translations_json')
    if "content_language" in existing_columns:
        op.drop_column('master_profiles', 'content_language')

    # Restore the nullable per-profile document-language column removed by
    # `upgrade()` (its values were intentionally not preserved - the plan
    # supersedes that control, see KTD3).
    if "document_language" not in existing_columns:
        op.add_column(
            'master_profiles',
            sa.Column('document_language', sa.String(length=10), nullable=True),
        )
