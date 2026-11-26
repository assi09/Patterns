"""Record the demo teams and made-up accounts the demo-team command creates, so removing one
deletes exactly those

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-26 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "demo_teams",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id"),
    )
    op.create_table(
        "demo_accounts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["demo_teams.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(op.f("ix_demo_accounts_team_id"), "demo_accounts", ["team_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_demo_accounts_team_id"), table_name="demo_accounts")
    op.drop_table("demo_accounts")
    op.drop_table("demo_teams")
