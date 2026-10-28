"""Narrow read-only annotation and send-time hold; never writes a Helm settlement."""

import uuid
from dataclasses import dataclass

from app.models.trinetra import TrinetraCredit
from app.models.work_item import WorkItem
from app.models.document_role import DocumentRole
from app.services.trinetra.projection import reviewed_withholding
from app.services.trinetra import versions


@dataclass(frozen=True)
class Withholding:
    """A confirmed withholding on one invoice: the case, and the reviewed tax amount (None: not known now)."""

    case_id: str
    reviewed_micros: int | None


def _value(row, facts) -> dict:
    """The case's evidence as of now (read-only; the same rules as the case view)."""
    evidence = [
        {
            **e,
            "current": bool(
                (doc := facts.get(uuid.UUID(e["work_item_id"])))
                and doc.evidence == e["source_version"]
            ),
        }
        for e in (row.review or {}).get("evidence", [])
    ]
    source = facts.get(row.work_item_id)
    value = {
        "source_current": bool(source and source.invoice == row.source_version),
        "review": {"evidence": evidence},
    }
    for kind, key in (
        ("DEDUCTOR_ADVICE", "advice_micros"),
        ("ACCOUNTING_RECORD", "booked_micros"),
    ):
        amounts = [
            e["amount_micros"]
            for e in evidence
            if e["kind"] == kind
            and e["current"]
            and e.get("amount_micros") is not None
        ]
        value[key] = sum(amounts) if amounts else None
    return value


def _confirmed(db, organization_id, work_item_ids, workspace_ids=None):
    query = db.query(TrinetraCredit).filter(
        TrinetraCredit.organization_id == organization_id,
        TrinetraCredit.work_item_id.in_(list(work_item_ids)),
        TrinetraCredit.state != "WITHDRAWN",
        TrinetraCredit.review["withholding_confirmed"].as_boolean().is_(True),
    )
    if workspace_ids is not None:
        query = query.filter(TrinetraCredit.workspace_id.in_(list(workspace_ids)))
    return query.limit(501).all()


def _reviewed_for(db, rows) -> dict:
    ids = {r.work_item_id for r in rows}
    ids.update(
        uuid.UUID(e["work_item_id"])
        for r in rows
        for e in (r.review or {}).get("evidence", [])
    )
    workspaces = {r.workspace_id for r in rows}
    facts = versions.load(db, workspaces, ids)
    grouped = {}
    for row in rows:
        grouped.setdefault(row.work_item_id, []).append(row)
    found = {}
    for work_item_id, candidates in grouped.items():
        row = candidates[0]
        amount = None
        if len(candidates) == 1:
            amount = reviewed_withholding(row, _value(row, facts))
        found[work_item_id] = (row, amount)
    return found


def withholding_for(db, organization_id, work_item_ids, workspace_ids=None):
    """The confirmed withholding on each of these invoices, for Helm's reminders (Final 2T, Phase 1.1).

    Deliberately independent of the TRINETRA mode, the plan and the workspace's state: a recorded confirmation keeps
    Helm from chasing the withheld tax as cash even after the feature is switched off or a plan lapses. Only an
    explicit withdrawal (or a review that clears the confirmation) releases it. `reviewed_micros` is None when the
    evidence behind the confirmation is no longer current, or more than one case claims the invoice: the invoice is
    still held, because the amount can no longer be told."""
    ids = list(work_item_ids)
    if not ids:
        return {}
    rows = _confirmed(db, organization_id, ids, workspace_ids)
    if len(rows) > 500:
        return {
            r.work_item_id: Withholding(str(r.id), None) for r in rows
        }  # no truncated total is presented as complete
    return {
        work_item_id: Withholding(str(row.id), amount)
        for work_item_id, (row, amount) in _reviewed_for(db, rows).items()
    }


def reminder_ceiling(db, *, organization_id, workspace_id, work_item_id):
    """The most a cash reminder for this invoice may ask for (micros), or None when no withholding applies.

    0 means held: the amount withheld is not known. A reminder for more than the ceiling would chase withheld tax."""
    if not workspace_id or not work_item_id:
        return None
    found = withholding_for(db, organization_id, [work_item_id], [workspace_id]).get(
        work_item_id
    )
    if found is None:
        return None
    if found.reviewed_micros is None:
        return 0
    role = (
        db.query(DocumentRole)
        .filter_by(work_item_id=work_item_id, workspace_id=workspace_id)
        .first()
    )
    if role is None or role.total_micros is None:
        return 0
    return max(0, role.total_micros - found.reviewed_micros)


def reminder_requires_review(db, *, organization_id, workspace_id, work_item_id):
    """Kept for callers that only need to know whether a withholding applies at all."""
    return (
        reminder_ceiling(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            work_item_id=work_item_id,
        )
        is not None
    )


def annotate(db, who, promises):
    from app.core.config import settings
    from app.api.capability_gate import has_capability
    from app.workers.tenant_gate import inactive_reason, unpaid_reason
    from app.services.helm.gate import through_api_key

    if (
        through_api_key()
        or not settings.TRINETRA_LIVE_ENABLED
        or unpaid_reason(db, organization_id=who.organization_id)
        or not has_capability(
            db,
            organization_id=who.organization_id,
            capability_key="capability.trinetra",
        )
    ):
        return promises
    eligible = [
        p
        for p in promises
        if p.get("readable")
        and p.get("work_item_id")
        and p.get("kind") == "PAYMENT_EXPECTED"
        and p.get("currency") == "INR"
        and who.can_read(uuid.UUID(p["workspace_id"]))
    ]
    if not eligible:
        return promises
    workspaces = {uuid.UUID(p["workspace_id"]) for p in eligible}
    active = {
        w
        for w in workspaces
        if not inactive_reason(db, organization_id=who.organization_id, workspace_id=w)
    }
    found = withholding_for(
        db,
        who.organization_id,
        [uuid.UUID(p["work_item_id"]) for p in eligible],
        active,
    )
    if len(found) > 500:
        return promises  # No truncated total is presented as complete.
    for promise in eligible:
        withholding = found.get(uuid.UUID(promise["work_item_id"]))
        if withholding is None:
            continue
        amount = withholding.reviewed_micros
        balance = promise.get("amount_micros")
        cash_due = (
            max(0, int(balance) - amount)
            if amount is not None and balance is not None
            else None
        )
        held = cash_due is None or cash_due <= 0
        promise["withholding_review"] = {
            "case_id": withholding.case_id,
            "reviewed_micros": str(amount) if amount is not None else None,
            "cash_due_micros": str(cash_due) if cash_due is not None else None,
            "reminder_held": held,
            "note": (
                "The commercial balance includes TDS the customer withheld. Reminders ask only for the cash still "
                "owed."
                if not held
                else "Commercial balance includes withholding; it is not all unpaid cash. Reminders are held until "
                "the TRINETRA evidence is reviewed."
            ),
        }
    return promises
