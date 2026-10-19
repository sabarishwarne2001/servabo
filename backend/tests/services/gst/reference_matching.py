"""The reconciliation as it stood before Session H's speed-up, kept only so a test can hold the fast version to it.

Do not use this in the application. `reconcile` below is the unchanged text of the earlier function: it compares every
free record with every remaining book of the same supplier, and appends the duplicate notes by scanning every row."""

from __future__ import annotations

import difflib
import uuid
from datetime import date
from typing import Optional, Sequence

from app.services.gst import vocabulary as v
from app.services.gst.matching import (
    KIND_GROUP, SUGGEST_DAYS, BookView, DecisionView, MatchOut, RecView, _same_year, _supplier_identity,
    claimable_micros, differences, effective_records, numbers_similar)


def reference_reconcile(
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
