"""add profile_type and application profile_id

Revision ID: f71a8d3d7876
Revises: d1a2b3c4e5f6
Create Date: 2026-09-23 14:09:32.664965+00:00

U1 (docs/plans/2026-09-23-001-feat-profile-types-plan.md): schema foundation
for two independent profiles ("it"/"full_life", R1/R2/R3) and a durable
per-application profile link used to lock generation to one profile's data
(R5/R6).

- `master_profiles.profile_type` (nullable "it"/"full_life" enum, mirrors
  `Application.status`'s `native_enum=False` style) gets a plain UNIQUE
  constraint - at most one profile per type, and `NULL` never collides with
  `NULL` under standard SQL uniqueness semantics on SQLite or PostgreSQL, so
  no partial index is needed (KTD7).
- `master_profiles.email`'s old `unique=True` is dropped: contact info,
  including the email, is fully independent per profile now (KTD9), so two
  profiles may legitimately share the same email.
- `applications.profile_id` (nullable, indexed, FK -> master_profiles.id
  ON DELETE SET NULL) is backfilled for every existing `Application` row
  that already has `cover_letter_text` set, pointing at the id of the one
  `MasterProfile` row that can exist before this ships (R8: at most one
  pre-existing profile, so the backfill target is unambiguous). `SET NULL`
  rather than `CASCADE` so deleting a profile never deletes application
  history (KTD10).

SQLite has no `ALTER TABLE ... ADD/DROP CONSTRAINT` support, so every
constraint change here goes through `op.batch_alter_table` (table
recreate-and-copy) - see the `add_column` failure this was verified against
in review (`NotImplementedError: No support for ALTER of constraints in
SQLite dialect`). The original `email` unique constraint was created
unnamed (`sa.UniqueConstraint('email')` in the baseline schema, no
`naming_convention` configured on `Base.metadata`), so batch mode is given
an explicit `naming_convention` to assign it a stable name during reflection
that `drop_constraint()` can then target (Alembic's documented workaround
for unnamed constraints).

Guarded-column style (`sa.inspect(bind).get_columns(...)` before touching a
column/constraint) mirrors `d1a2b3c4e5f6`, `c7f3a1b9d2e4`, so a
partially-migrated database - or a second `alembic upgrade head` run - does
not error. Parented on the verified single head `d1a2b3c4e5f6`; an existing
revision's `down_revision` is never rewritten.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f71a8d3d7876'
down_revision: str | None = 'd1a2b3c4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Used only to give the (originally unnamed) `email` unique constraint a
# deterministic name when SQLite batch mode reflects the table - see the
# module docstring. Applied narrowly (single-column unique constraints
# only) so it never affects any other constraint on this table.
_UNIQUE_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

_PROFILE_TYPE_ENUM = sa.Enum(
    "it", "full_life", name="profile_type", native_enum=False, length=20, validate_strings=True
)


def _single_column_unique_constraint(
    inspector: sa.engine.reflection.Inspector, table_name: str, column_name: str
) -> dict | None:
    for uc in inspector.get_unique_constraints(table_name):
        if uc["column_names"] == [column_name]:
            return uc
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    profile_columns = {col["name"] for col in inspector.get_columns("master_profiles")}
    if "profile_type" not in profile_columns:
        with op.batch_alter_table("master_profiles") as batch_op:
            batch_op.add_column(sa.Column("profile_type", _PROFILE_TYPE_ENUM, nullable=True))

    inspector = sa.inspect(bind)
    email_uc = _single_column_unique_constraint(inspector, "master_profiles", "email")
    profile_type_uc = _single_column_unique_constraint(inspector, "master_profiles", "profile_type")

    if email_uc is not None or profile_type_uc is None:
        with op.batch_alter_table(
            "master_profiles", naming_convention=_UNIQUE_NAMING_CONVENTION
        ) as batch_op:
            if email_uc is not None:
                batch_op.drop_constraint(email_uc["name"] or "uq_master_profiles_email", type_="unique")
            if profile_type_uc is None:
                batch_op.create_unique_constraint("uq_master_profiles_profile_type", ["profile_type"])

    application_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}
    if "profile_id" not in application_columns:
        with op.batch_alter_table("applications") as batch_op:
            batch_op.add_column(sa.Column("profile_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_applications_profile_id_master_profiles",
                "master_profiles",
                ["profile_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index("ix_applications_profile_id", "applications", ["profile_id"])
        _backfill_profile_id(bind)


def _backfill_profile_id(bind: sa.engine.Connection) -> None:
    """Points `profile_id` at the one pre-existing `MasterProfile` row (if
    any) for every `Application` that already has generated content. At
    most one `MasterProfile` row can exist before this migration, so the
    target is unambiguous (R8)."""
    profile_row = bind.execute(sa.text("SELECT id FROM master_profiles LIMIT 1")).fetchone()
    if profile_row is None:
        return
    bind.execute(
        sa.text(
            "UPDATE applications SET profile_id = :profile_id "
            "WHERE cover_letter_text IS NOT NULL"
        ),
        {"profile_id": profile_row[0]},
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    application_columns = {col["name"] for col in inspector.get_columns("applications")}
    if "profile_id" in application_columns:
        index_names = {ix["name"] for ix in inspector.get_indexes("applications")}
        if "ix_applications_profile_id" in index_names:
            op.drop_index("ix_applications_profile_id", table_name="applications")
        with op.batch_alter_table("applications") as batch_op:
            batch_op.drop_constraint(
                "fk_applications_profile_id_master_profiles", type_="foreignkey"
            )
            batch_op.drop_column("profile_id")

    inspector = sa.inspect(bind)
    email_uc = _single_column_unique_constraint(inspector, "master_profiles", "email")
    profile_type_uc = _single_column_unique_constraint(inspector, "master_profiles", "profile_type")

    if profile_type_uc is not None or email_uc is None:
        with op.batch_alter_table(
            "master_profiles", naming_convention=_UNIQUE_NAMING_CONVENTION
        ) as batch_op:
            if profile_type_uc is not None:
                batch_op.drop_constraint(
                    profile_type_uc["name"] or "uq_master_profiles_profile_type", type_="unique"
                )
            if email_uc is None:
                batch_op.create_unique_constraint("uq_master_profiles_email", ["email"])

    profile_columns = {col["name"] for col in sa.inspect(bind).get_columns("master_profiles")}
    if "profile_type" in profile_columns:
        with op.batch_alter_table("master_profiles") as batch_op:
            batch_op.drop_column("profile_type")
