"""Keep each team week's explorer figures, every metric's evidence, once and with when it was made

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "team_metric_weeks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("members_total", sa.Integer(), nullable=False),
        sa.Column("members_with_data", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("made_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "week_start", name="uq_team_metric_weeks_week"),
    )
    op.create_index(
        op.f("ix_team_metric_weeks_team_id"), "team_metric_weeks", ["team_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_team_metric_weeks_team_id"), table_name="team_metric_weeks")
    op.drop_table("team_metric_weeks")
