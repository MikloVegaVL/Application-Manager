"""merge cv builder and sent-to-email heads

Revision ID: d98463c22408
Revises: 17c15ce91b4e, 7b2f5c9d1a34
Create Date: 2026-09-12 10:30:04.714678+00:00

`17c15ce91b4e` (add cv builder fields) and `7b2f5c9d1a34` (add sent_to_email
to applications) branched independently off `3cf25349329e` when
feat/cv-builder-editor and develop diverged. A real merge revision - not a
rebase of one onto the other - is required here specifically because a
Postgres database may already have applied one branch (e.g. via an earlier
`alembic upgrade head` against the old graph): Alembic can walk such a
database through the sibling branch it's missing to reach this merge point,
whereas rebasing one revision onto the other leaves an already-migrated
database stuck at that revision forever, since `alembic upgrade head` then
sees its stamped revision as already being the head (see
ce-debug-Untersuchung 2026-09-12, reproduced against a live docker-compose
Postgres DB).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd98463c22408'
down_revision: str | None = ('17c15ce91b4e', '7b2f5c9d1a34')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
