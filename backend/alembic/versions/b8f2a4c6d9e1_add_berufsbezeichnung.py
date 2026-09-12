"""add berufsbezeichnung to master_profiles

Revision ID: b8f2a4c6d9e1
Revises: d98463c22408
Create Date: 2026-09-12 15:10:00.000000+00:00

Fügt das optionale Feld `berufsbezeichnung` (Job-Titel im CV) hinzu. Additiv
und nullable, daher für bestehende Zeilen ohne Backfill gültig.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f2a4c6d9e1'
down_revision: str | None = 'd98463c22408'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("master_profiles")}
    if "berufsbezeichnung" not in existing_columns:
        op.add_column(
            "master_profiles",
            sa.Column("berufsbezeichnung", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    existing_columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("master_profiles")}
    if "berufsbezeichnung" in existing_columns:
        op.drop_column("master_profiles", "berufsbezeichnung")
