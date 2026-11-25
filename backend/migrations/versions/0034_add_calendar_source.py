"""Allow google_calendar as a source: daily meeting counts, never events

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-25 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "source IN ('google_health', 'takeout', 'google_calendar')"
OLD = "source IN ('google_health', 'takeout')"


def _set(table: str, rule: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(f"ck_{table}_source", type_="check")
        batch.create_check_constraint(f"ck_{table}_source", rule)


def upgrade() -> None:
    """Upgrade schema."""
    _set("daily_metrics", NEW)
    _set("sync_runs", NEW)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM daily_metrics WHERE source = 'google_calendar'")
    op.execute("DELETE FROM sync_runs WHERE source = 'google_calendar'")
    _set("daily_metrics", OLD)
    _set("sync_runs", OLD)
