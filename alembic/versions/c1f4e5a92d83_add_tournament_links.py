"""add_tournament_links

Revision ID: c1f4e5a92d83
Revises: 98d8af9f947b
Create Date: 2026-11-07 08:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = 'c1f4e5a92d83'
down_revision: Union[str, Sequence[str], None] = '98d8af9f947b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Add links JSON column to tournaments."""
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns("tournaments")]

    if "links" not in cols:
        op.add_column(
            "tournaments",
            sa.Column("links", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json" if conn.dialect.name == "postgresql" else "'[]'")),
        )


def downgrade() -> None:
    """Downgrade schema: Remove links column from tournaments."""
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns("tournaments")]

    if "links" in cols:
        op.drop_column("tournaments", "links")
