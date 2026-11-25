"""Add MCP access tokens and what harnesses send in, held for approval

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-25 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW = "source IN ('google_health', 'takeout', 'google_calendar', 'harness_calendar')"
OLD = "source IN ('google_health', 'takeout', 'google_calendar')"


def _sources(rule: str) -> None:
    for table in ("daily_metrics", "sync_runs"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_source", type_="check")
            batch.create_check_constraint(f"ck_{table}_source", rule)


def upgrade() -> None:
    """Upgrade schema."""
    _sources(NEW)
    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_access_tokens_user_id", "access_tokens", ["user_id"])
    op.create_table(
        "harness_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("token_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('calendar_days', 'team_event')", name="ck_harness_submissions_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined')",
            name="ck_harness_submissions_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["access_tokens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_harness_submissions_user_id", "harness_submissions", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM daily_metrics WHERE source = 'harness_calendar'")
    _sources(OLD)
    op.drop_index("ix_harness_submissions_user_id", table_name="harness_submissions")
    op.drop_table("harness_submissions")
    op.drop_index("ix_access_tokens_user_id", table_name="access_tokens")
    op.drop_table("access_tokens")
