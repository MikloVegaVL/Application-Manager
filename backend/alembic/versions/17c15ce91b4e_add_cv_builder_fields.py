"""add cv builder fields

Revision ID: 17c15ce91b4e
Revises: 3cf25349329e
Create Date: 2026-09-10 18:00:33.973291+00:00

Adds the new `MasterProfile` columns needed for the CV Builder (see U1 of
docs/plans/2026-09-10-001-feat-cv-builder-editor-plan.md): a profile photo
(`photo_path`/`photo_filename`, mirroring the existing
`cv_file_path`/`cv_filename` convention - KTD4), structured languages/projects
lists (`languages_json`/`projects_json`, analogous to the existing
`experiences_json`/`education_json`), and a chosen export `template_id`.

Also backfills existing `skills_json` rows (KTD5): the column used to hold a
flat `list[str]`; the CV Builder needs a proficiency level per skill
(`app.schemas.master_profile.SkillEntry`), so each `"Python"`-style string
entry becomes `{"name": "Python", "level": "Grundkenntnisse"}` (lowest tier
default) rather than being dropped or blanked. Done row-by-row via
`op.get_bind()` instead of a bulk SQL expression, matching this repo's
existing migration style (see `4e9f0a320779`) - JSON columns aren't safely
bulk-transformable with plain SQL across SQLite and PostgreSQL, and existing
entries that are already `{"name": ..., "level": ...}` dicts (e.g. an
already-migrated row, or a fresh install with no legacy data) are left
untouched.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17c15ce91b4e'
down_revision: str | None = '3cf25349329e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEFAULT_SKILL_LEVEL = "Grundkenntnisse"


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    if "photo_path" not in existing_columns:
        op.add_column('master_profiles', sa.Column('photo_path', sa.String(length=1024), nullable=True))
    if "photo_filename" not in existing_columns:
        op.add_column('master_profiles', sa.Column('photo_filename', sa.String(length=255), nullable=True))
    if "languages_json" not in existing_columns:
        op.add_column(
            'master_profiles',
            sa.Column('languages_json', sa.JSON(), nullable=False, server_default='[]'),
        )
    if "projects_json" not in existing_columns:
        op.add_column(
            'master_profiles',
            sa.Column('projects_json', sa.JSON(), nullable=False, server_default='[]'),
        )
    if "template_id" not in existing_columns:
        op.add_column('master_profiles', sa.Column('template_id', sa.String(length=100), nullable=True))

    # `server_default` was only needed so the `ADD COLUMN nullable=False`
    # statement above has a value for already-existing rows - drop it
    # afterwards so it doesn't diverge from the model (which has no
    # `server_default`, only a Python-side `default=list`; see
    # `tests/test_migrations.py`, which fails on exactly such a mismatch).
    with op.batch_alter_table('master_profiles') as batch_op:
        batch_op.alter_column('languages_json', server_default=None)
        batch_op.alter_column('projects_json', server_default=None)

    # KTD5: flat `list[str]` skills -> `list[{"name": ..., "level": ...}]`.
    master_profiles = sa.table(
        'master_profiles',
        sa.column('id', sa.Integer()),
        sa.column('skills_json', sa.JSON()),
    )
    rows = bind.execute(sa.select(master_profiles.c.id, master_profiles.c.skills_json)).fetchall()
    for row in rows:
        raw_skills = row.skills_json or []
        migrated_skills = [
            {"name": entry, "level": _DEFAULT_SKILL_LEVEL} if isinstance(entry, str) else entry
            for entry in raw_skills
        ]
        if migrated_skills != raw_skills:
            bind.execute(
                master_profiles.update()
                .where(master_profiles.c.id == row.id)
                .values(skills_json=migrated_skills)
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}

    # `skills_json` is intentionally left as `{"name": ..., "level": ...}` on
    # downgrade - the pre-migration `list[str]` shape can't be reconstructed
    # without discarding the proficiency level, and this mirrors the
    # existing repo convention of not reversing data backfills (see
    # `4e9f0a320779`, which is a no-op reversal for its column drops too).
    if "template_id" in existing_columns:
        op.drop_column('master_profiles', 'template_id')
    if "projects_json" in existing_columns:
        op.drop_column('master_profiles', 'projects_json')
    if "languages_json" in existing_columns:
        op.drop_column('master_profiles', 'languages_json')
    if "photo_filename" in existing_columns:
        op.drop_column('master_profiles', 'photo_filename')
    if "photo_path" in existing_columns:
        op.drop_column('master_profiles', 'photo_path')
