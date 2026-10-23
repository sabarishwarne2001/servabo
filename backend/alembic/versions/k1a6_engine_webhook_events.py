"""The engines' public webhook events (Final session 1, Phase 6): the vocabularies.

Two CHECK constraints pin the webhook vocabulary into the database, and each refuses the five new names:

    ck_webhook_endpoints_event_types_vocabulary   what an endpoint may subscribe to: + the five events
    ck_webhook_deliveries_event_type_vocabulary   what a delivery row may carry: + the five events

    gst.return.imported        a GSTR-2B finished importing and was matched
    gst.invoice.at_risk        an unpaid invoice is nearing the 180-day reversal rule
    gst.supplier.not_reported  an invoice is in the books and in no imported GSTR-2B
    automation.run.failed      a workflow run failed, timed out or ran out of budget
    automation.run.held        a workflow run was held back (paused, throttled, cooldown)

`ck_outbox_events_visibility_vocabulary` is NOT touched: it pins the INTERNAL names only, and a PUBLIC event may carry
any name that is not internal.

Each list is written out in full, not imported, for the reason ARCH-37's migration gives: a migration that imports the
live set silently changes what it did the next time the set changes. Expand only. The downgrade first takes the five
names out of the rows that carry them, then narrows the CHECKs: their deliveries go (their attempts cascade); an
endpoint that listened to nothing but these goes too, since an endpoint must listen to at least one event
(`ck_webhook_endpoints_event_types_non_empty`), and every other endpoint keeps its other events.

Revision ID: k1a6_engine_webhook_events
Revises: k1a5_erp_oauth_states
"""

from __future__ import annotations

from alembic import op

revision = "k1a6_engine_webhook_events"
down_revision = "k1a5_erp_oauth_states"
branch_labels = None
depends_on = None

#: h1a4_helm_api_vocabulary.EVENTS_BEFORE + HELM_EVENTS, unchanged.
EVENTS_BEFORE: tuple[str, ...] = (
    "organization.updated",
    "member.invited",
    "member.joined",
    "member.role_changed",
    "member.deactivated",
    "member.reactivated",
    "invitation.created",
    "invitation.accepted",
    "invitation.rejected",
    "invitation.revoked",
    "invitation.expired",
    "workspace.created",
    "workspace.updated",
    "workspace.archived",
    "workspace.restored",
    "work_item.created",
    "work_item.updated",
    "work_item.deleted",
    "document.queued",
    "document.processing",
    "document.completed",
    "document.failed",
    "procurement.completed",
    "procurement.approved",
    "procurement.disputed",
    "anomaly.detected",
    "workflow.triggered",
    "helm.plan.ready",
    "helm.action.executed",
    "helm.mandate.breached",
)
ENGINE_EVENTS: tuple[str, ...] = (
    "gst.return.imported",
    "gst.invoice.at_risk",
    "gst.supplier.not_reported",
    "automation.run.failed",
    "automation.run.held",
)
#: Deliveries also carry the "Send test event" ping (p4a2); nobody subscribes to it.
TEST_EVENT = "webhook.test"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _events(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE webhook_deliveries DROP CONSTRAINT IF EXISTS ck_webhook_deliveries_event_type_vocabulary")
    op.execute("ALTER TABLE webhook_deliveries ADD CONSTRAINT ck_webhook_deliveries_event_type_vocabulary "
               f"CHECK (event_type IN ({_sql_list(values + (TEST_EVENT,))}))")
    op.execute("ALTER TABLE webhook_endpoints DROP CONSTRAINT IF EXISTS ck_webhook_endpoints_event_types_vocabulary")
    op.execute("ALTER TABLE webhook_endpoints ADD CONSTRAINT ck_webhook_endpoints_event_types_vocabulary "
               f"CHECK (event_types <@ ARRAY[{_sql_list(values)}]::varchar[])")


def upgrade() -> None:
    _events(EVENTS_BEFORE + ENGINE_EVENTS)


def downgrade() -> None:
    events = _sql_list(ENGINE_EVENTS)
    op.execute(f"DELETE FROM webhook_deliveries WHERE event_type IN ({events})")
    op.execute(f"DELETE FROM webhook_endpoints WHERE event_types <@ ARRAY[{events}]::varchar[]")
    op.execute("UPDATE webhook_endpoints SET event_types = ARRAY(SELECT e FROM unnest(event_types) AS e "
               f"WHERE e NOT IN ({events}))::varchar[] WHERE event_types && ARRAY[{events}]::varchar[]")
    _events(EVENTS_BEFORE)
