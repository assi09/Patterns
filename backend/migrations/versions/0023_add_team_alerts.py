"""Add alerts for a change in a team's aggregate

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-10 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_team_alerts_team_id"), "team_alerts", ["team_id"], unique=False)
    op.create_index(
        "ix_team_alerts_team_metric", "team_alerts", ["team_id", "metric"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_team_alerts_team_metric", table_name="team_alerts")
    op.drop_index(op.f("ix_team_alerts_team_id"), table_name="team_alerts")
    op.drop_table("team_alerts")
