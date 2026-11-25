"""Add HR invitations: a supervisor invites the team's HR contact by email

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-25 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hr_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_hr_invites_team_id", "hr_invites", ["team_id"])
    op.create_index(
        "uq_hr_invites_open_team",
        "hr_invites",
        ["team_id"],
        unique=True,
        sqlite_where=sa.text("accepted_at IS NULL"),
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_hr_invites_open_team", table_name="hr_invites")
    op.drop_index("ix_hr_invites_team_id", table_name="hr_invites")
    op.drop_table("hr_invites")
