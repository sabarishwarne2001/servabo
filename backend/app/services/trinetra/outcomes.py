"""Conservative, reproducible comparison to the immediately preceding import.

Only accountant-reviewed closure, against unchanged expectations, with a net increase
in the same deductor's statement amount counts. Mere reallocation cannot count.
"""

from sqlalchemy import func
from app.models.trinetra import TrinetraDecision

NOTE = "Current CA-reviewed closure against the immediately preceding import, capped by increased statement evidence. Recorded minutes are self-reported effort, not time saved. No refund or cash recovery is measured."


def totals(rows):
    result = {}
    for row in rows:
        key = row["deductor_key"]
        result[key] = result.get(key, 0) + int(row["amount_micros"])
    return result


def baseline(snapshot, items, credits):
    if not snapshot:
        return {}
    by_id = {str(c.id): c for c in credits}
    return {
        "version": "prior-import-v1",
        "snapshot_id": str(snapshot.id),
        "deductor_totals": {k: str(v) for k, v in totals(snapshot.rows).items()},
        "cases": {
            item["id"]: {
                "gap_micros": str(item["gap_micros"]),
                "expected_micros": str(item["expected_micros"]),
                "source_version": by_id[item["id"]].source_version,
            }
            for item in items
            if item["id"] in by_id
            and item["snapshot_id"] == str(snapshot.id)
            and item["gap_micros"] is not None
            and item["expected_micros"] is not None
            and item["review_state"] not in ("WITHDRAWN", "EXPLAINED", "DISPUTED", "UNRESOLVED")
        },
    }


def measure(db, workspace, items, credits, snapshots):
    by_id = {str(c.id): c for c in credits}
    by_snapshot = {str(s.id): s for s in snapshots}
    remaining = {}
    for snap in snapshots:
        prior = (snap.comparison or {}).get("deductor_totals", {})
        for key, amount in totals(snap.rows).items():
            remaining[(str(snap.id), key)] = max(
                0, amount - int(prior.get(key, amount))
            )
    closed = 0
    count = 0
    for item in items:
        snap = by_snapshot.get(item["snapshot_id"])
        row = by_id[item["id"]]
        old = (snap.comparison or {}).get("cases", {}).get(item["id"]) if snap else None
        if (
            not old
            or item["status"] != "POSTED"
            or item["review_state"] != "CA_REVIEWED"
            or not item["source_current"]
            or old["source_version"] != row.source_version
            or int(old["expected_micros"]) != row.expected_micros
        ):
            continue
        key = (str(snap.id), row.deductor_key)
        value = min(max(0, int(old["gap_micros"])), remaining.get(key, 0))
        remaining[key] -= value
        closed += value
        count += int(value > 0)
    minutes = (
        db.query(func.coalesce(func.sum(TrinetraDecision.review_minutes), 0))
        .filter_by(workspace_id=workspace.id)
        .scalar()
    )
    return {
        "confirmed_gap_closure_micros": closed,
        "confirmed_cases": count,
        "review_minutes": int(minutes),
        "note": NOTE,
    }
