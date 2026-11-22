"""Add who planned a team change and which one

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-22 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("team_actions") as batch:
        batch.add_column(
            sa.Column("source", sa.String(length=16), server_default="agent", nullable=False)
        )
        batch.add_column(sa.Column("play", sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("team_actions") as batch:
        batch.drop_column("play")
        batch.drop_column("source")
