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
    #: The section or table item as the invoice or accounting record prints it (never converted).
    section: str | None = None
    #: Credit notes a person attached, in micros: they reduce the gross the expectation can rest on.
    credit_notes_micros: int = 0
    #: The amount the tax was computed on, ONLY when an invoice, an accounting record or an advice states it (never computed).
    basis_micros: int | None = None
    basis_source: str | None = None
    #: A correction response was recorded before the active statement was imported.
    corrected: bool = False
    #: (snapshot id, posting id) pairs a reviewer rejected: not offered again for that snapshot.
    rejected: frozenset = frozenset()


@dataclass(frozen=True)
class Posting:
    id: str
    scope: Scope
    deductor: str
    amount: int
    snapshot: str
    reference: str | None = None
    #: As the statement prints it: an old-Act section (194C) or a new-Act Section 393 table item.
    section: str | None = None
    #: The statement row's transaction date, when it prints one.
    on: date | None = None
    #: The date the row was booked, when the statement prints it.
    booked_on: date | None = None


@dataclass(frozen=True)
class Allocation:
    credit: str
    posting: str
    amount: int
    snapshot: str


def _label(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def section_conflict(credit: Credit, posting: Posting) -> bool:
    """Both sides print a section or table item and they differ as printed. An old-Act section and a new-Act table item
    are different labels and are never converted into one another."""
    a, b = _label(credit.section), _label(posting.section)
    return bool(a and b and a != b)


def adjusted_gross(credit: Credit) -> int | None:
    """The invoice's gross less the credit notes a person attached (None when the gross is not known)."""
    if credit.gross_micros is None:
        return None
    return max(0, credit.gross_micros - credit.credit_notes_micros)


def _prints_alike(a: Posting, b: Posting) -> bool:
    """Two rows print the same section and dates (and print at least one of them: typed rows that print nothing can only
    be called ambiguous, never duplicates)."""
    same = (_label(a.section), a.on, a.booked_on) == (_label(b.section), b.on, b.booked_on)
    return same and bool(a.section or a.on or a.booked_on)


def booked_late(posting: Posting) -> bool:
    """Booked in a later tax year than the transaction it belongs to."""
    return (
        posting.on is not None
        and posting.booked_on is not None
        and tax_period(posting.booked_on)[0] > tax_period(posting.on)[0]
    )


def outside_year(credit: Credit, posting: Posting) -> bool:
    """The posting's transaction date falls in another tax year than the credit's: cross-year contamination."""
    return posting.on is not None and tax_period(posting.on)[0] != credit.scope.year


def allocate(
    credit: Credit, posting: Posting, amount: int, allocations: list[Allocation]
) -> list[Allocation]:
    if credit.scope != posting.scope:
        raise ValueError("Allocation scope differs.")
    if outside_year(credit, posting):
        raise ValueError(
            "The statement row is dated in another tax year than this case. Years are never mixed."
        )
    if section_conflict(credit, posting):
        raise ValueError(
            "The statement row's section or table item differs from the case's as printed. Servabo never converts an "
            "old-Act section into a new-Act table item or back; resolve it with the accountant."
        )
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
        if p.scope == credit.scope
        and p.deductor == credit.deductor
        and not outside_year(credit, p)
        and not section_conflict(credit, p)
    }
    posted = sum(
        a.amount
        for a in allocations
        if a.credit == credit.id
        and a.posting in relevant
        and a.snapshot == relevant[a.posting].snapshot
    )
    expected = credit.expected
    gross_left = adjusted_gross(credit)
    # A credit note can leave less gross than the expectation rests on: it is unsupported until a person reconfirms it.
    if expected is not None and gross_left is not None and expected > gross_left:
        expected = None
    available = {
        p.id: p.amount
        - sum(
            a.amount
            for a in allocations
            if a.posting == p.id and a.snapshot == p.snapshot and a.credit != credit.id
        )
        for p in relevant.values()
    }
    candidate_rows = [
        p
        for p in relevant.values()
        if expected is not None
        and available[p.id] > 0
        and available[p.id] == expected
        and (p.snapshot, p.id) not in credit.rejected
    ]
    candidates = [p.id for p in candidate_rows]
    wrong_identity = any(
        p.scope == credit.scope
        and p.deductor != credit.deductor
        and credit.reference
        and p.reference
        and p.reference.casefold().strip() == credit.reference.casefold().strip()
        for p in postings
    )
    allocated_rows = [
        relevant[a.posting]
        for a in allocations
        if a.credit == credit.id and a.posting in relevant and a.snapshot == relevant[a.posting].snapshot
    ]
    if credit.disputed:
        status = "DISPUTED"
    elif expected is None or not credit.source:
        status = "EVIDENCE_NEEDED"
    elif not statement_available:
        status = "PENDING_REPORT"
    elif posted == expected and expected > 0:
        if credit.corrected:
            status = "VERIFIED_CORRECTED"
        elif allocated_rows and all(booked_late(p) for p in allocated_rows):
            status = "LATE_POSTING"
        else:
            status = "POSTED"
    elif posted:
        status = "AMOUNT_MISMATCH"
    elif len(candidates) > 1:
        status = (
            "DUPLICATE_SUSPECTED"
            if all(_prints_alike(candidate_rows[0], p) for p in candidate_rows[1:])
            else "AMBIGUOUS"
        )
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
        adjusted_gross_micros=gross_left,
        credit_notes_micros=credit.credit_notes_micros,
        bank_micros=credit.bank_micros,
        booked_micros=credit.booked_micros,
        advice_micros=credit.advice_micros,
        basis_micros=credit.basis_micros,
        basis_source=credit.basis_source,
        note="Evidence comparison only; absence does not establish claimability or misconduct.",
    )
