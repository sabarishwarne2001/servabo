"""Pure TDS evidence arithmetic. Version 1: exact paise, no rate inference.

All IDs are opaque, already-authorized references. Matching proposes; only a
reviewed allocation contributes to posted amounts. No Helm cash state is mutated.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re

VERSION = "trinetra-v1-paise-exact"
MAX_MICROS = 9_000_000_000_000_000


def money(raw: str) -> int:
    if not isinstance(raw, str) or not re.fullmatch(r"\d{1,10}(?:\.\d{1,2})?", raw):
        raise ValueError(
            "Use a nonnegative decimal amount with at most two decimal places."
        )
    value = int(Decimal(raw) * 1_000_000)
    if value > MAX_MICROS:
        raise ValueError("Amount exceeds the supported bound.")
    return value


def tax_period(on: date) -> tuple[int, str]:
    year = on.year if on.month >= 4 else on.year - 1
    suffix = f"{(year + 1) % 100:02d}"
    label = (
        f"Tax year {year}–{suffix}"
        if year >= 2026
        else f"FY {year}–{suffix} / AY {year+1}–{(year+2)%100:02d}"
    )
    return year, label


@dataclass(frozen=True)
class Scope:
    organization: str
    workspace: str
    entity: str
    year: int


@dataclass(frozen=True)
class Credit:
    id: str
    scope: Scope
    deductor: str
    expected: int | None
    source: str
    disputed: bool = False
    gross_micros: int | None = None
    bank_micros: int | None = None
    booked_micros: int | None = None
    advice_micros: int | None = None
    reference: str | None = None


@dataclass(frozen=True)
class Posting:
    id: str
    scope: Scope
    deductor: str
    amount: int
    snapshot: str
    reference: str | None = None


@dataclass(frozen=True)
class Allocation:
    credit: str
    posting: str
    amount: int
    snapshot: str


def allocate(
    credit: Credit, posting: Posting, amount: int, allocations: list[Allocation]
) -> list[Allocation]:
    if credit.scope != posting.scope:
        raise ValueError("Allocation scope differs.")
    if credit.deductor != posting.deductor or not credit.deductor:
        raise ValueError("Deductor identity requires review.")
    if credit.disputed or credit.expected is None or not credit.source:
        raise ValueError("A supported, undisputed expectation is required.")
    if type(amount) is not int or amount <= 0 or posting.amount <= 0:
        raise ValueError(
            "Reversals and nonpositive allocations require separate review."
        )
    used = sum(
        a.amount
        for a in allocations
        if a.posting == posting.id and a.snapshot == posting.snapshot
    )
    credited = sum(
        a.amount
        for a in allocations
        if a.credit == credit.id and a.snapshot == posting.snapshot
    )
    if amount > posting.amount - used or amount > credit.expected - credited:
        raise ValueError("Allocation exceeds available amount.")
    return [*allocations, Allocation(credit.id, posting.id, amount, posting.snapshot)]


def reconcile(
    credit: Credit,
    postings: list[Posting],
    allocations: list[Allocation],
    *,
    statement_available: bool,
) -> dict:
    relevant = {
        p.id: p
        for p in postings
        if p.scope == credit.scope and p.deductor == credit.deductor
    }
    posted = sum(
        a.amount
        for a in allocations
        if a.credit == credit.id
        and a.posting in relevant
        and a.snapshot == relevant[a.posting].snapshot
    )
    expected = credit.expected
    available = {
        p.id: p.amount
        - sum(
            a.amount
            for a in allocations
            if a.posting == p.id and a.snapshot == p.snapshot and a.credit != credit.id
        )
        for p in relevant.values()
    }
    candidates = [
        p.id
        for p in relevant.values()
        if expected is not None and available[p.id] > 0 and available[p.id] == expected
    ]
    wrong_identity = any(
        p.scope == credit.scope
        and p.deductor != credit.deductor
        and credit.reference
        and p.reference
        and p.reference.casefold().strip() == credit.reference.casefold().strip()
        for p in postings
    )
    if credit.disputed:
        status = "DISPUTED"
    elif expected is None or not credit.source:
        status = "EVIDENCE_NEEDED"
    elif not statement_available:
        status = "PENDING_REPORT"
    elif posted == expected and expected > 0:
        status = "POSTED"
    elif posted:
        status = "AMOUNT_MISMATCH"
    elif len(candidates) > 1:
        status = "AMBIGUOUS"
    elif candidates:
        status = "SUGGESTED"
    elif wrong_identity:
        status = "TAN_MISMATCH_SUSPECTED"
    elif any(value > 0 for value in available.values()):
        status = "AMOUNT_MISMATCH"
    else:
        status = "POSSIBLE_MISSING_POSTING"
    return dict(
        status=status,
        expected_micros=expected,
        posted_micros=posted,
        gap_micros=(
            max(0, expected - posted)
            if expected is not None and statement_available
            else None
        ),
        candidate_ids=candidates,
        rule_version=VERSION,
        gross_micros=credit.gross_micros,
        bank_micros=credit.bank_micros,
        booked_micros=credit.booked_micros,
        advice_micros=credit.advice_micros,
        note="Evidence comparison only; absence does not establish claimability or misconduct.",
    )
