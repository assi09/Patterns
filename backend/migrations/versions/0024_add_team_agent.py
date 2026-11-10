"""Add the team agent's notes, proposed actions and conversation

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-10 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_team_notes_team_id"), "team_notes", ["team_id"], unique=False)
    op.create_table(
        "team_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("body", sa.String(length=400), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('challenge', 'message')", name="ck_team_actions_kind"),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'declined')", name="ck_team_actions_status"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_team_actions_team_id"), "team_actions", ["team_id"], unique=False)
    op.create_table(
        "team_chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_team_chat_team_created", "team_chat_messages", ["team_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_team_chat_team_created", table_name="team_chat_messages")
    op.drop_table("team_chat_messages")
    op.drop_index(op.f("ix_team_actions_team_id"), table_name="team_actions")
    op.drop_table("team_actions")
    op.drop_index(op.f("ix_team_notes_team_id"), table_name="team_notes")
    op.drop_table("team_notes")
