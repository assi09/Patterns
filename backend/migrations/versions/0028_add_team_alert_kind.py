"""Add an alert's kind (concern, improvement or change) and room for the note it lined up with

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-12 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("team_alerts") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=16), server_default="change", nullable=False)
        )
        batch.alter_column("text", existing_type=sa.String(length=300), type_=sa.String(length=400))


def downgrade() -> None:
    with op.batch_alter_table("team_alerts") as batch:
        batch.alter_column("text", existing_type=sa.String(length=400), type_=sa.String(length=300))
        batch.drop_column("kind")
