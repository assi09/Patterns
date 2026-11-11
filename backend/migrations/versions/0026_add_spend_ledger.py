"""Add a spending ledger kept apart from the chats

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-11 15:00:00

Deleting a chat deleted its answers' costs, and the daily caps were summed from them, so deleting
chats handed back spending. Costs already stored are copied in, so today's caps stay right.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    spend = op.create_table(
        "spend",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spend_at", "spend", ["at"], unique=False)
    op.create_index("ix_spend_user_at", "spend", ["user_id", "at"], unique=False)
    rows = op.get_bind().execute(
        sa.text(
            "SELECT user_id, cost_usd, created_at FROM chat_messages "
            "WHERE role = 'assistant' AND cost_usd > 0"
        )
    )
    copied = [
        {
            "id": uuid.uuid4(),
            "user_id": user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)),
            "kind": "answer",
            "cost_usd": cost,
            "at": at if getattr(at, "tzinfo", None) else _utc(at),
        }
        for user_id, cost, at in rows
    ]
    if copied:
        op.bulk_insert(spend, copied)


def _utc(at):
    from datetime import datetime

    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    return at.replace(tzinfo=UTC)


def downgrade() -> None:
    op.drop_index("ix_spend_user_at", table_name="spend")
    op.drop_index("ix_spend_at", table_name="spend")
    op.drop_table("spend")
