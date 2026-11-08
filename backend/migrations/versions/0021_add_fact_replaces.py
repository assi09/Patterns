"""Add what a memory replaces, so that keeping a change removes what is no longer true

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-08 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_facts") as batch:
        batch.add_column(sa.Column("replaces_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("memory_facts") as batch:
        batch.drop_column("replaces_id")
