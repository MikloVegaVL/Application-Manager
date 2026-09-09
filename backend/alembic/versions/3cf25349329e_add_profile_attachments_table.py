"""add profile_attachments table

Revision ID: 3cf25349329e
Revises: 4e9f0a320779
Create Date: 2026-09-09 00:00:00.000000+00:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cf25349329e'
down_revision: str | None = '4e9f0a320779'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('profile_attachments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=False),
    sa.Column('file_path', sa.String(length=1024), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['master_profiles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_profile_attachments_id'), 'profile_attachments', ['id'], unique=False)
    op.create_index(op.f('ix_profile_attachments_profile_id'), 'profile_attachments', ['profile_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_profile_attachments_profile_id'), table_name='profile_attachments')
    op.drop_index(op.f('ix_profile_attachments_id'), table_name='profile_attachments')
    op.drop_table('profile_attachments')
