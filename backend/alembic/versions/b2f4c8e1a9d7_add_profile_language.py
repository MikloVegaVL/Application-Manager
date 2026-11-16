"""add profile language and composite (profile_type, language) uniqueness

Revision ID: b2f4c8e1a9d7
Revises: e4c9a1b2d3f6
Create Date: 2026-11-16 12:00:00.000000+00:00

Bilingual CV profiles (docs/plans/2026-11-16-001-feat-bilingual-cv-profiles-plan.md,
U1/KTD1): language is a first-class profile dimension.

- Adds `master_profiles.language` ("de"/"en", non-null). Existing rows are
  German, so a temporary `server_default='de'` backfills them and is then
  cleared to match the model (no server default, no Python default).
- Replaces the single-column `uq_master_profiles_profile_type` unique with a
  composite `(profile_type, language)` unique, so each domain can hold one
  German and one English row.

SQLite has no direct ADD/DROP CONSTRAINT support, so the constraint swap goes
through `op.batch_alter_table`. Guarded-column/inspection style mirrors
`f71a8d3d7876` / `9a7b6c5d4e3f`. Parented on the verified sole head
`e4c9a1b2d3f6`; an existing revision's `down_revision` is never rewritten.

Downgrade is intentionally data-aware: restoring the single-column unique
cannot succeed once a domain has both `de` and `en` rows, so the downgrade
refuses with a clear error instead of silently deleting English profiles.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2f4c8e1a9d7"
down_revision: str | None = "e4c9a1b2d3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LANGUAGE_ENUM = sa.Enum(
    "de",
    "en",
    name="profile_language",
    native_enum=False,
    length=2,
    validate_strings=True,
)
_COMPOSITE_UNIQUE_NAME = "uq_master_profiles_profile_type_language"
_SINGLE_UNIQUE_NAME = "uq_master_profiles_profile_type"
# Applied narrowly so SQLite batch mode can name an (originally unnamed)
# single-column unique constraint during reflection.
_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def _unique_by_columns(
    inspector: sa.engine.reflection.Inspector, table_name: str, columns: list[str]
) -> dict | None:
    for uc in inspector.get_unique_constraints(table_name):
        if uc["column_names"] == columns:
            return uc
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("master_profiles")}

    added_language = "language" not in existing_columns
    if added_language:
        # `server_default` only so the `ADD COLUMN nullable=False` statement
        # has a value for already-existing (German) rows; dropped right after
        # so it does not diverge from the model.
        op.add_column(
            "master_profiles",
            sa.Column("language", _LANGUAGE_ENUM, nullable=False, server_default="de"),
        )

    inspector = sa.inspect(bind)
    single_uc = _unique_by_columns(inspector, "master_profiles", ["profile_type"])
    composite_uc = _unique_by_columns(inspector, "master_profiles", ["profile_type", "language"])

    with op.batch_alter_table(
        "master_profiles", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        if single_uc is not None:
            batch_op.drop_constraint(single_uc["name"] or _SINGLE_UNIQUE_NAME, type_="unique")
        if composite_uc is None:
            batch_op.create_unique_constraint(
                _COMPOSITE_UNIQUE_NAME, ["profile_type", "language"]
            )
        if added_language:
            batch_op.alter_column("language", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()

    # Refuse before any DDL: the single-column unique cannot be restored while
    # a domain has more than one language row.
    duplicates = bind.execute(
        sa.text(
            "SELECT profile_type, COUNT(*) AS row_count FROM master_profiles "
            "WHERE profile_type IS NOT NULL "
            "GROUP BY profile_type HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "Downgrade abgebrochen: für mindestens einen profile_type existieren "
            "mehrere Sprach-Profile. Die Einzelspalten-Unique-Constraint kann nicht "
            "wiederhergestellt werden, ohne Profile zu löschen."
        )

    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("master_profiles")}
    if "language" not in existing_columns:
        return

    composite_uc = _unique_by_columns(
        inspector, "master_profiles", ["profile_type", "language"]
    )
    single_uc = _unique_by_columns(inspector, "master_profiles", ["profile_type"])

    with op.batch_alter_table(
        "master_profiles", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        if composite_uc is not None:
            batch_op.drop_constraint(
                composite_uc["name"] or _COMPOSITE_UNIQUE_NAME, type_="unique"
            )
        if single_uc is None:
            batch_op.create_unique_constraint(_SINGLE_UNIQUE_NAME, ["profile_type"])
        batch_op.drop_column("language")
