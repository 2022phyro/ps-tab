"""add_institution_metadata_and_affiliations

Revision ID: d1681ee63f2b
Revises: d4e912384a71
Create Date: 2026-11-05 20:46:22.683418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1681ee63f2b'
down_revision: Union[str, Sequence[str], None] = 'd4e912384a71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Update institutions table
    op.add_column('institutions', sa.Column('tournament_id', sa.String(length=36), nullable=True))
    op.add_column('institutions', sa.Column('country', sa.String(length=100), nullable=True))
    op.add_column('institutions', sa.Column('region', sa.String(length=100), nullable=True))
    op.drop_index('ix_institutions_name', table_name='institutions')
    op.create_index(op.f('ix_institutions_name'), 'institutions', ['name'], unique=False)
    op.create_index(op.f('ix_institutions_tournament_id'), 'institutions', ['tournament_id'], unique=False)
    op.create_unique_constraint('uq_institutions_tournament_name', 'institutions', ['tournament_id', 'name'])
    op.create_foreign_key(
        'fk_institutions_tournament_id_tournaments',
        'institutions',
        'tournaments',
        ['tournament_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_institutions_tournament_id_tournaments', 'institutions', type_='foreignkey')
    op.drop_constraint('uq_institutions_tournament_name', 'institutions', type_='unique')
    op.drop_index(op.f('ix_institutions_tournament_id'), table_name='institutions')
    op.drop_index(op.f('ix_institutions_name'), table_name='institutions')
    op.create_index('ix_institutions_name', 'institutions', ['name'], unique=True)
    op.drop_column('institutions', 'region')
    op.drop_column('institutions', 'country')
    op.drop_column('institutions', 'tournament_id')
