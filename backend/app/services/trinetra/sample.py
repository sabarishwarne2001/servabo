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
    return dict(
        is_sample=True,
        as_of="2026-03-31",
        items=items,
        total=len(items),
        expected_micros=sum(x["expected_micros"] or 0 for x in items),
        posted_micros=sum(x["posted_micros"] for x in items),
        gap_micros=sum(x["gap_micros"] or 0 for x in items),
        unresolved=sum(x["status"] != "POSTED" for x in items),
        note="Synthetic arithmetic examples; no rates or section eligibility asserted. Unknown gaps excluded from totals.",
    )
