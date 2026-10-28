"""What TRINETRA announces to the rest of Servabo (Final 2T, Phase 7.6 and 7.7), once per occurrence.

  trinetra.case.gap_found       a case's tax is not (fully) in the statement: a possible gap, an amount mismatch, a suggestion nobody
                                has confirmed. Once per case revision.
  trinetra.case.evidence_stale  a confirmed withholding lost its evidence. Once per case revision.
  trinetra.case.closed          a case was closed (reviewed by the accountant, explained, withdrawn or left unresolved).
  trinetra.case.reviewed        any decision on a case (Final 2A). Enterprise webhook only.

TWO AUDIENCES, ONE MOMENT.
  * AUTOMATION (Business and Enterprise, `trigger.trinetra.case.*`): internal events through `emitters.emit_once`. They carry the
    invoice reference and the customer's name, which the author of a rule could already see on the case. A rule on them may notify,
    assign, tag and chat; it can NEVER send an inquiry, an email or a webhook (the trigger lists the actions it allows).
  * PUBLIC WEBHOOKS (Enterprise, `capability.trinetra_all_workspaces`): ids, states and amounts only (amounts as integer micros with
    their currency). Never a PAN, a TAN, an invoice number or a customer's name.

Both are written only when someone listens, in the caller's transaction, and a failure to write is logged and dropped.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable, Optional

from app.api.capability_gate import has_capability
from app.services.automation import emitters
from app.services.automation import public_events
from app.services.automation.public_events import emit_once
from app.services.trinetra import mode

logger = logging.getLogger("app.services.trinetra.events")

GAP_FOUND = "trinetra.case.gap_found"
EVIDENCE_STALE = "trinetra.case.evidence_stale"
CLOSED = "trinetra.case.closed"
REVIEWED = "trinetra.case.reviewed"
#: The internal (automation) event names: the public name behind the `trigger.` namespace.
TRIGGER = {GAP_FOUND: emitters.TRINETRA_GAP_FOUND, EVIDENCE_STALE: emitters.TRINETRA_EVIDENCE_STALE, CLOSED: emitters.TRINETRA_CLOSED}
ENTERPRISE = "capability.trinetra_all_workspaces"
CLOSED_STATES = ("EXPLAINED", "WITHDRAWN", "CA_REVIEWED", "UNRESOLVED")


def _public_enabled(db, workspace) -> bool:
    return has_capability(db, organization_id=workspace.organization_id, capability_key=ENTERPRISE)


def reviewed(db, workspace, row):
    """Called after every decision on a case: the Enterprise `reviewed` webhook, and `closed` when the decision closed it."""
    if workspace.is_sample or not mode.live_for(db, workspace.organization_id):
        return None
    out = None
    if _public_enabled(db, workspace):
        out = emit_once(
            db,
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            event_type=REVIEWED,
            mark_key=f"trinetra:{row.id}:{row.revision}",
            resource_id=row.id,
            payload={
                "workspace_id": str(workspace.id),
                "case_id": str(row.id),
                "revision": row.revision,
                "state": row.state,
            },
        )
    if row.state in CLOSED_STATES:
        closed(db, workspace, row)
    return out


def _public_payload(workspace, row, *, state: str, status: Optional[str], micros: Optional[int]) -> dict[str, Any]:
    return {"workspace_id": str(workspace.id), "case_id": str(row.id), "revision": row.revision, "year": row.year, "state": state,
            "status": status, "amount_micros": micros, "currency": "INR"}


def _announce(db, workspace, row, name: str, *, status: Optional[str], micros: Optional[int], reference: str, customer: str, days: int):
    base = _public_payload(workspace, row, state=row.state, status=status, micros=micros)
    internal = emitters.emit_once(
        db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=TRIGGER[name],
        mark_key=f"{name}:{row.id}:{row.revision}", resource_id=row.work_item_id,
        payload={**base, "work_item_id": str(row.work_item_id), "reference": reference, "customer": customer,
                 "days_open": int(days)})
    if _public_enabled(db, workspace):
        emit_once(db, organization_id=workspace.organization_id, workspace_id=workspace.id, event_type=name,
                  mark_key=f"{name}:{row.id}:{row.revision}", resource_id=row.id, payload=base)
    return internal


def closed(db, workspace, row):
    from app.services.trinetra import service

    try:
        item = service.view(db, workspace, row)
        return _announce(db, workspace, row, CLOSED, status=item["status"], micros=row.expected_micros,
                         reference=row.reference, customer=row.counterparty, days=item["age_days"])
    except Exception:  # noqa: BLE001 - an announcement never fails the decision that caused it
        logger.warning("trinetra.closed_event_failed", exc_info=True)
        return None


def listening(db, workspace) -> dict[str, bool]:
    """For each event, whether anyone would hear it: a rule in the workspace, or (Enterprise) an endpoint of the organization."""
    public = _public_enabled(db, workspace)
    return {name: emitters.listening(db, workspace.id, TRIGGER[name])
            or (public and public_events.listening(db, workspace.organization_id, name))
            for name in (GAP_FOUND, EVIDENCE_STALE)}


def detected(db, workspace, items: Iterable[dict], gap_statuses: Iterable[str], evidence_lost, open_states, expected_of) -> int:
    """The gap-found and evidence-stale occurrences among these case views. Returns how many were written."""
    from app.models.trinetra import TrinetraCredit

    heard = listening(db, workspace)
    if not any(heard.values()):
        return 0
    written = 0
    gap_statuses = tuple(gap_statuses)
    for item in items:
        if item["review_state"] not in open_states:
            continue
        wanted = []
        if heard[EVIDENCE_STALE] and evidence_lost(item):
            wanted.append((EVIDENCE_STALE, expected_of(item)))
        if heard[GAP_FOUND] and item["status"] in gap_statuses and (item["gap_micros"] or 0) > 0:
            wanted.append((GAP_FOUND, item["gap_micros"]))
        for name, micros in wanted:
            row = db.get(TrinetraCredit, uuid.UUID(item["id"]))
            if row is None:
                continue
            if _announce(db, workspace, row, name, status=item["status"], micros=micros, reference=item["reference"],
                         customer=item["counterparty"], days=item["age_days"]) is not None:
                written += 1
    return written
