"""Warning emails after a workspace or organization is deleted (Final session 2A, Phase 4; N-164).

`deletion_notice_sends`: one row per warning sent, so a retried or doubled job never sends it twice. `kind` is `ARCHIVED`
(sent at once: "will be erased on <date>; restore until then") or `LAST_CHANCE` (5 days before the purge). The key holds
the archive moment, so a workspace restored and deleted again is warned again.

Expand-only: a new table. Downgrade drops it.

Revision ID: s2a2_deletion_notice_sends
Revises: s2a1_safety_job_runs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "s2a2_deletion_notice_sends"
down_revision = "s2a1_safety_job_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deletion_notice_sends",
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("scope_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('ARCHIVED', 'LAST_CHANCE')", name="ck_deletion_notice_sends_kind"),
        sa.CheckConstraint("scope_type IN ('WORKSPACE', 'ORGANIZATION')", name="ck_deletion_notice_sends_scope"),
    )
    op.create_index("ix_deletion_notice_sends_organization", "deletion_notice_sends", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_deletion_notice_sends_organization", table_name="deletion_notice_sends")
    op.drop_table("deletion_notice_sends")
