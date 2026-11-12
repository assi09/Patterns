"""Add the supervisor's message a team note was made from

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-11 17:00:00

Deleting a note now deletes that exchange too: the team agent reads earlier messages, so the
words would otherwise keep a deleted note alive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("team_notes", sa.Column("source_message_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("team_notes") as batch:
        batch.drop_column("source_message_id")
