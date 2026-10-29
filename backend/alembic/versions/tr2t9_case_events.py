"""TRINETRA's case events (Final 2T, Phase 7.6 and 7.7): the vocabularies.

Three CHECK constraints pin event names into the database, and each refuses the new ones:

    ck_outbox_events_visibility_vocabulary       the INTERNAL names an automation rule listens to: + three `trigger.trinetra.case.*`
    ck_webhook_endpoints_event_types_vocabulary  what a webhook endpoint may subscribe to: + gap_found and closed
    ck_webhook_deliveries_event_type_vocabulary  what a delivery row may carry: the same two

    trinetra.case.gap_found       a case's tax is not (fully) in the statement            (Enterprise webhook; Business rule)
    trinetra.case.closed          a case was closed                                      (Enterprise webhook; Business rule)
    trigger.trinetra.case.evidence_stale   a confirmed withholding lost its evidence      (a rule only; never a webhook)

Each list is written out in full, not imported, as k1a6 and j1a1 did: a migration that imports the live set silently changes what
it did the next time the set changes. Expand only. The downgrade first removes the new names from the rows that carry them.

Revision ID: tr2t9_case_events
Revises: tr2t8_notice_sends
"""

from __future__ import annotations

from alembic import op

revision = "tr2t9_case_events"
down_revision = "tr2t8_notice_sends"
branch_labels = None
depends_on = None

#: The CHECK as j1a1_automation_triggers left it, pinned.
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
    "trigger.document.received_by_link",
    "trigger.gst.return_imported",
    "trigger.gst.reversal_risk",
    "trigger.gst.waiting_for_supplier",
    "trigger.helm.approval_needed",
    "trigger.helm.mandate_breached",
    "trigger.legal_hold.placed",
    "trigger.legal_hold.released",
    "trigger.manual",
    "trigger.obligation.due_soon",
    "trigger.obligation.overdue",
    "trigger.packet.split",
    "trigger.payment_risk.flagged",
    "trigger.posting.failed",
    "trigger.process.sla_at_risk",
    "trigger.procurement.approved",
    "trigger.procurement.completed",
    "trigger.procurement.disputed",
    "trigger.redaction.completed",
    "trigger.review.cleared",
    "trigger.schedule.daily",
    "trigger.schedule.weekly",
    "trigger.table.flagged",
    "trigger.truthmesh.conflict_opened",
    "trigger.truthmesh.conflict_resolved",
    "trigger.work_item.created",
    "trigger.work_item.reprocessed",
    "usage.aggregation_needed",
    "usage.recorded",
    "work_item.enriched",
    "work_item.field_changed",
    "work_item.verification_completed",
    "work_item.verification_disagreed",
)

NEW_INTERNAL: tuple[str, ...] = (
    "trigger.trinetra.case.closed",
    "trigger.trinetra.case.evidence_stale",
    "trigger.trinetra.case.gap_found",
)
INTERNAL_AFTER: tuple[str, ...] = INTERNAL_BEFORE + NEW_INTERNAL

#: The webhook vocabulary as tr1a1_credit_assurance left it, pinned.
PUBLIC_BEFORE: tuple[str, ...] = (
    "anomaly.detected",
    "automation.run.failed",
    "automation.run.held",
    "document.completed",
    "document.failed",
    "document.processing",
    "document.queued",
    "gst.invoice.at_risk",
    "gst.return.imported",
    "gst.supplier.not_reported",
    "helm.action.executed",
    "helm.mandate.breached",
    "helm.plan.ready",
    "invitation.accepted",
    "invitation.created",
    "invitation.expired",
    "invitation.rejected",
    "invitation.revoked",
    "member.deactivated",
    "member.invited",
    "member.joined",
    "member.reactivated",
    "member.role_changed",
    "organization.updated",
    "procurement.approved",
    "procurement.completed",
    "procurement.disputed",
    "trinetra.case.reviewed",
    "work_item.created",
    "work_item.deleted",
    "work_item.updated",
    "workflow.triggered",
    "workspace.archived",
    "workspace.created",
    "workspace.restored",
    "workspace.updated",
)

NEW_PUBLIC: tuple[str, ...] = (
    "trinetra.case.closed",
    "trinetra.case.gap_found",
)
PUBLIC_AFTER: tuple[str, ...] = PUBLIC_BEFORE + NEW_PUBLIC
#: Deliveries also carry the "Send test event" ping (p4a2); nobody subscribes to it.
TEST_EVENT = "webhook.test"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _visibility_check(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS ck_outbox_events_visibility_vocabulary")
    array = ", ".join(f"'{value}'::character varying" for value in values)
    op.execute(
        "ALTER TABLE outbox_events ADD CONSTRAINT ck_outbox_events_visibility_vocabulary CHECK ("
        f"((visibility::text = 'INTERNAL'::text AND event_type::text = ANY (ARRAY[{array}]::text[])) OR "
        f"(visibility::text = 'PUBLIC'::text AND event_type::text <> ALL (ARRAY[{array}]::text[]))))"
    )


def _events(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE webhook_deliveries DROP CONSTRAINT IF EXISTS ck_webhook_deliveries_event_type_vocabulary")
    op.execute("ALTER TABLE webhook_deliveries ADD CONSTRAINT ck_webhook_deliveries_event_type_vocabulary "
               f"CHECK (event_type IN ({_sql_list(values + (TEST_EVENT,))}))")
    op.execute("ALTER TABLE webhook_endpoints DROP CONSTRAINT IF EXISTS ck_webhook_endpoints_event_types_vocabulary")
    op.execute("ALTER TABLE webhook_endpoints ADD CONSTRAINT ck_webhook_endpoints_event_types_vocabulary "
               f"CHECK (event_types <@ ARRAY[{_sql_list(values)}]::varchar[])")


def upgrade() -> None:
    _visibility_check(INTERNAL_AFTER)
    _events(PUBLIC_AFTER)


def downgrade() -> None:
    internal = _sql_list(NEW_INTERNAL)
    op.execute(f"DELETE FROM outbox_events WHERE event_type IN ({internal})")
    _visibility_check(INTERNAL_BEFORE)
    events = _sql_list(NEW_PUBLIC)
    op.execute(f"DELETE FROM webhook_deliveries WHERE event_type IN ({events})")
    op.execute(f"DELETE FROM webhook_endpoints WHERE event_types <@ ARRAY[{events}]::varchar[]")
    op.execute("UPDATE webhook_endpoints SET event_types = ARRAY(SELECT e FROM unnest(event_types) AS e "
               f"WHERE e NOT IN ({events}))::varchar[] WHERE event_types && ARRAY[{events}]::varchar[]")
    _events(PUBLIC_BEFORE)
