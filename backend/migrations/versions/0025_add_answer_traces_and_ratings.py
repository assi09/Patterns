"""Add a stored trace per answer, and thumbs up or down on answers in both chats

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-11 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATED = ("chat_messages", "team_chat_messages")


def upgrade() -> None:
    op.create_table(
        "answer_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("team_message_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("stages_ms", sa.JSON(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("tool_errors", sa.Integer(), nullable=False),
        sa.Column("repair_rounds", sa.Integer(), nullable=False),
        sa.Column("rejected_claims", sa.Integer(), nullable=False),
        sa.Column("summary_fell_back", sa.Boolean(), nullable=False),
        sa.Column("guard_down", sa.Boolean(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('answered', 'answered_in_part', 'budget', 'failed_checks', 'refused', "
            "'failed')",
            name="ck_answer_traces_outcome",
        ),
        sa.CheckConstraint(
            "(message_id IS NULL) != (team_message_id IS NULL)", name="ck_answer_traces_one_chat"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_message_id"], ["team_chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
        sa.UniqueConstraint("team_message_id"),
    )
    op.create_index("ix_answer_traces_created", "answer_traces", ["created_at"], unique=False)
    for table in RATED:
        op.add_column(table, sa.Column("rating", sa.String(length=8), nullable=True))
        op.add_column(table, sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True))
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(
                f"ck_{table}_rating", "rating IS NULL OR rating IN ('up', 'down')"
            )


def downgrade() -> None:
    for table in RATED:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_rating", type_="check")
            batch.drop_column("rated_at")
            batch.drop_column("rating")
    op.drop_index("ix_answer_traces_created", table_name="answer_traces")
    op.drop_table("answer_traces")
