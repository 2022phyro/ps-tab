"""increase_tournament_status_length

Revision ID: d682051e7a29
Revises: c571051d5c18
Create Date: 2026-11-09 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd682051e7a29'
down_revision: Union[str, Sequence[str], None] = 'c571051d5c18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Increase tournaments.status column length to accommodate 'registration'."""
    op.alter_column('tournaments', 'status', type_=sa.String(length=32), existing_type=sa.String(length=9))


def downgrade() -> None:
    """Revert tournaments.status column length."""
    op.alter_column('tournaments', 'status', type_=sa.String(length=9), existing_type=sa.String(length=32))
