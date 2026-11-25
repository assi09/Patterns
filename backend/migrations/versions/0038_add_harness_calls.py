"""Add MCP tool calls: which tool, whether it worked, when; never inputs or results

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "harness_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=True),
        sa.Column("tool", sa.String(length=40), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["access_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_harness_calls_user_id", "harness_calls", ["user_id"])
    op.create_index("ix_harness_calls_token_at", "harness_calls", ["token_id", "at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_harness_calls_token_at", table_name="harness_calls")
    op.drop_index("ix_harness_calls_user_id", table_name="harness_calls")
    op.drop_table("harness_calls")
