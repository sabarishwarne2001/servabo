"""Narrow read-only annotation and send-time hold; never writes a Helm settlement."""

import uuid

from app.models.trinetra import TrinetraCredit
from app.models.work_item import WorkItem
from app.models.document_role import DocumentRole
from app.services.trinetra.projection import reviewed_withholding
from app.services.trinetra.service import invoice_version


def reminder_requires_review(db, *, organization_id, workspace_id, work_item_id):
    if not workspace_id or not work_item_id:
        return False
    # Keep this safety hold even after a plan downgrade, flag disable or stale source.
    # Only an explicit withdrawal or review clearing confirmation releases it.
    return (
        db.query(TrinetraCredit.id)
        .filter(
            TrinetraCredit.organization_id == organization_id,
            TrinetraCredit.workspace_id == workspace_id,
            TrinetraCredit.work_item_id == work_item_id,
            TrinetraCredit.state != "WITHDRAWN",
            TrinetraCredit.review["withholding_confirmed"].as_boolean().is_(True),
        )
        .first()
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
    rows = (
        db.query(TrinetraCredit)
        .filter(
            TrinetraCredit.organization_id == who.organization_id,
            TrinetraCredit.workspace_id.in_(active),
            TrinetraCredit.work_item_id.in_(
                [uuid.UUID(p["work_item_id"]) for p in eligible]
            ),
            TrinetraCredit.state != "WITHDRAWN",
            TrinetraCredit.review["withholding_confirmed"].as_boolean().is_(True),
        )
        .limit(501)
        .all()
    )
    if len(rows) > 500:
        return promises  # No truncated total is presented as complete.
    ids = {r.work_item_id for r in rows}
    ids.update(
        uuid.UUID(e["work_item_id"])
        for r in rows
        for e in (r.review or {}).get("evidence", [])
    )
    sources = {
        x.id: x
        for x in db.query(WorkItem).filter(
            WorkItem.id.in_(ids), WorkItem.workspace_id.in_(active)
        )
    }
    roles = {
        r.work_item_id: r
        for r in db.query(DocumentRole).filter(
            DocumentRole.work_item_id.in_(ids), DocumentRole.workspace_id.in_(active)
        )
    }
    grouped = {}
    for row in rows:
        grouped.setdefault(str(row.work_item_id), []).append(row)
    for promise in eligible:
        candidates = grouped.get(promise["work_item_id"], [])
        if not candidates:
            continue
        amount = None
        row = candidates[0]
        if len(candidates) == 1:
            source = sources.get(row.work_item_id)
            evidence = [
                {
                    **e,
                    "current": bool(
                        (doc := sources.get(uuid.UUID(e["work_item_id"])))
                        and doc.workspace_id == row.workspace_id
                        and doc.updated_at.isoformat() == e["source_version"]
                    ),
                }
                for e in (row.review or {}).get("evidence", [])
            ]
            value = {
                "source_current": bool(
                    source
                    and invoice_version(source, roles.get(row.work_item_id))
                    == row.source_version
                ),
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
            amount = reviewed_withholding(row, value)
        promise["withholding_review"] = {
            "case_id": str(row.id),
            "reviewed_micros": str(amount) if amount is not None else None,
            "reminder_held": True,
            "note": "Commercial balance includes withholding; it is not all unpaid cash. Review TRINETRA evidence before chasing.",
        }
    return promises
