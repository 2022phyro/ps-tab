"""add_tournament_timezone

Revision ID: c571051d5c18
Revises: e188a458af9c
Create Date: 2026-11-09 06:46:57.100178

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c571051d5c18'
down_revision: Union[str, Sequence[str], None] = 'e188a458af9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tournaments', sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tournaments', 'timezone')
