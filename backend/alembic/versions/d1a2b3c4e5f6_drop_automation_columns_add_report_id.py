"""drop portal automation columns and add portal_submissions.report_id

Revision ID: d1a2b3c4e5f6
Revises: 9c1d2e3f4a5b
Create Date: 2026-09-22 12:00:00.000000+00:00

U2/R17 (docs/plans/2026-09-22-003-feat-browser-extension-application-autofill-
plan.md): the server-side portal auto-fill agent is replaced by a browser
extension, so the four `Application` automation-state columns are dropped.
The extension reports a completed submission instead, and KTD3 adds a
nullable unique `portal_submissions.report_id` idempotency key so a repeated
report returns the existing row instead of inserting a second.

Both directions use the same inspector-guard pattern as the existing drop
migrations (`4e9f0a320779`, `581736b96da4`), so a partially-migrated database
does not error on re-run. Parented on the verified single head `9c1d2e3f4a5b`;
an existing revision's `down_revision` is never rewritten.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a2b3c4e5f6'
down_revision: str | None = '9c1d2e3f4a5b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTOMATION_COLUMNS = (
    "automation_state",
    "action_needed_reason",
    "action_needed_detail",
    "automation_started_at",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}
    for column in _AUTOMATION_COLUMNS:
        if column in existing_columns:
            op.drop_column('applications', column)

    inspector = sa.inspect(bind)
    submission_columns = {col["name"] for col in inspector.get_columns("portal_submissions")}
    if "report_id" not in submission_columns:
        op.add_column(
            'portal_submissions', sa.Column('report_id', sa.String(length=128), nullable=True)
        )
    index_names = {index["name"] for index in inspector.get_indexes("portal_submissions")}
    if "ix_portal_submissions_report_id" not in index_names:
        op.create_index(
            "ix_portal_submissions_report_id", "portal_submissions", ["report_id"], unique=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    submission_columns = {col["name"] for col in inspector.get_columns("portal_submissions")}
    index_names = {index["name"] for index in inspector.get_indexes("portal_submissions")}
    if "ix_portal_submissions_report_id" in index_names:
        op.drop_index("ix_portal_submissions_report_id", table_name="portal_submissions")
    if "report_id" in submission_columns:
        op.drop_column('portal_submissions', 'report_id')

    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}
    if "automation_state" not in existing_columns:
        op.add_column(
            'applications', sa.Column('automation_state', sa.String(length=20), nullable=True)
        )
    if "action_needed_reason" not in existing_columns:
        op.add_column(
            'applications', sa.Column('action_needed_reason', sa.String(length=30), nullable=True)
        )
    if "action_needed_detail" not in existing_columns:
        op.add_column(
            'applications', sa.Column('action_needed_detail', sa.String(length=80), nullable=True)
        )
    if "automation_started_at" not in existing_columns:
        op.add_column(
            'applications',
            sa.Column('automation_started_at', sa.DateTime(timezone=True), nullable=True),
        )
