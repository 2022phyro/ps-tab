"""add_official_profile_phone_and_title

Revision ID: 98d8af9f947b
Revises: 181de544311f
Create Date: 2026-11-07 07:19:00.950906

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = '98d8af9f947b'
down_revision: Union[str, Sequence[str], None] = '181de544311f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns("official_profiles")]

    if "title" not in cols:
        op.add_column("official_profiles", sa.Column("title", sa.String(length=150), nullable=True))
    if "phone" not in cols:
        op.add_column("official_profiles", sa.Column("phone", sa.String(length=32), nullable=True))
    if "is_phone_public" not in cols:
        op.add_column("official_profiles", sa.Column("is_phone_public", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    if "display_order" not in cols:
        op.add_column("official_profiles", sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns("official_profiles")]

    if "display_order" in cols:
        op.drop_column("official_profiles", "display_order")
    if "is_phone_public" in cols:
        op.drop_column("official_profiles", "is_phone_public")
    if "phone" in cols:
        op.drop_column("official_profiles", "phone")
    if "title" in cols:
        op.drop_column("official_profiles", "title")
