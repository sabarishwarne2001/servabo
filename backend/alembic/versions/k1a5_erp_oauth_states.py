"""Zoho Books "Connect": the short-lived, single-use sign-in state (Final session 1, 3C).

When a customer clicks "Connect Zoho Books" the app signs a state (workspace, person, data centre, an expiry) and keeps its nonce
here; Zoho sends the same state back to the callback, which accepts it once. The row is the "single use": the callback marks it used
with one conditional update, so a replayed or copied callback finds nothing to take. Expand-only: a new table. Downgrade drops it.

Revision ID: k1a5_erp_oauth_states
Revises: k1a4_gst_notice_sends
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k1a5_erp_oauth_states"
down_revision = "k1a4_gst_notice_sends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_oauth_states",
        sa.Column("nonce", sa.String(64), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(16), nullable=False, server_default="zoho"),
        sa.Column("data_centre", sa.String(4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_erp_oauth_states_expires", "erp_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_erp_oauth_states_expires", table_name="erp_oauth_states")
    op.drop_table("erp_oauth_states")
