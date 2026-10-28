"""Transient synthetic scenarios: no customer records, tax rates or legal claims."""

from datetime import date, timedelta
from dataclasses import replace
from app.services.trinetra.domain import (
    Scope,
    Credit,
    Posting,
    allocate,
    reconcile,
    tax_period,
)


def cockpit():
    scope = Scope("synthetic", "synthetic", "meridian", 2025)
    examples = [
        ("Exact posted", 2000, 2000, True),
        ("Partial remittance", 3000, 1500, True),
        ("Disputed deduction", 1800, 0, True),
        ("No uploaded posting", 2400, 0, True),
        ("Later posting", 1200, 1200, True),
        ("Deductor mismatch suspected", 900, 0, True),
        ("Grouped quarter allocation", 4000, 4000, True),
        ("Unsupported source", 1000, 0, False),
        ("Credit note pending review", None, 0, True),
    ]
    items = []
    for i, (name, expected, posted, available) in enumerate(examples):
        as_of = date(2026, 3, 31)
        age_days = [1, 18, 24, 32, 2, 9, 4, 7, 3][i]
        c = Credit(
            str(i),
            scope,
            "synthetic-deductor",
            expected * 1000000 if expected is not None else None,
            f"synthetic-invoice-{i}",
            disputed=i == 2,
            gross_micros=118000000000,
            bank_micros=50000000000 if i == 1 else None,
            reference=f"DEMO-{i+1:03d}",
        )
        p = Posting(str(i), scope, c.deductor, posted * 1000000, "synthetic-2026-03-31")
        allocations = allocate(c, p, p.amount, []) if posted else []
        sources = [p] if posted else []
        if i == 5:
            sources = [
                replace(
                    p,
                    deductor="different-synthetic-deductor",
                    amount=900000000,
                    reference=c.reference,
                )
            ]
        if i == 6:
            p = replace(p, amount=6000000000)
            other = replace(c, id="quarter-other", expected=2000000000)
            allocations = allocate(other, p, 2000000000, [])
            allocations = allocate(c, p, 4000000000, allocations)
            sources = [p]
        result = reconcile(c, sources, allocations, statement_available=available)
        if i == 4:
            result[
                "note"
            ] += " Earlier snapshot had no posting; this later snapshot contains the reviewed amount."
        if i == 6:
            result[
                "note"
            ] += " This invoice uses ₹4,000 of a ₹6,000 quarterly posting; ₹2,000 belongs to another invoice."
        if i == 7:
            result[
                "note"
            ] += " The supplied file was unsupported, so no statement amount was accepted."
        items.append(
            dict(
                id=str(i),
                reference=f"DEMO-{i+1:03d}",
                counterparty=name,
                year=2025,
                period=tax_period(date(2026, 3, 31))[1],
                revision=1,
                age_days=age_days,
                review_state="OPEN",
                created_at=(as_of - timedelta(days=age_days)).isoformat()
                + "T00:00:00+00:00",
                as_of="2026-03-31",
                source_kind="Illustrative synthetic evidence",
                **result,
            )
        )
    items += _money_model_scenarios(len(items))
    return dict(
        is_sample=True,
        as_of="2026-03-31",
        items=items,
        total=len(items),
        expected_micros=sum(x["expected_micros"] or 0 for x in items),
        posted_micros=sum(x["posted_micros"] for x in items),
        gap_micros=sum(x["gap_micros"] or 0 for x in items),
        unresolved=sum(x["status"] not in ("POSTED", "LATE_POSTING", "VERIFIED_CORRECTED", "UNRESOLVED") for x in items),
        note="Synthetic arithmetic examples; no rates or section eligibility asserted. Unknown gaps excluded from totals.",
    )


def _money_model_scenarios(start):
    """Four more synthetic scenarios for the statuses of the whole money model (Final 2T): a suspected duplicate, a posting
    booked in a later tax year, a reversal a reviewer paired with its row, and a case closed as unresolved."""
    M = 1_000_000
    out = []
    twin = dict(section="194C", on=date(2025, 6, 15), booked_on=date(2025, 7, 30))
    cases = [
        ("Duplicate posting suspected", 2025, 2000, [("a", 2000, twin), ("b", 2000, twin)], None, 5,
         "Two identical statement rows could each match; a person decides, nothing is allocated."),
        ("Posted in a later tax year", 2024, 1500, [("a", 1500, dict(on=date(2025, 3, 20), booked_on=date(2025, 6, 10)))], 1500, 11,
         "The row is dated in FY 2024-25 and was booked in Tax Year 2025-26; it is still the reviewed amount."),
        ("Reversal paired by a reviewer", 2025, 2000, [("a", 2000, dict(section="194C"))], 2000, 14,
         "A ₹1,000 reversal was paired with a ₹3,000 row by a reviewer; the net ₹2,000 was allocated."),
        ("Closed as unresolved", 2025, 1200, [], None, 40,
         "Closed without resolution after the customer did not answer; this is not a refund or a recovery."),
    ]
    for n, (name, year, expected, rows, allocated, age, note) in enumerate(cases):
        scope = Scope("synthetic", "synthetic", "meridian", year)
        c = Credit(str(start + n), scope, "synthetic-deductor", expected * M, f"synthetic-invoice-{start + n}",
                   gross_micros=118000000000, reference=f"DEMO-{start + n + 1:03d}")
        postings = [Posting(i, scope, c.deductor, amount * M, "synthetic-2026-03-31", None, **extra) for i, amount, extra in rows]
        allocations = allocate(c, postings[0], allocated * M, []) if allocated else []
        result = reconcile(c, postings, allocations, statement_available=True)
        review_state = "OPEN"
        if n == 3:
            result["status"], review_state = "UNRESOLVED", "UNRESOLVED"
        result["note"] += " " + note
        as_of = date(2026, 3, 31)
        out.append(dict(
            id=str(start + n), reference=f"DEMO-{start + n + 1:03d}", counterparty=name, year=year,
            period=tax_period(date(year + 1, 3, 31))[1], revision=1, age_days=age, review_state=review_state,
            created_at=(as_of - timedelta(days=age)).isoformat() + "T00:00:00+00:00", as_of="2026-03-31",
            source_kind="Illustrative synthetic evidence", **result))
    return out
