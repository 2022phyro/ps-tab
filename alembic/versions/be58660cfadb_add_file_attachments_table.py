"""add_file_attachments_table

Revision ID: be58660cfadb
Revises: c07778314860
Create Date: 2026-11-01 11:17:55.186721

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from kwuo.core.typeid import TypeIDType


# revision identifiers, used by Alembic.
revision: str = 'be58660cfadb'
down_revision: Union[str, Sequence[str], None] = 'c07778314860'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use execute to check if table already exists (e.g. from Base.metadata.create_all)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'file_attachments' not in tables:
        op.create_table(
            'file_attachments',
            sa.Column('id', TypeIDType('att'), nullable=False),
            sa.Column('tournament_id', TypeIDType('tourn'), nullable=False),
            sa.Column('task_id', TypeIDType('task'), nullable=True),
            sa.Column('uploader_id', TypeIDType(('user', 'usr')), nullable=True),
            sa.Column('title', sa.String(length=150), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('category', sa.String(length=32), nullable=False),
            sa.Column('filename', sa.String(length=255), nullable=False),
            sa.Column('file_path', sa.String(length=500), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=False),
            sa.Column('mime_type', sa.String(length=100), nullable=False),
            sa.Column('sha256_hash', sa.String(length=64), nullable=True),
            sa.Column('is_public', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('display_order', sa.Integer(), server_default=sa.text('1'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['uploader_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_file_attachments_tournament_id'), 'file_attachments', ['tournament_id'], unique=False)
        op.create_index(op.f('ix_file_attachments_task_id'), 'file_attachments', ['task_id'], unique=False)
        op.create_index(op.f('ix_file_attachments_uploader_id'), 'file_attachments', ['uploader_id'], unique=False)
        op.create_index(op.f('ix_file_attachments_category'), 'file_attachments', ['category'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'file_attachments' in tables:
        op.drop_index(op.f('ix_file_attachments_category'), table_name='file_attachments')
        op.drop_index(op.f('ix_file_attachments_uploader_id'), table_name='file_attachments')
        op.drop_index(op.f('ix_file_attachments_task_id'), table_name='file_attachments')
        op.drop_index(op.f('ix_file_attachments_tournament_id'), table_name='file_attachments')
        op.drop_table('file_attachments')
