"""Final session 1 (Phase 6) — the five engine events a customer's own systems can subscribe to.

    gst.return.imported       a GSTR-2B finished importing and was matched
    gst.invoice.at_risk       an unpaid purchase invoice is nearing the 180-day reversal rule
    gst.supplier.not_reported an invoice is in the books and in no imported GSTR-2B, after the waiting notice days
    automation.run.failed     a workflow run ended FAILED, TIMED_OUT or BUDGET_EXHAUSTED
    automation.run.held       a workflow run was held back (paused, throttled, cooldown) and never ran

These are the PUBLIC counterparts of the internal `trigger.*` events in `emitters.py`, written by the same callers at
the same moment, and they follow the same rules:

  * ONCE PER OCCURRENCE. A row in `automation_event_marks` (workspace, key) is inserted first, under a `public:` key so
    it can never collide with the internal mark for the same occurrence. If it exists the occurrence was announced.
  * ONLY WHEN SOMEONE LISTENS. No row is written unless an ACTIVE webhook endpoint of the organization is subscribed to
    the event, so an engine adds no cost where nobody asked.
  * IDS AND FIGURES ONLY. Amounts are integer micros with their currency, dates ISO, plus counts and state names.
    Never document text, a supplier's or customer's name, an invoice number, an error message or a rule's name: a
    webhook leaves the platform for whatever URL a tenant configured. The API serves the rest to whoever may read it.
  * ONE TRANSACTION. The mark and the outbox row are written in the caller's transaction (`outbox_service.emit` never
    commits), so a caller that rolls back loses both.
  * NEVER A REASON TO FAIL. A failure to write is logged and dropped: a GST import or a workflow run never fails because
    a webhook could not be queued.

`automation.` is a reserved internal namespace (`automation_events.INTERNAL_ONLY_PREFIXES`); the two `automation.run.*`
names are the only exceptions, listed one by one in `automation_events.PUBLIC_AUTOMATION_EVENTS`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

logger = logging.getLogger("app.services.automation.public_events")

GST_RETURN_IMPORTED = "gst.return.imported"
GST_INVOICE_AT_RISK = "gst.invoice.at_risk"
GST_SUPPLIER_NOT_REPORTED = "gst.supplier.not_reported"
RUN_FAILED = "automation.run.failed"
RUN_HELD = "automation.run.held"

#: The execution statuses that mean "did not finish what it set out to do" (the same three Run history counts).
FAILED_STATUSES = ("FAILED", "TIMED_OUT", "BUDGET_EXHAUSTED")


def _micros(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def listening(db: Session, organization_id: uuid.UUID, event_type: str) -> bool:
    """Is any ACTIVE endpoint of the organization subscribed to `event_type`?"""
    from app.models.webhook_endpoint import WebhookEndpoint, WebhookEndpointStatus

    return db.execute(
        select(WebhookEndpoint.id).where(
            WebhookEndpoint.organization_id == organization_id,
            WebhookEndpoint.status == WebhookEndpointStatus.ACTIVE,
            WebhookEndpoint.event_types.contains([event_type]),
        ).limit(1)
    ).first() is not None


def emit_once(
    db: Session,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    event_type: str,
    mark_key: str,
    payload: dict[str, Any],
    resource_id: Optional[uuid.UUID] = None,
) -> Optional[Any]:
    """Announce one occurrence to the organization's webhook endpoints, once. Returns the outbox event, or None
    (nobody listens, already announced, or the write failed and was logged)."""
    from app.models.automation_trigger import AutomationEventMark
    from app.services import outbox_service

    try:
        if not listening(db, organization_id, event_type):
            return None
        key = f"public:{mark_key}"[:200]
        with db.begin_nested():
            inserted = db.execute(
                pg_insert(AutomationEventMark)
                .values(workspace_id=workspace_id, mark_key=key, event_type=event_type)
                .on_conflict_do_nothing(index_elements=["workspace_id", "mark_key"])
                .returning(AutomationEventMark.workspace_id)
            ).first()
            if inserted is None:
                return None
            return outbox_service.emit(
                db,
                organization_id=organization_id,
                event_type=event_type,
                payload=payload,
                workspace_id=workspace_id,
                resource_id=resource_id,
                idempotency_key=f"{event_type}:{mark_key}"[:200],
            )
    except Exception:  # noqa: BLE001 - an engine's own work never fails because a webhook could not be queued
        logger.exception("webhook.public_emit_failed", extra={"event_type": event_type, "workspace_id": str(workspace_id)})
        return None


# ------------------------------------------------------------------------------------------------ GST credit


def gst_return_imported(db: Session, *, workspace: Any, payload: dict[str, Any], return_id: uuid.UUID) -> Optional[Any]:
    """`payload` is the figures the internal event already carries (they are all ids, counts and micros)."""
    return emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=GST_RETURN_IMPORTED,
        mark_key=f"gst.return:{return_id}", resource_id=return_id,
        payload={"workspace_id": str(workspace.id), **payload},
    )


def gst_invoice_at_risk(
    db: Session, *, workspace: Any, row: Any, work_item_id: uuid.UUID, age_days: int, reversal_date: date,
    limit_days: int, warn_at_days: int,
) -> Optional[Any]:
    return emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=GST_INVOICE_AT_RISK,
        mark_key=f"gst.reversal:{row.gstin}:{work_item_id}:{warn_at_days}", resource_id=work_item_id,
        payload={"workspace_id": str(workspace.id), "work_item_id": str(work_item_id), "gstin": row.gstin,
                 "supplier_gstin": row.supplier_gstin or "", "amount_micros": _micros(row.tax_micros), "currency": "INR",
                 "age_days": int(age_days), "days_left": max(0, int(limit_days) - int(age_days)),
                 "reversal_date": reversal_date.isoformat()},
    )


def gst_supplier_not_reported(
    db: Session, *, workspace: Any, row: Any, work_item_id: uuid.UUID, days_waiting: int, threshold_days: int,
) -> Optional[Any]:
    return emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id,
        event_type=GST_SUPPLIER_NOT_REPORTED,
        mark_key=f"gst.waiting:{row.gstin}:{work_item_id}:{threshold_days}", resource_id=work_item_id,
        payload={"workspace_id": str(workspace.id), "work_item_id": str(work_item_id), "gstin": row.gstin,
                 "supplier_gstin": row.supplier_gstin or "", "amount_micros": _micros(row.value_micros),
                 "currency": "INR", "days_waiting": int(days_waiting), "threshold_days": int(threshold_days)},
    )


# ------------------------------------------------------------------------------------------------ workflow runs


def run_payload(execution: Any) -> dict[str, Any]:
    return {
        "execution_id": str(execution.id), "rule_id": str(execution.rule_id), "workspace_id": str(execution.workspace_id),
        "work_item_id": str(execution.work_item_id) if execution.work_item_id else None,
        "status": execution.status.value if hasattr(execution.status, "value") else str(execution.status),
        "nodes_executed": int(execution.nodes_executed or 0), "actions_executed": int(execution.actions_executed or 0),
        "depth": int(execution.depth or 0),
    }


def run_failed(db: Session, *, execution: Any) -> Optional[Any]:
    """A run reached FAILED, TIMED_OUT or BUDGET_EXHAUSTED. Once per execution."""
    return emit_once(
        db, organization_id=execution.organization_id, workspace_id=execution.workspace_id, event_type=RUN_FAILED,
        mark_key=f"run.failed:{execution.id}", resource_id=execution.id, payload=run_payload(execution),
    )


def run_held(db: Session, *, execution: Any) -> Optional[Any]:
    """A run was recorded as held back (paused, throttled, cooldown) and never ran. Once per execution."""
    return emit_once(
        db, organization_id=execution.organization_id, workspace_id=execution.workspace_id, event_type=RUN_HELD,
        mark_key=f"run.held:{execution.id}", resource_id=execution.id, payload=run_payload(execution),
    )


__all__ = [
    "FAILED_STATUSES", "GST_INVOICE_AT_RISK", "GST_RETURN_IMPORTED", "GST_SUPPLIER_NOT_REPORTED", "RUN_FAILED", "RUN_HELD",
    "emit_once", "gst_invoice_at_risk", "gst_return_imported", "gst_supplier_not_reported", "listening", "run_failed",
    "run_held", "run_payload",
]
