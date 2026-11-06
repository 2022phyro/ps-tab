"""add_ghost_round_limit_and_schedule_items

Revision ID: d4e912384a71
Revises: 83c70ff7651a
Create Date: 2026-11-05 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e912384a71'
down_revision: Union[str, Sequence[str], None] = '83c70ff7651a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Add ghost_round_limit if not already present on tournaments
    tourn_cols = [c['name'] for c in inspector.get_columns('tournaments')]
    if 'ghost_round_limit' not in tourn_cols:
        op.add_column(
            'tournaments',
            sa.Column('ghost_round_limit', sa.Integer(), server_default='2', nullable=False)
        )

    # Create schedule_items table if not exists
    tables = inspector.get_table_names()
    if 'schedule_items' not in tables:
        op.create_table(
            'schedule_items',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('tournament_id', sa.String(length=36), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
            sa.Column('location', sa.String(length=200), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_published', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('display_order', sa.Integer(), server_default='1', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_schedule_items_tournament_id'), 'schedule_items', ['tournament_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_schedule_items_tournament_id'), table_name='schedule_items')
    op.drop_table('schedule_items')
    op.drop_column('tournaments', 'ghost_round_limit')
