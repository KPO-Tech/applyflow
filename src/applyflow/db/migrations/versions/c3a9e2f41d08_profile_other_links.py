"""profile other links

Revision ID: c3a9e2f41d08
Revises: b7d41e5c9a20
Create Date: 2026-10-23 21:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3a9e2f41d08"
down_revision = "b7d41e5c9a20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("other_links", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("other_links")
