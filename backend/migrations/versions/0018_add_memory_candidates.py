"""Add memory candidates: dated, counted facts and the inbox entry that asks about one

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "kind IN ('routine', 'goal', 'preference', 'context')"
NEW_KINDS = "kind IN ('routine', 'goal', 'preference', 'context', 'event', 'commitment')"
OLD_STATUSES = "status IN ('proposed', 'approved', 'declined')"
NEW_STATUSES = "status IN ('candidate', 'proposed', 'approved', 'declined')"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("memory_facts") as batch:
        batch.drop_constraint("ck_memory_facts_kind", type_="check")
        batch.drop_constraint("ck_memory_facts_status", type_="check")
        batch.create_check_constraint("ck_memory_facts_kind", NEW_KINDS)
        batch.create_check_constraint("ck_memory_facts_status", NEW_STATUSES)
        batch.add_column(sa.Column("start_day", sa.Date(), nullable=True))
        batch.add_column(sa.Column("end_day", sa.Date(), nullable=True))
        batch.add_column(sa.Column("seen", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("source_message_id", sa.Uuid(), nullable=True))
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(sa.Column("fact_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_notifications_fact_id_memory_facts",
            "memory_facts",
            ["fact_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint("fk_notifications_fact_id_memory_facts", type_="foreignkey")
        batch.drop_column("fact_id")
    op.execute("DELETE FROM memory_facts WHERE status = 'candidate'")
    op.execute("DELETE FROM memory_facts WHERE kind IN ('event', 'commitment')")
    with op.batch_alter_table("memory_facts") as batch:
        batch.drop_column("source_message_id")
        batch.drop_column("last_seen_at")
        batch.drop_column("seen")
        batch.drop_column("end_day")
        batch.drop_column("start_day")
        batch.drop_constraint("ck_memory_facts_status", type_="check")
        batch.drop_constraint("ck_memory_facts_kind", type_="check")
        batch.create_check_constraint("ck_memory_facts_kind", OLD_KINDS)
        batch.create_check_constraint("ck_memory_facts_status", OLD_STATUSES)
