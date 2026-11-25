"""Give Google Calendar its own sign-in, apart from Google Health's

Google's Health API refuses a token that also carries the calendar permission, so a person who
connected their calendar through the shared sign-in could no longer sync their health data. The
calendar gets its own table; a shared token that has the calendar permission is moved there (it
still works for the calendar) and the health sign-in is marked for reconnecting, health only.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-25 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CALENDAR = "https://www.googleapis.com/auth/calendar.readonly"


def upgrade() -> None:
    """Upgrade schema."""
    table = op.create_table(
        "calendar_connections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_token", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    google = sa.table(
        "google_connections",
        sa.column("user_id", sa.Uuid()),
        sa.column("encrypted_token", sa.LargeBinary()),
        sa.column("scopes", sa.JSON()),
        sa.column("status", sa.String()),
        sa.column("connected_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    for row in connection.execute(sa.select(google)).mappings().all():
        if CALENDAR not in (row["scopes"] or []):
            continue
        connection.execute(
            table.insert().values(
                user_id=row["user_id"],
                encrypted_token=row["encrypted_token"],
                scopes=[CALENDAR],
                status=row["status"],
                connected_at=row["connected_at"],
            )
        )
        connection.execute(
            google.update()
            .where(google.c.user_id == row["user_id"])
            .values(
                status="reconnect_needed",
                scopes=[s for s in row["scopes"] if s != CALENDAR],
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("calendar_connections")
