"""job country

Revision ID: b7d41e5c9a20
Revises: 9f3c2a71b4d0
Create Date: 2026-10-23 17:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d41e5c9a20"
down_revision = "9f3c2a71b4d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("country", sa.String(length=2), nullable=True))
        batch.create_index("ix_jobs_country", ["country"])
    # Rattrapage des offres déjà collectées, à partir de leur localisation.
    from applyflow.geo import detect_country

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, location FROM jobs WHERE location IS NOT NULL")
    ).fetchall()
    for job_id, location in rows:
        code = detect_country(location)
        if code:
            connection.execute(
                sa.text("UPDATE jobs SET country = :code WHERE id = :id"),
                {"code": code, "id": job_id},
            )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_country")
        batch.drop_column("country")
