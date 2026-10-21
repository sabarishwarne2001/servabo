"""The engines become automation triggers (Session J, Phase 2).

Three things, all expand-only:

1. `ck_outbox_events_visibility_vocabulary` admits the fourteen new INTERNAL trigger events (GST Credit, payment risk,
   legal holds, TruthMesh, schedules, a manual run, Helm, a document received through a request link). The list is
   written out in full, not imported, as arch37 and p4a1 did: a migration that imports the live set silently changes
   what it did the next time the set changes.
2. `automation_event_marks`: one row per (workspace, key), inserted in the same transaction as the event it guards, so
   a sweep that runs hourly emits "this invoice has waited 30 days" once, and keeps emitting nothing after the outbox
   prunes the old event. The outbox's own idempotency key cannot say that: published events are pruned.
3. `gst_settings.waiting_notice_days`: after how many days a purchase invoice still missing from every GSTR-2B is
   announced to the rules (1 to 365, default 30).

Downgrade: removes the marks table and the column, deletes any outbox row that carries a new name, and narrows the CHECK.

Revision ID: j1a1_automation_triggers
Revises: h1a7_monthly_receipt_sends
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "j1a1_automation_triggers"
down_revision = "h1a7_monthly_receipt_sends"
branch_labels = None
depends_on = None

#: The CHECK as p4a1_outbox_vocabulary_restore left it (40 names), pinned.
INTERNAL_BEFORE: tuple[str, ...] = (
    "automation.budget_exhausted",
    "automation.execution_completed",
    "billing.invoice_finalization_needed",
    "billing.seat_added",
    "billing.seat_removed",
    "billing.seat_sync_needed",
    "identity.domain_lapsed",
    "identity.domain_verified",
    "identity.idp_config_changed",
    "identity.jit_cap_reached",
    "identity.user_deprovisioned",
    "identity.user_provisioned",
    "identity.user_reactivated",
    "trigger.anomaly.detected",
    "trigger.assertion.held",
    "trigger.batch.completed",
    "trigger.case.completed",
    "trigger.case.inconsistent",
    "trigger.corroboration.discrepancies",
    "trigger.document.completed",
    "trigger.document.failed",
    "trigger.obligation.due_soon",
    "trigger.obligation.overdue",
    "trigger.packet.split",
    "trigger.posting.failed",
    "trigger.process.sla_at_risk",
    "trigger.procurement.approved",
    "trigger.procurement.completed",
    "trigger.procurement.disputed",
    "trigger.redaction.completed",
    "trigger.review.cleared",
    "trigger.table.flagged",
    "trigger.work_item.created",
    "trigger.work_item.reprocessed",
    "usage.aggregation_needed",
    "usage.recorded",
    "work_item.enriched",
    "work_item.field_changed",
    "work_item.verification_completed",
    "work_item.verification_disagreed",
)

NEW: tuple[str, ...] = (
    "trigger.document.received_by_link",
    "trigger.gst.reversal_risk",
    "trigger.gst.return_imported",
    "trigger.gst.waiting_for_supplier",
    "trigger.helm.approval_needed",
    "trigger.helm.mandate_breached",
    "trigger.legal_hold.placed",
    "trigger.legal_hold.released",
    "trigger.manual",
    "trigger.payment_risk.flagged",
    "trigger.schedule.daily",
    "trigger.schedule.weekly",
    "trigger.truthmesh.conflict_opened",
    "trigger.truthmesh.conflict_resolved",
)

INTERNAL_AFTER: tuple[str, ...] = INTERNAL_BEFORE + NEW


def _visibility_check(values: tuple[str, ...]) -> None:
    """Same shape as arch40_step0_review_vocabulary._visibility_check."""
    op.execute("ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS ck_outbox_events_visibility_vocabulary")
    array = ", ".join(f"'{value}'::character varying" for value in values)
    op.execute(
        "ALTER TABLE outbox_events ADD CONSTRAINT ck_outbox_events_visibility_vocabulary CHECK ("
        f"((visibility::text = 'INTERNAL'::text AND event_type::text = ANY (ARRAY[{array}]::text[])) OR "
        f"(visibility::text = 'PUBLIC'::text AND event_type::text <> ALL (ARRAY[{array}]::text[]))))"
    )


def upgrade() -> None:
    _visibility_check(INTERNAL_AFTER)
    op.create_table(
        "automation_event_marks",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mark_key", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "mark_key", name="pk_automation_event_marks"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE",
                                name="fk_automation_event_marks_workspace_id_workspaces"),
    )
    op.create_index("ix_automation_event_marks_created", "automation_event_marks", ["created_at"])
    op.add_column("gst_settings", sa.Column("waiting_notice_days", sa.Integer(), nullable=False, server_default="30"))
    op.create_check_constraint("ck_gst_settings_waiting_notice_days", "gst_settings",
                               "waiting_notice_days >= 1 AND waiting_notice_days <= 365")


def downgrade() -> None:
    op.drop_constraint("ck_gst_settings_waiting_notice_days", "gst_settings", type_="check")
    op.drop_column("gst_settings", "waiting_notice_days")
    op.drop_index("ix_automation_event_marks_created", table_name="automation_event_marks")
    op.drop_table("automation_event_marks")
    names = ", ".join(f"'{name}'" for name in NEW)
    op.execute(f"DELETE FROM outbox_events WHERE event_type IN ({names})")
    _visibility_check(INTERNAL_BEFORE)
