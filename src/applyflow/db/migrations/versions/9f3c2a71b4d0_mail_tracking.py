"""mail tracking

Revision ID: 9f3c2a71b4d0
Revises: 008ce64763a3
Create Date: 2026-10-23 11:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9f3c2a71b4d0"
down_revision = "008ce64763a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("remote_id", sa.String(length=500), nullable=False),
        sa.Column("account", sa.String(length=255), nullable=False),
        sa.Column("folder", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("sender_email", sa.String(length=255), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=400), nullable=False),
        sa.Column("application_id", sa.String(length=32), nullable=True),
        sa.Column("match_reason", sa.String(length=400), nullable=True),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("ignored", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_id", name="uq_email_messages_remote"),
    )
    with op.batch_alter_table("email_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_email_messages_application_id"), ["application_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_email_messages_classification"), ["classification"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_email_messages_received_at"), ["received_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_email_messages_sender_email"), ["sender_email"], unique=False
        )

    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("followed_up_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_column("followed_up_at")
    op.drop_table("email_messages")
