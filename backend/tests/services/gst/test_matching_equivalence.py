"""The fast reconciliation gives exactly the rows of the earlier one (Session H, GST matching speed).

`reference_matching.reference_reconcile` is the function as it was before the speed-up. Seeded random workloads hold
the new one to it: every row, in the same order, with the same status, method, differences, notes and amounts. The
workloads are built to touch every branch: exact numbers, numbers printed differently, near numbers and near dates
(suggestions that compete for one book), amounts off, documents reported twice and amended, credit notes, suppliers
without a GSTIN, a document entered twice in the books, and people's decisions."""

from __future__ import annotations

import random
import uuid
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.services.gst import vocabulary as v
from app.services.gst.keys import number_key
from app.services.gst.matching import DecisionView, MatchOut, RecView, period_window, reconcile
from app.services.helm import identity as ident
from tests.services.gst.helpers import M, book
from tests.services.gst.reference_matching import reference_reconcile

pytestmark = pytest.mark.no_db

SUPPLIERS = [("27AABCS5555K1Z5", "Sahyadri Packaging"), ("29AAGCD7777P1Z2", "Deccan Steel Traders"),
             ("24AAHCP1234Q1Z9", "Patel Chemicals Pvt Ltd"), ("07AAACN9999R1Z1", "Nirmal Logistics"),
             (None, "Cash Vendor Stores"), (None, "Local Printers")]


def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128))


def _rec(rng, *, gstin, name, number, on, taxable, period, section="b2b", kind="INVOICE", irn=None, original_key=None):
    tax = int(taxable * 0.18 * M)
    return RecView(
        id=_uuid(rng), section=section, kind=kind, period=period, supplier_gstin=gstin, supplier_name=name,
        supplier_name_key=ident.key_for(name), number=number, doc_key=number_key(number), doc_date=on,
        value_micros=int(taxable * M) + tax, taxable_micros=int(taxable * M), igst_micros=0, cgst_micros=tax // 2,
        sgst_micros=tax - tax // 2, cess_micros=0, reverse_charge=rng.random() < 0.03,
        itc_available="N" if rng.random() < 0.04 else "Y", reason=None, irn=irn, original_key=original_key)


def workload(seed: int, size: int):
    rng = random.Random(seed)
    records, books, decisions = [], [], []
    for n in range(size):
        gstin, name = rng.choice(SUPPLIERS)
        on = date(2026, 9, 1) + timedelta(days=rng.randint(0, 29))
        taxable = rng.choice([1000, 2500, 2500, 7800, 12000]) + rng.choice([0, 0, 0, 1, 40])
        number = f"{rng.choice(['INV', 'S01', 'TX'])}/25-26/{rng.randint(1, 60):04d}"
        irn = f"{rng.getrandbits(256):064x}" if rng.random() < 0.1 else None
        roll = rng.random()
        kind = "CREDIT_NOTE" if rng.random() < 0.05 else "INVOICE"
        in_books = roll < 0.9
        if in_books:
            b = book(number, on, taxable, supplier=gstin, name=name, kind=kind, irn=irn)
            b = replace(b, work_item_id=_uuid(rng))
            books.append(b)
            if rng.random() < 0.05:  # entered twice
                books.append(replace(b, work_item_id=_uuid(rng)))
        reported = rng.random() < 0.88
        if not reported:
            continue
        shown = number
        shift = 0
        amount = taxable
        style = rng.random()
        if style < 0.12:
            shown = number.replace("/25-26/", "-")
        elif style < 0.22:
            shown = number[:-1] + str((int(number[-1]) + 1) % 10)  # a near number: suggestion
            shift = rng.randint(-4, 4)
        elif style < 0.3:
            amount += rng.choice([-500, 500, 2000])
        elif style < 0.34:
            shift = rng.choice([-1, 1]) * rng.randint(2, 6)
        period = "2026-09"
        rec = _rec(rng, gstin=gstin, name=name, number=shown, on=on + timedelta(days=shift), taxable=amount,
                   period=period, kind=kind, irn=irn)
        records.append(rec)
        if rng.random() < 0.05:  # reported again in a later period
            records.append(replace(rec, id=_uuid(rng), period="2026-10"))
        if rng.random() < 0.04:  # amended
            records.append(_rec(rng, gstin=gstin, name=name, number=shown + "A", on=rec.doc_date, taxable=amount + 100,
                                period="2026-10", section="b2ba", original_key=rec.doc_key))
        if gstin and rng.random() < 0.03:
            decisions.append(DecisionView(gstin, rec.doc_key or "", "I" if kind == "INVOICE" else "N",
                                          rng.choice([v.DECISION_NOT_OURS, v.DECISION_CONFIRM]), None))
    # a decision that links a record to a particular book
    for rec in rng.sample(records, min(5, len(records))):
        if rec.supplier_gstin and rec.doc_key and books:
            decisions.append(DecisionView(rec.supplier_gstin, rec.doc_key, "INVOICE", v.DECISION_LINK,
                                          rng.choice(books).work_item_id))
    rng.shuffle(records)
    rng.shuffle(books)
    return records, books, decisions


def _plain(rows: list[MatchOut]):
    return [(r.record, r.book, r.status, r.method, r.differences, r.notes, r.itc_micros, r.period_first_seen,
             r.reported_late, r.duplicate_of_record, r.decision) for r in rows]


@pytest.mark.parametrize("seed", [1, 7, 42, 2026, 20261019])
def test_the_fast_reconcile_gives_the_rows_of_the_earlier_one(seed):
    records, books, decisions = workload(seed, 400)
    window = period_window(["2026-09", "2026-10"])
    expected = reference_reconcile(records, books, decisions=decisions, window=window)
    got = reconcile(records, books, decisions=decisions, window=window)
    assert len(got) == len(expected) > 300
    assert _plain(got) == _plain(expected)
    statuses = {r.status for r in got}
    assert {v.MATCHED, v.SUGGESTED, v.WAITING_FOR_SUPPLIER, v.NOT_IN_BOOKS} <= statuses  # the workload reaches them
    assert any(n["code"] == "DUPLICATE_IN_BOOKS" for r in got for n in r.notes)
