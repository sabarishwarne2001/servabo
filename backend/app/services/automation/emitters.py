"""Session J — where the engines tell automation that something happened.

Every function here is called from the place the thing happens (GST import, the radar, legal holds, TruthMesh, Helm,
a request link, the sweeps, the manual-run route), inside that caller's transaction, and writes ONE internal trigger
event through `outbox_service.emit_trigger`:

  * ONCE PER OCCURRENCE. A row in `automation_event_marks` (workspace, key) is inserted first. If it already exists the
    occurrence was announced and nothing is written. The mark and the event live and die together: a caller that rolls
    back loses both.
  * ONLY WHEN SOMEONE LISTENS. A workspace with no active rule on the event gets no event row and no job, so a busy
    engine adds no cost where nobody asked. (A rule made later sees the next occurrence; the sweeps also catch up on
    what is already true, because their marks are only written when an event is.)
  * NOTHING SENSITIVE. A payload carries ids, figures (amounts as integer micros with their currency), dates, states and
    short names the rule's author could already see. Never document text, a bank account, an email address.
  * NEVER A PUBLIC EVENT. The names are all `trigger.*`, which can never be in the webhook vocabulary. The five GST and
    run events customers can subscribe to are written beside them by `public_events.py`, under their own names.

A failure to write an event is logged and dropped: an engine's own work never fails because a rule could not hear of it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.services.automation import public_events

logger = logging.getLogger("app.services.automation.emitters")

GST_RETURN_IMPORTED = "trigger.gst.return_imported"
GST_WAITING = "trigger.gst.waiting_for_supplier"
GST_REVERSAL = "trigger.gst.reversal_risk"
PAYMENT_RISK = "trigger.payment_risk.flagged"
HOLD_PLACED = "trigger.legal_hold.placed"
HOLD_RELEASED = "trigger.legal_hold.released"
CONFLICT_OPENED = "trigger.truthmesh.conflict_opened"
CONFLICT_RESOLVED = "trigger.truthmesh.conflict_resolved"
SCHEDULE_DAILY = "trigger.schedule.daily"
SCHEDULE_WEEKLY = "trigger.schedule.weekly"
MANUAL = "trigger.manual"
HELM_BREACHED = "trigger.helm.mandate_breached"
HELM_APPROVAL = "trigger.helm.approval_needed"
RECEIVED_BY_LINK = "trigger.document.received_by_link"
#: Final session 2T (Phase 7.6): TDS credit. Written by `app/services/trinetra/events.py` through `emit_once` below.
TRINETRA_GAP_FOUND = "trigger.trinetra.case.gap_found"
TRINETRA_EVIDENCE_STALE = "trigger.trinetra.case.evidence_stale"
TRINETRA_CLOSED = "trigger.trinetra.case.closed"

WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def listening(db: Session, workspace_id: uuid.UUID, event_type: str) -> bool:
    """True when the workspace has at least one active rule on the event."""
    from app.models.automation import AutomationRule
    from app.models.automation_trigger import AutomationRuleTrigger

    return db.execute(
        select(AutomationRule.id)
        .join(AutomationRuleTrigger, AutomationRuleTrigger.rule_id == AutomationRule.id)
        .where(
            AutomationRuleTrigger.workspace_id == workspace_id,
            AutomationRuleTrigger.event_type == event_type,
            AutomationRule.is_active.is_(True),
            AutomationRule.deleted_at.is_(None),
        )
        .limit(1)
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
    """Announce one occurrence, once. Returns the outbox event, or None (nobody listens, or already announced)."""
    from app.models.automation_trigger import AutomationEventMark
    from app.services import outbox_service

    try:
        if not listening(db, workspace_id, event_type):
            return None
        with db.begin_nested():
            inserted = db.execute(
                pg_insert(AutomationEventMark)
                .values(workspace_id=workspace_id, mark_key=mark_key[:200], event_type=event_type)
                .on_conflict_do_nothing(index_elements=["workspace_id", "mark_key"])
                .returning(AutomationEventMark.workspace_id)
            ).first()
            if inserted is None:
                return None
            return outbox_service.emit_trigger(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                event_type=event_type,
                payload=payload,
                resource_id=resource_id,
                idempotency_key=f"{event_type}:{mark_key}"[:200],
            )
    except Exception:  # noqa: BLE001 - an engine's own work never fails because a rule could not hear of it
        logger.exception("automation.emit_failed", extra={"event_type": event_type, "workspace_id": str(workspace_id)})
        return None


def _micros(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _day(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, (date, datetime)) else None


# ---------------------------------------------------------------------------------------------------- GST Credit


def gst_return_imported(
    db: Session, *, workspace: Any, gstin: str, period: str, return_id: uuid.UUID, records: int, replaced: bool,
) -> Optional[Any]:
    """A GSTR-2B finished importing and was matched (the caller has recomputed). Once per import."""
    from sqlalchemy import func

    from app.models.gst import GstMatch
    from app.services.gst import vocabulary as v

    waiting_count, waiting_micros = db.execute(
        select(func.count(), func.coalesce(func.sum(GstMatch.value_micros), 0)).where(
            GstMatch.workspace_id == workspace.id, GstMatch.gstin == gstin, GstMatch.status == v.WAITING_FOR_SUPPLIER)
    ).one()
    differences = db.execute(
        select(func.count()).where(
            GstMatch.workspace_id == workspace.id, GstMatch.gstin == gstin,
            GstMatch.status == v.MATCHED_WITH_DIFFERENCES)
    ).scalar_one()
    payload = {"gstin": gstin, "period": period, "records": int(records), "waiting_count": int(waiting_count),
               "waiting_micros": int(waiting_micros or 0), "currency": "INR", "differences": int(differences),
               "replaced": bool(replaced), "return_id": str(return_id)}
    public = public_events.gst_return_imported(db, workspace=workspace, payload=payload, return_id=return_id)
    internal = emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=GST_RETURN_IMPORTED,
        mark_key=f"gst.return:{return_id}", payload=payload,
    )
    return internal if internal is not None else public


def gst_waiting_for_supplier(
    db: Session, *, workspace: Any, row: Any, work_item_id: uuid.UUID, days_waiting: int, threshold_days: int,
) -> Optional[Any]:
    public = public_events.gst_supplier_not_reported(
        db, workspace=workspace, row=row, work_item_id=work_item_id, days_waiting=days_waiting, threshold_days=threshold_days)
    internal = emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=GST_WAITING,
        mark_key=f"gst.waiting:{row.gstin}:{work_item_id}:{threshold_days}", resource_id=work_item_id,
        payload={"work_item_id": str(work_item_id), "gstin": row.gstin, "supplier_name": row.supplier_name or "",
                 "supplier_gstin": row.supplier_gstin or "", "invoice_number": row.doc_number or "",
                 "amount_micros": _micros(row.value_micros), "currency": "INR", "days_waiting": int(days_waiting),
                 "threshold_days": int(threshold_days)},
    )
    return internal if internal is not None else public


def gst_reversal_risk(
    db: Session, *, workspace: Any, row: Any, work_item_id: uuid.UUID, age_days: int, reversal_date: date,
    limit_days: int, warn_at_days: int,
) -> Optional[Any]:
    public = public_events.gst_invoice_at_risk(
        db, workspace=workspace, row=row, work_item_id=work_item_id, age_days=age_days, reversal_date=reversal_date,
        limit_days=limit_days, warn_at_days=warn_at_days)
    internal = emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=GST_REVERSAL,
        mark_key=f"gst.reversal:{row.gstin}:{work_item_id}:{warn_at_days}", resource_id=work_item_id,
        payload={"work_item_id": str(work_item_id), "gstin": row.gstin, "supplier_name": row.supplier_name or "",
                 "supplier_gstin": row.supplier_gstin or "", "invoice_number": row.doc_number or "",
                 "amount_micros": _micros(row.tax_micros), "currency": "INR", "age_days": int(age_days),
                 "days_left": max(0, int(limit_days) - int(age_days)), "reversal_date": reversal_date.isoformat()},
    )
    return internal if internal is not None else public


# ------------------------------------------------------------------------------------------------ payment risk


def payment_risk_flagged(db: Session, *, flag_id: uuid.UUID, role: Any, kind: str, severity: str) -> Optional[Any]:
    return emit_once(
        db, organization_id=role.organization_id, workspace_id=role.workspace_id, event_type=PAYMENT_RISK,
        mark_key=f"payment_risk:{flag_id}", resource_id=role.work_item_id,
        payload={"work_item_id": str(role.work_item_id), "flag_id": str(flag_id), "kind": kind, "severity": severity,
                 "vendor": role.vendor_key or "", "amount_micros": _micros(role.total_micros),
                 "currency": role.currency or None},
    )


# ---------------------------------------------------------------------------------------------------- legal holds


def legal_hold(db: Session, *, hold: Any, workspace_id: Optional[uuid.UUID], placed: bool) -> Optional[Any]:
    """A hold was placed or released. A document hold names only the document, so its workspace is looked up."""
    from app.models.work_item import WorkItem

    workspace_id = workspace_id or hold.workspace_id
    if workspace_id is None and hold.work_item_id is not None:
        workspace_id = db.execute(select(WorkItem.workspace_id).where(WorkItem.id == hold.work_item_id)
                                  ).scalar_one_or_none()
    if workspace_id is None:
        return None
    return emit_once(
        db, organization_id=hold.organization_id, workspace_id=workspace_id,
        event_type=HOLD_PLACED if placed else HOLD_RELEASED,
        mark_key=f"legal_hold:{hold.id}:{'placed' if placed else 'released'}",
        # `document_id`, not `work_item_id`: a hold is not one document's trigger, and the handler would hold an
        # announcement back while that document waits for a reviewer.
        payload={"hold_id": str(hold.id), "scope": "DOCUMENT" if hold.work_item_id else "WORKSPACE",
                 "document_id": str(hold.work_item_id) if hold.work_item_id else None,
                 "reason": hold.reason or "", "reference": hold.reference or "",
                 "placed_by": "A person in your workspace"},
    )


# ------------------------------------------------------------------------------------------------------ TruthMesh


def truthmesh_conflict(
    db: Session, *, conflict: Any, opened: bool, how: Optional[str] = None, when: Optional[datetime] = None,
) -> Optional[Any]:
    """`when` tells one opening (or resolution) of a conflict from the next: a conflict that cleared and came back is a
    second occurrence."""
    when = when or (conflict.first_seen_at if opened else conflict.resolved_at) or datetime.utcnow()
    return emit_once(
        db, organization_id=conflict.organization_id, workspace_id=conflict.workspace_id,
        event_type=CONFLICT_OPENED if opened else CONFLICT_RESOLVED,
        mark_key=f"truthmesh:{conflict.id}:{'opened' if opened else 'resolved'}:{when.isoformat()}",
        payload={"conflict_id": str(conflict.id), "kind": conflict.kind, "severity": conflict.severity,
                 "title": (conflict.title or "")[:200], "documents": len(conflict.work_item_ids or []),
                 "exposure_micros": _micros(conflict.exposure_micros), "currency": conflict.currency,
                 **({"how": how or "RESOLVED"} if not opened else {})},
    )


# --------------------------------------------------------------------------------------------------- schedules


def schedule(db: Session, *, workspace: Any, weekly: bool, local_date: date) -> Optional[Any]:
    kind = "weekly" if weekly else "daily"
    return emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id,
        event_type=SCHEDULE_WEEKLY if weekly else SCHEDULE_DAILY,
        mark_key=f"schedule.{kind}:{local_date.isoformat()}",
        payload={"local_date": local_date.isoformat(), "weekday": WEEKDAYS[local_date.weekday()]},
    )


# ------------------------------------------------------------------------------------------------------- manual


def manual(db: Session, *, workspace: Any, work_item_id: uuid.UUID, rule_id: uuid.UUID) -> Optional[Any]:
    """One press of "Run a rule on this document". Every press is an occurrence of its own."""
    return emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=MANUAL,
        mark_key=f"manual:{rule_id}:{work_item_id}:{uuid.uuid4()}", resource_id=work_item_id,
        payload={"work_item_id": str(work_item_id), "rule_id": str(rule_id),
                 "requested_by": "A workspace admin"},
    )


# ------------------------------------------------------------------------------------------------------- Helm


def helm_mandate_breached(
    db: Session, *, book: Any, plan: Any, instrument: dict[str, Any], previous_state: Optional[str],
) -> Optional[Any]:
    if book.workspace_id is None:
        return None
    mandate_id = str(instrument.get("mandate_id"))
    return emit_once(
        db, organization_id=book.organization_id, workspace_id=book.workspace_id, event_type=HELM_BREACHED,
        mark_key=f"helm.breach:{plan.id}:{mandate_id}",
        payload={"book_id": str(book.id), "plan_id": str(plan.id), "mandate_id": mandate_id,
                 "template": instrument.get("template") or "", "kind": instrument.get("kind") or "",
                 "previous_state": previous_state or "", "items": len(instrument.get("items") or [])},
    )


def helm_approval_needed(db: Session, *, book: Any, action: Any) -> Optional[Any]:
    if book.workspace_id is None:
        return None
    return emit_once(
        db, organization_id=book.organization_id, workspace_id=book.workspace_id, event_type=HELM_APPROVAL,
        mark_key=f"helm.approval:{action.id}",
        payload={"book_id": str(book.id), "action_id": str(action.id), "kind": action.kind,
                 "amount_micros": _micros(action.amount_micros), "currency": action.currency,
                 "run_date": _day(action.run_date)},
    )


# --------------------------------------------------------------------------------------------- request links


def document_received_by_link(db: Session, *, request: Any, work_item_id: uuid.UUID, case_title: str) -> Optional[Any]:
    return emit_once(
        db, organization_id=request.organization_id, workspace_id=request.workspace_id, event_type=RECEIVED_BY_LINK,
        mark_key=f"request_link:{request.id}", resource_id=work_item_id,
        payload={"work_item_id": str(work_item_id), "request_id": str(request.id),
                 "document_type": request.document_type, "recipient": request.recipient_label or "",
                 "case_title": (case_title or "")[:200]},
    )


__all__ = [
    "document_received_by_link",
    "emit_once",
    "gst_reversal_risk",
    "gst_return_imported",
    "gst_waiting_for_supplier",
    "helm_approval_needed",
    "helm_mandate_breached",
    "legal_hold",
    "listening",
    "manual",
    "payment_risk_flagged",
    "schedule",
    "truthmesh_conflict",
]
