"""TRINETRA remembers what it has already said (Final 2T, Phase 7).

`trinetra_notice_sends` is the claim ledger for TDS-credit notices and the Monday digest: one row per organization, kind and key
(a case and its revision, or an ISO week). The primary key is the claim, so two workers or a retried job never say a thing twice.
Expand-only: a new table. Downgrade drops it.

Revision ID: tr2t8_notice_sends
Revises: tr2t7_resolution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tr2t8_notice_sends"
down_revision = "tr2t7_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trinetra_notice_sends",
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(10), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("kind IN ('stale', 'missing', 'due', 'digest', 'bundle')", name="ck_trinetra_notice_sends_kind"),
    )


def downgrade() -> None:
    op.drop_table("trinetra_notice_sends")
