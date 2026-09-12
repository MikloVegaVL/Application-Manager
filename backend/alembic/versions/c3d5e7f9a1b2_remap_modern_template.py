"""remap legacy modern cv template to template-1

Revision ID: c3d5e7f9a1b2
Revises: b8f2a4c6d9e1
Create Date: 2026-09-12 15:20:00.000000+00:00

`modern` wurde durch `template-1` ersetzt (R1/R11). Bestehende Profile, die
noch `modern` gespeichert haben, werden auf die nächstliegende neue Vorlage
umgestellt, damit Vorschau/Export ohne Nutzeraktion funktionieren. `NULL`
(keine Vorlage gewählt) und alle übrigen Werte bleiben unangetastet.

Der Downgrade ist bewusst ein No-op: Nach dem Ausrollen ist ein vom Nutzer
gewähltes `template-1` nicht mehr von einem remappten `modern` zu
unterscheiden, ein Zurückschreiben würde echte Auswahlen verfälschen (siehe
`17c15ce91b4e_add_cv_builder_fields.py`, das aus demselben Grund keine
Daten-Backfills umkehrt).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d5e7f9a1b2'
down_revision: str | None = 'b8f2a4c6d9e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("master_profiles")}
    if "template_id" in existing_columns:
        op.execute(
            "UPDATE master_profiles SET template_id = 'template-1' "
            "WHERE template_id = 'modern'"
        )


def downgrade() -> None:
    # Bewusst kein Reverse-Remap (siehe Modul-Docstring).
    pass
