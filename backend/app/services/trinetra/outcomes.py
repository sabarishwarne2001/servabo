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
        **ledger(db, workspace),
        **cycle(db, workspace),
    }


LEDGER_NOTE = (
    "TDS now visible in your statement: the tax of cases that had a gap in an earlier import and that an accountant has "
    "since confirmed as posted. It is evidence that a credit appears in your statement. It is NOT cash recovered, a refund "
    "or money saved."
)
CYCLE_NOTE = (
    "Measured from the case history: the days from a case being opened to its being closed. The recorded review minutes "
    "above are what reviewers typed in, a different thing."
)


def ledger(db, workspace):
    """The cumulative closure ledger for this workspace (rows persist across imports; deduplicated by case and snapshot)."""
    from datetime import datetime, timezone

    from app.models.trinetra import TrinetraOutcome

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = month_start.replace(month=1)
    O = TrinetraOutcome
    month, year, total, count = (
        db.query(
            func.coalesce(func.sum(O.amount_micros).filter(O.confirmed_at >= month_start), 0),
            func.coalesce(func.sum(O.amount_micros).filter(O.confirmed_at >= year_start), 0),
            func.coalesce(func.sum(O.amount_micros), 0),
            func.count(O.id),
        )
        .filter(O.workspace_id == workspace.id, O.was_gap.is_(True))
        .one()
    )
    return {
        "now_visible_this_month_micros": int(month or 0),
        "now_visible_this_year_micros": int(year or 0),
        "now_visible_total_micros": int(total or 0),
        "now_visible_cases": int(count or 0),
        "ledger_note": LEDGER_NOTE,
    }


def cycle(db, workspace):
    """Days from a case being opened to its being closed, from the history (median and mean)."""
    from statistics import mean, median

    from app.models.trinetra import TrinetraCredit

    closing = ("CA_REVIEWED", "EXPLAINED", "WITHDRAWN", "UNRESOLVED")
    rows = (
        db.query(
            TrinetraCredit.id,
            func.min(TrinetraDecision.created_at),
            func.max(TrinetraDecision.created_at).filter(TrinetraDecision.action.in_(closing)),
        )
        .join(TrinetraDecision, TrinetraDecision.credit_id == TrinetraCredit.id)
        .filter(TrinetraCredit.workspace_id == workspace.id, TrinetraCredit.state.in_(closing))
        .group_by(TrinetraCredit.id)
        .limit(5001)
        .all()
    )
    spans = [max(0.0, (closed - opened).total_seconds() / 86400) for _, opened, closed in rows if opened and closed]
    return {
        "measured_cycle_cases": len(spans),
        "measured_cycle_days_median": round(median(spans), 1) if spans else None,
        "measured_cycle_days_mean": round(mean(spans), 1) if spans else None,
        "cycle_note": CYCLE_NOTE,
    }
