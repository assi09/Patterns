"""Add check-in alerts: the hr role, a team's HR contact, the third consent and the alert tables

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-25 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role", type_="check")
        batch.create_check_constraint("ck_users_role", "role IN ('member', 'supervisor', 'hr')")
    with op.batch_alter_table("teams") as batch:
        batch.add_column(sa.Column("hr_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_teams_hr_id_users", "users", ["hr_id"], ["id"], ondelete="SET NULL"
        )
    with op.batch_alter_table("team_memberships") as batch:
        batch.add_column(
            sa.Column("checkin_alerts", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(sa.Column("checkin_consent_version", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("checkin_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "checkin_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rule", sa.String(length=32), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('waiting', 'withdrawn', 'sent')", name="ck_checkin_alerts_status"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_checkin_alerts_team_id", "checkin_alerts", ["team_id"])
    op.create_index("ix_checkin_alerts_user_id", "checkin_alerts", ["user_id"])
    op.create_table(
        "checkin_marks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('checked_in', 'not_needed')",
            name="ck_checkin_marks_outcome",
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["checkin_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id", "user_id", name="uq_checkin_marks_recipient"),
    )
    op.create_index("ix_checkin_marks_alert_id", "checkin_marks", ["alert_id"])
    op.create_table(
        "checkin_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event IN ('raised', 'withdrawn', 'sent', 'opened', 'marked', 'reminded')",
            name="ck_checkin_events_event",
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["checkin_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_checkin_events_alert_id", "checkin_events", ["alert_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_checkin_events_alert_id", table_name="checkin_events")
    op.drop_table("checkin_events")
    op.drop_index("ix_checkin_marks_alert_id", table_name="checkin_marks")
    op.drop_table("checkin_marks")
    op.drop_index("ix_checkin_alerts_user_id", table_name="checkin_alerts")
    op.drop_index("ix_checkin_alerts_team_id", table_name="checkin_alerts")
    op.drop_table("checkin_alerts")
    with op.batch_alter_table("team_memberships") as batch:
        batch.drop_column("checkin_changed_at")
        batch.drop_column("checkin_consent_version")
        batch.drop_column("checkin_alerts")
    with op.batch_alter_table("teams") as batch:
        batch.drop_constraint("fk_teams_hr_id_users", type_="foreignkey")
        batch.drop_column("hr_id")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role", type_="check")
        batch.create_check_constraint("ck_users_role", "role IN ('member', 'supervisor')")
