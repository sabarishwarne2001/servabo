"""The reconciliation of the books against GSTR-2B: pure functions, no database, deterministic.

Inputs are plain views of the supplier records (`RecView`) and of the purchase documents Servabo has read
(`BookView`). The result is one `MatchOut` per supplier record and per book document that should be shown.

Rules (docs/product/GST-CREDIT.md):
  * Amendments (`b2ba`, `cdnra`, `ecoma`) replace their originals; the same supplier document reported in two
    periods is one document, its later copy marked a duplicate.
  * Exact: the same IRN, else the same supplier GSTIN and normalised number with dates in one financial year.
  * Suggested: same supplier, dates within 3 days, the value within the tolerance and similar numbers. A
    suggestion is never confirmed by the engine; it waits for a person.
  * One to one: a book document matches at most one record and the other way round.
  * A person's decision (confirm, link by hand, "not ours") is applied before anything else.
  * Across periods: all imported periods of a GSTIN are matched together; a book invoice is "waiting" only
    inside the window the imports cover.
Nothing here is tax advice.
"""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Mapping, Optional, Sequence

from app.services.gst import vocabulary as v
from app.services.gst.keys import financial_year

SUGGEST_DAYS = 3
SUGGEST_NUMBER_RATIO = 0.7

KIND_GROUP = {v.KIND_INVOICE: "I", v.KIND_CREDIT_NOTE: "N", v.KIND_DEBIT_NOTE: "N", v.KIND_OTHER: "O"}


@dataclass(frozen=True)
class RecView:
    id: uuid.UUID
    section: str
    kind: str
    period: str
    supplier_gstin: Optional[str]
    supplier_name: Optional[str]
    supplier_name_key: Optional[str]
    number: Optional[str]
    doc_key: Optional[str]
    doc_date: Optional[date]
    value_micros: Optional[int]
    taxable_micros: Optional[int]
    igst_micros: int
    cgst_micros: int
    sgst_micros: int
    cess_micros: int
    reverse_charge: bool
    itc_available: Optional[str]
    reason: Optional[str]
    irn: Optional[str]
    original_key: Optional[str]
    supplier_period: Optional[str] = None

    @property
    def tax_micros(self) -> int:
        return self.igst_micros + self.cgst_micros + self.sgst_micros + self.cess_micros

    @property
    def group(self) -> str:
        return KIND_GROUP.get(self.kind, "O")


@dataclass(frozen=True)
class BookView:
    work_item_id: uuid.UUID
    number: Optional[str]
    number_key: Optional[str]
    kind: str  # INVOICE | CREDIT_NOTE | DEBIT_NOTE
    doc_date: Optional[date]
    supplier_gstin: Optional[str]
    supplier_name: Optional[str]
    supplier_name_key: Optional[str]
    taxable_micros: Optional[int]
    igst_micros: Optional[int]
    cgst_micros: Optional[int]
    sgst_micros: Optional[int]
    cess_micros: Optional[int]
    tax_total_micros: Optional[int]
    total_micros: Optional[int]
    irn: Optional[str] = None
    #: three-way matching: the case status of this invoice (None when procurement data does not cover it)
    case_status: Optional[str] = None
    case_reason: Optional[str] = None
    has_purchase_order: bool = False
    has_receipt: bool = False
    #: Helm settlement: "PAID" with a date, or None (nothing recorded)
    paid_on: Optional[date] = None
    paid_fully: bool = False

    @property
    def group(self) -> str:
        return KIND_GROUP.get(self.kind, "O")

    @property
    def tax_micros(self) -> Optional[int]:
        return self.tax_total_micros


@dataclass(frozen=True)
class DecisionView:
    supplier_gstin: str
    doc_key: str
    kind: str
    decision: str
    work_item_id: Optional[uuid.UUID]


@dataclass
class MatchOut:
    record: Optional[RecView]
    book: Optional[BookView]
    status: str
    method: Optional[str] = None
    differences: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    itc_micros: Optional[int] = None
    ims_action: Optional[str] = None
    ims_reason: Optional[str] = None
    period_first_seen: Optional[str] = None
    reported_late: bool = False
    duplicate_of_record: Optional[uuid.UUID] = None
    duplicate_of_work_item: Optional[uuid.UUID] = None
    decision: Optional[str] = None
    risk: Optional[dict[str, Any]] = None


# --------------------------------------------------------------------------------------------- helpers


def _same_year(a: Optional[date], b: Optional[date]) -> bool:
    return a is None or b is None or financial_year(a) == financial_year(b)


def _digits(text: Optional[str]) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit()).lstrip("0")


def numbers_similar(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    da, db = _digits(a), _digits(b)
    if len(da) >= 3 and da == db:
        return True
    matcher = difflib.SequenceMatcher(None, a, b)
    return (matcher.real_quick_ratio() >= SUGGEST_NUMBER_RATIO and matcher.quick_ratio() >= SUGGEST_NUMBER_RATIO
            and matcher.ratio() >= SUGGEST_NUMBER_RATIO)


def _supplier_identity(gstin: Optional[str], name_key: Optional[str]) -> tuple[str, str]:
    return ("g", gstin) if gstin else ("n", name_key or "")


# --------------------------------------------------------------------------------------------- records


def effective_records(records: Sequence[RecView]) -> tuple[list[RecView], dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, str]]:
    """Apply amendments and fold a document reported twice.

    Returns (records that stand, {duplicate record id: the record it duplicates}, {record id: first period seen})."""
    superseded: set[uuid.UUID] = set()
    by_group: dict[tuple[Any, ...], list[RecView]] = {}
    for rec in records:
        if rec.section in v.MATCHABLE_SECTIONS and rec.doc_key:
            by_group.setdefault((rec.supplier_gstin, rec.group, rec.doc_key), []).append(rec)
    for rec in records:
        if rec.section not in v.AMENDMENT_SECTIONS:
            continue
        target = rec.original_key or rec.doc_key
        for other in by_group.get((rec.supplier_gstin, rec.group, target), ()):
            if other.id != rec.id and (other.section not in v.AMENDMENT_SECTIONS or other.period < rec.period):
                superseded.add(other.id)
    standing = [r for r in records if r.section in v.MATCHABLE_SECTIONS and r.id not in superseded]
    standing.sort(key=lambda r: (r.period, r.id.int))
    keep: list[RecView] = []
    duplicates: dict[uuid.UUID, uuid.UUID] = {}
    seen: dict[tuple[Any, ...], RecView] = {}
    first_seen: dict[uuid.UUID, str] = {}
    for rec in standing:
        first_seen[rec.id] = rec.period
        if not rec.doc_key:
            keep.append(rec)
            continue
        key = (rec.supplier_gstin, rec.group, rec.doc_key, financial_year(rec.doc_date) if rec.doc_date else None)
        first = seen.get(key)
        if first is None:
            seen[key] = rec
            keep.append(rec)
        else:
            duplicates[rec.id] = first.id
            keep.append(rec)
    return keep, duplicates, first_seen


# --------------------------------------------------------------------------------------------- differences


def _head_pairs(book: BookView, rec: RecView) -> list[tuple[str, str, Optional[int], Optional[int]]]:
    pairs: list[tuple[str, str, Optional[int], Optional[int]]] = [
        ("taxable", "Taxable value", book.taxable_micros, rec.taxable_micros),
        ("igst", "IGST", book.igst_micros, rec.igst_micros),
        ("cgst", "CGST", book.cgst_micros, rec.cgst_micros),
        ("sgst", "SGST", book.sgst_micros, rec.sgst_micros),
        ("cess", "Cess", book.cess_micros, rec.cess_micros),
    ]
    heads_known = any(x is not None for x in (book.igst_micros, book.cgst_micros, book.sgst_micros, book.cess_micros))
    if not heads_known:
        pairs.append(("tax", "Total tax", book.tax_total_micros, rec.tax_micros))
    pairs.append(("value", "Invoice value", book.total_micros, rec.value_micros))
    return pairs


def differences(book: BookView, rec: RecView, tolerance: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(amount differences beyond the tolerance, notes: date and number formatting). Only what both sides carry."""
    diffs: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for name, label, mine, theirs in _head_pairs(book, rec):
        if mine is None or theirs is None:
            continue
        if abs(mine - theirs) > tolerance:
            diffs.append({"field": name, "label": label, "books_micros": mine, "gstr2b_micros": theirs,
                          "delta_micros": mine - theirs})
    if book.doc_date and rec.doc_date and book.doc_date != rec.doc_date:
        notes.append({"code": "DATE", "label": "Date", "books": book.doc_date.isoformat(),
                      "gstr2b": rec.doc_date.isoformat()})
    if book.number and rec.number and book.number.strip().upper() != rec.number.strip().upper():
        notes.append({"code": "NUMBER_FORMAT", "label": "Number as printed", "books": book.number,
                      "gstr2b": rec.number})
    return diffs, notes


def claimable_micros(book: Optional[BookView], rec: RecView, diffs: Sequence[Mapping[str, Any]]) -> int:
    """The credit to claim for a pair: GSTR-2B's tax, or the lower of the two when the books differ."""
    theirs = rec.tax_micros
    if diffs and book is not None and book.tax_micros is not None:
        return min(theirs, book.tax_micros)
    return theirs


# --------------------------------------------------------------------------------------------- engine


def reconcile(
    records: Sequence[RecView],
    books: Sequence[BookView],
    *,
    tolerance_micros: int = v.DEFAULT_TOLERANCE_MICROS,
    decisions: Sequence[DecisionView] = (),
    window: Optional[tuple[date, date]] = None,
) -> list[MatchOut]:
    standing, duplicates, first_seen = effective_records(records)
    rec_by_id = {r.id: r for r in standing}

    # --- books: fold a document entered twice
    book_dupes: dict[uuid.UUID, uuid.UUID] = {}
    seen_books: dict[tuple[Any, ...], BookView] = {}
    usable: list[BookView] = []
    for book in sorted(books, key=lambda b: (b.doc_date or date.max, b.work_item_id.int)):
        if book.number_key:
            key = (_supplier_identity(book.supplier_gstin, book.supplier_name_key), book.group, book.number_key)
            first = seen_books.get(key)
            if first is not None and _same_year(first.doc_date, book.doc_date):
                book_dupes[book.work_item_id] = first.work_item_id
                continue
            seen_books[key] = book
        usable.append(book)
    book_by_id = {b.work_item_id: b for b in usable}

    pairs: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}  # record id -> (work item id, method)
    book_taken: set[uuid.UUID] = set()
    not_ours: set[uuid.UUID] = set()

    # --- 0. people first
    rec_by_natural = {(r.supplier_gstin, r.group, r.doc_key): r for r in standing if r.doc_key and r.supplier_gstin}
    decision_of: dict[uuid.UUID, str] = {}
    for d in decisions:
        group = KIND_GROUP.get(d.kind, "O")
        rec = rec_by_natural.get((d.supplier_gstin, group, d.doc_key))
        if rec is None:
            continue
        decision_of[rec.id] = d.decision
        if d.decision == v.DECISION_NOT_OURS:
            not_ours.add(rec.id)
        elif d.work_item_id in book_by_id and d.work_item_id not in book_taken and rec.id not in pairs:
            pairs[rec.id] = (d.work_item_id, v.METHOD_PERSON)
            book_taken.add(d.work_item_id)

    free_recs = [r for r in standing if r.id not in pairs and r.id not in not_ours and r.id not in duplicates]

    # --- 1. IRN
    book_by_irn: dict[str, list[BookView]] = {}
    for b in usable:
        if b.irn and b.work_item_id not in book_taken:
            book_by_irn.setdefault(b.irn.strip().lower(), []).append(b)
    for rec in free_recs:
        if not rec.irn:
            continue
        for b in book_by_irn.get(rec.irn.strip().lower(), ()):
            if b.work_item_id not in book_taken and b.group == rec.group:
                pairs[rec.id] = (b.work_item_id, v.METHOD_IRN)
                book_taken.add(b.work_item_id)
                break

    # --- 2. supplier GSTIN + normalised number, same financial year
    book_by_number: dict[tuple[Any, ...], list[BookView]] = {}
    for b in usable:
        if b.work_item_id not in book_taken and b.supplier_gstin and b.number_key:
            book_by_number.setdefault((b.supplier_gstin, b.group, b.number_key), []).append(b)
    for rec in free_recs:
        if rec.id in pairs or not rec.doc_key or not rec.supplier_gstin:
            continue
        for b in book_by_number.get((rec.supplier_gstin, rec.group, rec.doc_key), ()):
            if b.work_item_id not in book_taken and _same_year(b.doc_date, rec.doc_date):
                pairs[rec.id] = (b.work_item_id, v.METHOD_NUMBER)
                book_taken.add(b.work_item_id)
                break

    # --- 3. suggestions (never confirmed by the engine)
    suggested: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    rest_books: dict[tuple[str, str], list[BookView]] = {}
    for b in usable:
        if b.work_item_id not in book_taken:
            rest_books.setdefault(_supplier_identity(b.supplier_gstin, b.supplier_name_key), []).append(b)
    candidates: list[tuple[tuple[float, int, int], uuid.UUID, uuid.UUID]] = []
    for rec in free_recs:
        if rec.id in pairs:
            continue
        pools = list(rest_books.get(("g", rec.supplier_gstin or ""), ()))
        if rec.supplier_name_key:
            pools += rest_books.get(("n", rec.supplier_name_key), ())
        for b in pools:
            # the cheap tests first; comparing numbers is the expensive one
            if b.group != rec.group or b.doc_date is None or rec.doc_date is None \
                    or abs((b.doc_date - rec.doc_date).days) > SUGGEST_DAYS:
                continue
            mine = b.total_micros if b.total_micros is not None else b.taxable_micros
            theirs = rec.value_micros if (rec.value_micros is not None and b.total_micros is not None) else rec.taxable_micros
            if mine is None or theirs is None or abs(mine - theirs) > tolerance_micros:
                continue
            if not numbers_similar(b.number_key, rec.doc_key):
                continue
            ratio = difflib.SequenceMatcher(None, b.number_key or "", rec.doc_key or "").ratio()
            candidates.append(((-ratio, abs((b.doc_date - rec.doc_date).days), abs(mine - theirs)), rec.id, b.work_item_id))
    for _, rec_id, wid in sorted(candidates, key=lambda c: (c[0], c[1].int, c[2].int)):
        if rec_id not in pairs and rec_id not in suggested and wid not in book_taken:
            suggested[rec_id] = (wid, v.METHOD_SUGGESTED)
            book_taken.add(wid)

    # --- 4. build the rows
    out: list[MatchOut] = []
    for rec in standing:
        row = MatchOut(record=rec, book=None, status=v.NOT_IN_BOOKS, period_first_seen=first_seen.get(rec.id))
        row.decision = decision_of.get(rec.id)
        pair = pairs.get(rec.id) or suggested.get(rec.id)
        if pair is not None:
            book = book_by_id[pair[0]]
            row.book, row.method = book, pair[1]
            row.differences, row.notes = differences(book, rec, tolerance_micros)
        if rec.id in duplicates:
            row.duplicate_of_record = duplicates[rec.id]
            row.status = v.NOT_IN_BOOKS
            row.itc_micros = 0
            row.notes.append({"code": "DUPLICATE_RECORD", "label": "Reported twice",
                              "detail": "The supplier reported this document more than once."})
        elif rec.id in suggested:
            row.status = v.SUGGESTED
            row.itc_micros = rec.tax_micros
        elif rec.kind in (v.KIND_CREDIT_NOTE, v.KIND_DEBIT_NOTE):
            row.status = v.NOTE
            sign = -1 if rec.kind == v.KIND_CREDIT_NOTE else 1
            row.itc_micros = sign * rec.tax_micros if rec.itc_available != "N" else 0
        elif rec.reverse_charge:
            row.status = v.REVERSE_CHARGE
            row.itc_micros = rec.tax_micros
        elif rec.itc_available == "N":
            row.status = v.NOT_ELIGIBLE
            row.itc_micros = rec.tax_micros
        elif rec.id in pairs:
            row.status = v.MATCHED_WITH_DIFFERENCES if row.differences else v.MATCHED
            row.itc_micros = claimable_micros(row.book, rec, row.differences)
        else:
            row.status = v.NOT_IN_BOOKS
            row.itc_micros = rec.tax_micros
        if rec.id in not_ours:
            row.status = v.NOT_IN_BOOKS
            row.itc_micros = rec.tax_micros
        if rec.doc_date and rec.period and row.period_first_seen:
            row.reported_late = row.period_first_seen > f"{rec.doc_date.year:04d}-{rec.doc_date.month:02d}"
        out.append(row)

    matched_books = {row.book.work_item_id for row in out if row.book is not None}
    for book in usable:
        if book.work_item_id in matched_books:
            continue
        if window is not None and book.doc_date is not None and not (window[0] <= book.doc_date <= window[1]):
            continue
        if window is not None and book.doc_date is None:
            continue
        out.append(MatchOut(record=None, book=book, status=v.WAITING_FOR_SUPPLIER, itc_micros=book.tax_micros))
    for dupe_id, first_id in book_dupes.items():
        for row in out:
            if row.book is not None and row.book.work_item_id == first_id:
                row.notes.append({"code": "DUPLICATE_IN_BOOKS", "label": "Entered twice in your books",
                                  "work_item_id": str(dupe_id)})
    return out


def period_window(periods: Sequence[str]) -> Optional[tuple[date, date]]:
    """First day of the earliest imported period to the last day of the latest."""
    if not periods:
        return None
    first, last = min(periods), max(periods)
    y1, m1 = int(first[:4]), int(first[5:7])
    y2, m2 = int(last[:4]), int(last[5:7])
    end = date(y2 + (m2 == 12), (m2 % 12) + 1, 1) - timedelta(days=1)
    return date(y1, m1, 1), end


def section_16_4_deadline(invoice_date: date) -> date:
    """30 November following the end of the financial year the invoice belongs to (Section 16(4))."""
    return date(financial_year(invoice_date) + 1, 11, 30)


__all__ = ["BookView", "DecisionView", "MatchOut", "RecView", "claimable_micros", "differences", "effective_records",
           "numbers_similar", "period_window", "reconcile", "section_16_4_deadline"]
