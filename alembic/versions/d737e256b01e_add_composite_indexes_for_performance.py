"""add_composite_indexes_for_performance

Revision ID: d737e256b01e
Revises: d682051e7a29
Create Date: 2026-11-09 18:38:48.667927

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd737e256b01e'
down_revision: Union[str, Sequence[str], None] = 'd682051e7a29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite indexes for tournament queries, filtering, and attachments."""
    op.create_index(
        'ix_participants_tournament_status',
        'participants',
        ['tournament_id', 'status'],
        unique=False,
    )
    op.create_index(
        'ix_participants_tournament_name',
        'participants',
        ['tournament_id', 'name'],
        unique=False,
    )
    op.create_index(
        'ix_institutions_tournament_name',
        'institutions',
        ['tournament_id', 'name'],
        unique=False,
    )
    op.create_index(
        'ix_file_attachments_tournament_category',
        'file_attachments',
        ['tournament_id', 'category'],
        unique=False,
    )


def downgrade() -> None:
    """Drop composite indexes."""
    op.drop_index('ix_file_attachments_tournament_category', table_name='file_attachments')
    op.drop_index('ix_institutions_tournament_name', table_name='institutions')
    op.drop_index('ix_participants_tournament_name', table_name='participants')
    op.drop_index('ix_participants_tournament_status', table_name='participants')
