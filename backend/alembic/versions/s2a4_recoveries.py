"""Recoveries (Final session 2A, Phase 6; N-191): money issues from Found to Being fixed to Verified.

`recovery_issues`: the state each engine cannot hold for itself (the first time an issue was found, its owner, a due date a
person set where the law and the terms give none, and a person's "Not money: <reason>"), one row per issue, keyed by
what it is about (`subject_key`) so an engine that rebuilds its rows (GST matching) never loses it. The facts (amounts,
documents, the closure evidence) stay in the engines' own tables; `services/recoveries` reads them.

`recovery_outcomes`: the outcomes Recoveries proves, counted once. `dedupe_key` is the same key Helm's value ledger uses
(`helm/value.dedupe_key`), so an outcome both could claim is counted once (Helm's row wins); `withdrawn_at` takes an
outcome off when its evidence is undone.

Expand-only: two new tables. Downgrade drops them.

Revision ID: s2a4_recoveries
Revises: s2a3_counterparty_contact_source
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "s2a4_recoveries"
down_revision = "s2a3_counterparty_contact_source"
branch_labels = None
depends_on = None

KINDS = "('GST_CREDIT', 'DUPLICATE', 'OVERCHARGE', 'STATEMENT_DIFFERENCE', 'PAYMENT_DEADLINE')"
STATES = "('FOUND', 'BEING_FIXED', 'VERIFIED', 'NOT_MONEY', 'CLOSED')"
CATEGORIES = "('ITC_SECURED', 'OVERCHARGE_RECOVERED', 'DUPLICATE_BLOCKED', 'LATE_FEE_AVOIDED')"


def upgrade() -> None:
    op.create_table(
        "recovery_issues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("subject_key", sa.String(200), nullable=False),
        sa.Column("work_item_id", UUID(as_uuid=True), sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(12), nullable=False, server_default=sa.text("'FOUND'")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("exposure_micros", sa.BigInteger(), nullable=True),
        sa.Column("found_exposure_micros", sa.BigInteger(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_basis", sa.String(80), nullable=True),
        sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("closed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("first_found_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("workspace_id", "kind", "subject_key", name="uq_recovery_issues_subject"),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_recovery_issues_kind"),
        sa.CheckConstraint(f"state IN {STATES}", name="ck_recovery_issues_state"),
        sa.CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="ck_recovery_issues_currency"),
    )
    op.create_index("ix_recovery_issues_workspace_state", "recovery_issues", ["workspace_id", "state"])
    op.create_index("ix_recovery_issues_organization", "recovery_issues", ["organization_id"])
    op.create_table(
        "recovery_outcomes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_id", UUID(as_uuid=True), sa.ForeignKey("recovery_issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_item_id", UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_recovery_outcomes_dedupe_key"),
        sa.CheckConstraint(f"category IN {CATEGORIES}", name="ck_recovery_outcomes_category"),
        sa.CheckConstraint("amount_micros > 0", name="ck_recovery_outcomes_positive"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_recovery_outcomes_currency"),
    )
    op.create_index("ix_recovery_outcomes_workspace_occurred", "recovery_outcomes", ["workspace_id", "occurred_on"])
    op.create_index("ix_recovery_outcomes_issue", "recovery_outcomes", ["issue_id"])


def downgrade() -> None:
    op.drop_index("ix_recovery_outcomes_issue", table_name="recovery_outcomes")
    op.drop_index("ix_recovery_outcomes_workspace_occurred", table_name="recovery_outcomes")
    op.drop_table("recovery_outcomes")
    op.drop_index("ix_recovery_issues_organization", table_name="recovery_issues")
    op.drop_index("ix_recovery_issues_workspace_state", table_name="recovery_issues")
    op.drop_table("recovery_issues")
