"""Add outside lookups: what was looked up in USDA data or on the web, for the cache and the cap

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-05 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "outside_lookups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('food', 'web')", name="ck_outside_lookups_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outside_lookups_query", "outside_lookups", ["kind", "query", "created_at"])
    op.create_index("ix_outside_lookups_user", "outside_lookups", ["user_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_outside_lookups_user", table_name="outside_lookups")
    op.drop_index("ix_outside_lookups_query", table_name="outside_lookups")
    op.drop_table("outside_lookups")
