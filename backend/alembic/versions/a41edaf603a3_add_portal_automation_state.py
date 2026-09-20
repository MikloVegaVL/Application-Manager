"""add portal automation state to applications and portal_submissions table

Revision ID: a41edaf603a3
Revises: c7f3a1b9d2e4
Create Date: 2026-09-19 10:00:00.000000+00:00

Adds the automation-state columns U1 needs for the portal auto-fill agent
(docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md):
`applications.automation_state`/`action_needed_reason`/
`automation_started_at`, plus a new `portal_submissions` log table mirroring
`sent_emails` (`ondelete=SET NULL` + a `company`/`job_title`/`platform`
snapshot so the log stays readable after the `Application` is deleted).

Parented on the current single head `c7f3a1b9d2e4`. Never rewrite an existing
revision's `down_revision` - a rebase silently strands already-migrated
databases (see docs/solutions/database-issues/
alembic-migration-rebase-silently-skips-sibling-branch.md).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a41edaf603a3'
down_revision: str | None = 'c7f3a1b9d2e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}

    if "automation_state" not in existing_columns:
        op.add_column('applications', sa.Column('automation_state', sa.String(length=20), nullable=True))
    if "action_needed_reason" not in existing_columns:
        op.add_column('applications', sa.Column('action_needed_reason', sa.String(length=30), nullable=True))
    if "automation_started_at" not in existing_columns:
        op.add_column(
            'applications', sa.Column('automation_started_at', sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table(
        'portal_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('company', sa.String(length=255), nullable=True),
        sa.Column('job_title', sa.String(length=255), nullable=True),
        sa.Column('platform', sa.String(length=100), nullable=True),
        sa.Column('portal_url', sa.String(length=2048), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_portal_submissions_id'), 'portal_submissions', ['id'], unique=False)
    op.create_index(
        op.f('ix_portal_submissions_application_id'), 'portal_submissions', ['application_id'], unique=False
    )
    op.create_index(
        op.f('ix_portal_submissions_submitted_at'), 'portal_submissions', ['submitted_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_portal_submissions_submitted_at'), table_name='portal_submissions')
    op.drop_index(op.f('ix_portal_submissions_application_id'), table_name='portal_submissions')
    op.drop_index(op.f('ix_portal_submissions_id'), table_name='portal_submissions')
    op.drop_table('portal_submissions')

    bind = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("applications")}

    if "automation_started_at" in existing_columns:
        op.drop_column('applications', 'automation_started_at')
    if "action_needed_reason" in existing_columns:
        op.drop_column('applications', 'action_needed_reason')
    if "automation_state" in existing_columns:
        op.drop_column('applications', 'automation_state')
