"""The monthly summary email is recorded once per organization and month (Session H, Part 3).

`monthly_receipt_sends` has one row per organization and month ("2026-09" for the summary sent on 1 October). The row is
written before anything is sent (an insert that does nothing when the row exists), so two workers or a retried job never
send a month twice; its `recipients` and `findings` are 0 when the month had nothing to say. Expand only: a new table.

Downgrade drops it.

Revision ID: h1a7_monthly_receipt_sends
Revises: h1a6_gst_credit_addon
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "h1a7_monthly_receipt_sends"
down_revision = "h1a6_gst_credit_addon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_receipt_sends",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("recipients", sa.Integer(), server_default="0", nullable=False),
        sa.Column("findings", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "period", name="pk_monthly_receipt_sends"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE",
                                name="fk_monthly_receipt_sends_organization_id_organizations"),
    )


def downgrade() -> None:
    op.drop_table("monthly_receipt_sends")
