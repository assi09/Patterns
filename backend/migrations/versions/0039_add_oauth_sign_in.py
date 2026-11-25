"""Add OAuth sign-in for MCP assistants: registered clients, sign-ins in progress, and the
expiring, refreshable tokens they lead to

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-26 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_table(
        "oauth_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_oauth_requests_client_id", "oauth_requests", ["client_id"])
    with op.batch_alter_table("access_tokens") as batch:
        batch.add_column(sa.Column("client_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("refresh_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_access_tokens_client_id_oauth_clients",
            "oauth_clients",
            ["client_id"],
            ["client_id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_access_tokens_refresh_hash", ["refresh_hash"])
        batch.create_index("ix_access_tokens_client_id", ["client_id"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("access_tokens") as batch:
        batch.drop_index("ix_access_tokens_client_id")
        batch.drop_constraint("uq_access_tokens_refresh_hash", type_="unique")
        batch.drop_constraint("fk_access_tokens_client_id_oauth_clients", type_="foreignkey")
        batch.drop_column("refresh_expires_at")
        batch.drop_column("refresh_hash")
        batch.drop_column("expires_at")
        batch.drop_column("client_id")
    op.drop_index("ix_oauth_requests_client_id", table_name="oauth_requests")
    op.drop_table("oauth_requests")
    op.drop_table("oauth_clients")
