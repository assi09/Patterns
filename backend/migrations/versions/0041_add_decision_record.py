"""Keep what a team decided and what was reported: an event's category, and on a team change its
request id, the connection that recorded it, explicit links, tracking and implementation

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-27 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = ("deadline", "launch", "travel", "holiday", "reorganisation", "onboarding", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("team_notes") as batch:
        batch.add_column(sa.Column("category", sa.String(length=16), nullable=True))
        batch.create_check_constraint("ck_team_notes_category", _in("category", CATEGORIES))
    with op.batch_alter_table("team_actions") as batch:
        batch.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("token_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("event_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("finding_report_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("finding_evidence_id", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("observe_starts_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("observe_ends_on", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column(
                "comparison",
                sa.String(length=24),
                server_default="before_the_change",
                nullable=True,
            )
        )
        batch.add_column(sa.Column("implementation", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("implementation_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_team_actions_event_id_team_notes",
            "team_notes",
            ["event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_team_actions_request", ["team_id", "request_id"])
        batch.create_check_constraint(
            "ck_team_actions_implementation", _in("implementation", ("tried", "not_tried"))
        )
        batch.create_check_constraint(
            "ck_team_actions_comparison",
            _in("comparison", ("before_the_change", "observation_only")),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("team_actions") as batch:
        batch.drop_constraint("ck_team_actions_comparison", type_="check")
        batch.drop_constraint("ck_team_actions_implementation", type_="check")
        batch.drop_constraint("uq_team_actions_request", type_="unique")
        batch.drop_constraint("fk_team_actions_event_id_team_notes", type_="foreignkey")
        for column in (
            "implementation_at",
            "implementation",
            "comparison",
            "observe_ends_on",
            "observe_starts_on",
            "finding_evidence_id",
            "finding_report_id",
            "event_id",
            "token_id",
            "request_id",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("team_notes") as batch:
        batch.drop_constraint("ck_team_notes_category", type_="check")
        batch.drop_column("category")
