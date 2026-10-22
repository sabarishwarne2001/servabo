"""GST notices and the Monday digest remember what they have said (Final session 1, 3A).

`gst_notice_sends` is the claim ledger: one row per organization, kind and key (an import, an invoice reaching 150 days, a month's
"suppliers have not reported", a month's IMS reminder, an ISO week's digest). The primary key is the claim, so two workers or a
retried job never say a thing twice. Expand-only: a new table. Downgrade drops it.

Revision ID: k1a4_gst_notice_sends
Revises: k1a3_inbound_email
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "k1a4_gst_notice_sends"
down_revision = "k1a3_inbound_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gst_notice_sends",
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("kind IN ('import', 'window', 'supplier', 'ims', 'digest')", name="ck_gst_notice_sends_kind"),
    )


def downgrade() -> None:
    op.drop_table("gst_notice_sends")
