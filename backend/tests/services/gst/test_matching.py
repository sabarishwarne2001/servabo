"""The reconciliation rules (pure): exact and suggested matches, differences, statuses, amendments, periods,
duplicates, people's decisions and the IMS recommendation. Every case names what the engine must say and why."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date

import pytest

from app.services.gst import builder as b
from app.services.gst import ims
from app.services.gst import vocabulary as v
from app.services.gst.matching import DecisionView, period_window, reconcile, section_16_4_deadline
from tests.services.gst.helpers import M, SUPPLIER_A, SUPPLIER_B, book, parsed_return, rec_views, supplier_invoices

pytestmark = pytest.mark.no_db

SEP = date(2026, 9, 1)
WINDOW = period_window(["2026-09"])


def run(documents, books, *, decisions=(), window=WINDOW, tolerance=v.DEFAULT_TOLERANCE_MICROS, sections=None,
        period="2026-09"):
    body = sections if sections is not None else {"b2b": [supplier_invoices(documents)]}
    records = rec_views(parsed_return(body, period))
    return reconcile(records, books, tolerance_micros=tolerance, decisions=decisions, window=window), records


def by_status(rows, status):
    return [r for r in rows if r.status == status]


def test_the_same_irn_matches_even_when_the_numbers_differ():
    irn = "ab" * 32
    rows, _ = run([b.document("INV-9", date(2026, 9, 5), 1000, irn=irn)], [book("TOTALLY/DIFFERENT", date(2026, 9, 5), 1000, irn=irn)])
    assert [(r.status, r.method) for r in rows] == [(v.MATCHED, v.METHOD_IRN)]


@pytest.mark.parametrize("printed,booked", [
    ("INV/25-26/0045", "INV-45"), ("inv 0045", "INV-0045"), ("Invoice No. 45/2025-2026", "45"),
])
def test_the_same_supplier_and_number_matches_ignoring_zeros_labels_and_the_year_token(printed, booked):
    rows, _ = run([b.document(printed, date(2026, 9, 5), 1000)], [book(booked, date(2026, 9, 5), 1000)])
    assert [(r.status, r.method) for r in rows] == [(v.MATCHED, v.METHOD_NUMBER)]


def test_the_same_number_in_another_financial_year_is_another_invoice():
    rows, _ = run([b.document("INV-45", date(2026, 9, 5), 1000)], [book("INV-45", date(2025, 9, 5), 1000)],
                  window=period_window(["2025-09", "2026-09"]))
    assert sorted(r.status for r in rows) == [v.NOT_IN_BOOKS, v.WAITING_FOR_SUPPLIER]


def test_a_near_match_is_only_suggested_and_the_book_invoice_is_not_left_waiting():
    rows, _ = run([b.document("INV-0451", date(2026, 9, 6), 1000)], [book("INV-0452", date(2026, 9, 5), 1000)])
    assert [(r.status, r.method) for r in rows] == [(v.SUGGESTED, v.METHOD_SUGGESTED)]
    assert rows[0].ims_action is None  # the recommendation is added by the engine, after


def test_a_suggestion_needs_dates_within_three_days_and_a_value_within_tolerance():
    far, _ = run([b.document("INV-0451", date(2026, 9, 12), 1000)], [book("INV-0452", date(2026, 9, 5), 1000)])
    assert sorted(r.status for r in far) == [v.NOT_IN_BOOKS, v.WAITING_FOR_SUPPLIER]
    dear, _ = run([b.document("INV-0451", date(2026, 9, 6), 1500)], [book("INV-0452", date(2026, 9, 5), 1000)])
    assert sorted(r.status for r in dear) == [v.NOT_IN_BOOKS, v.WAITING_FOR_SUPPLIER]


def test_matching_is_one_to_one():
    documents = [b.document("INV-1", date(2026, 9, 5), 1000), b.document("INV-1", date(2026, 9, 5), 1000)]
    rows, _ = run(documents, [book("INV-1", date(2026, 9, 5), 1000)])
    assert sorted(r.status for r in rows) == [v.MATCHED, v.NOT_IN_BOOKS]
    assert any(n["code"] == "DUPLICATE_RECORD" for r in rows for n in r.notes)


def test_an_amount_beyond_the_tolerance_is_a_difference_and_the_lower_figure_is_claimable():
    # the books say 1000 + 18% = 180 tax; the supplier reported 1050 taxable, 189 tax
    rows, _ = run([b.document("INV-2", date(2026, 9, 5), 1050)], [book("INV-2", date(2026, 9, 5), 1000)])
    row = rows[0]
    assert row.status == v.MATCHED_WITH_DIFFERENCES
    fields = {d["field"] for d in row.differences}
    assert {"taxable", "cgst", "sgst", "value"} <= fields
    assert row.itc_micros == 180 * M  # the lower of 180 (books) and 189 (GSTR-2B)
    taxable = next(d for d in row.differences if d["field"] == "taxable")
    assert taxable["books_micros"] == 1000 * M and taxable["gstr2b_micros"] == 1050 * M and taxable["delta_micros"] == -50 * M


def test_a_rounding_difference_within_a_rupee_is_not_a_difference():
    other = book("INV-3", date(2026, 9, 5), 1000)
    other = replace(other, cgst_micros=other.cgst_micros + 400_000)
    rows, _ = run([b.document("INV-3", date(2026, 9, 5), 1000)], [other])
    assert rows[0].status == v.MATCHED and rows[0].differences == []


def test_the_tolerance_is_a_workspace_setting():
    other = replace(book("INV-3", date(2026, 9, 5), 1000), cgst_micros=90 * M + 5 * M)
    strict, _ = run([b.document("INV-3", date(2026, 9, 5), 1000)], [other])
    lenient, _ = run([b.document("INV-3", date(2026, 9, 5), 1000)], [other], tolerance=10 * M)
    assert strict[0].status == v.MATCHED_WITH_DIFFERENCES and lenient[0].status == v.MATCHED


def test_date_and_number_formatting_differences_are_notes_not_a_change_of_status():
    rows, _ = run([b.document("INV/25-26/0045", date(2026, 9, 5), 1000)], [book("INV-45", date(2026, 9, 6), 1000)])
    assert rows[0].status == v.MATCHED
    assert {n["code"] for n in rows[0].notes} == {"DATE", "NUMBER_FORMAT"}


def test_book_fields_that_were_not_read_are_not_differences():
    thin = replace(book("INV-4", date(2026, 9, 5), 1000), taxable_micros=None, igst_micros=None, cgst_micros=None,
                   sgst_micros=None, cess_micros=None, tax_total_micros=None, total_micros=None)
    rows, _ = run([b.document("INV-4", date(2026, 9, 5), 1000)], [thin])
    assert rows[0].status == v.MATCHED and rows[0].differences == []


def test_a_book_invoice_in_no_return_is_waiting_only_inside_the_imported_window():
    inside = book("IN-1", date(2026, 9, 20), 100)
    after = book("IN-2", date(2026, 10, 2), 100)
    before = book("IN-3", date(2026, 7, 30), 100)
    rows, _ = run([b.document("ZZZ-9", date(2026, 9, 5), 1000, rate=5)], [inside, after, before])
    waiting = by_status(rows, v.WAITING_FOR_SUPPLIER)
    assert [r.book.number for r in waiting] == ["IN-1"] and waiting[0].itc_micros == inside.tax_micros


def test_a_supplier_record_that_is_not_in_the_books_says_so():
    rows, _ = run([b.document("X-1", date(2026, 9, 5), 1000)], [])
    assert [(r.status, r.itc_micros) for r in rows] == [(v.NOT_IN_BOOKS, 180 * M)]


def test_not_eligible_reverse_charge_and_notes_have_their_own_statuses():
    documents = [
        b.document("NE-1", date(2026, 9, 5), 1000, itc_available="N", reason="P"),
        b.document("RC-1", date(2026, 9, 6), 1000, reverse_charge=True, itc_available="N"),
    ]
    sections = {"b2b": [supplier_invoices(documents)],
                "cdnr": [supplier_invoices([b.document("CN-1", date(2026, 9, 7), 500, note="C"),
                                            b.document("DN-1", date(2026, 9, 8), 100, note="D")], notes=True)]}
    rows, _ = run([], [], sections=sections)
    status = {r.record.number: r.status for r in rows}
    assert status == {"NE-1": v.NOT_ELIGIBLE, "RC-1": v.REVERSE_CHARGE, "CN-1": v.NOTE, "DN-1": v.NOTE}
    itc = {r.record.number: r.itc_micros for r in rows}
    assert itc["CN-1"] == -90 * M and itc["DN-1"] == 18 * M  # a credit note lowers the credit, a debit note adds


def test_an_amendment_replaces_its_original_across_periods():
    original = parsed_return({"b2b": [supplier_invoices([b.document("INV-7", date(2026, 8, 20), 1000)])]}, "2026-08")
    amended = parsed_return({"b2ba": [supplier_invoices([b.document("INV-7A", date(2026, 8, 20), 900,
                                                                    original=("INV-7", date(2026, 8, 20)))])]}, "2026-09")
    rows = reconcile(rec_views(original) + rec_views(amended), [book("INV-7A", date(2026, 8, 20), 900)],
                     window=period_window(["2026-08", "2026-09"]))
    assert [(r.record.section, r.status) for r in rows] == [("b2ba", v.MATCHED)]


def test_a_late_reported_invoice_is_matched_across_periods_and_says_where_it_first_appeared():
    october = parsed_return({"b2b": [supplier_invoices([b.document("LATE-1", date(2026, 9, 25), 1000)],
                                                       period="102026", filed=date(2026, 11, 9))]}, "2026-10")
    september = parsed_return({"b2b": []}, "2026-09")
    books = [book("LATE-1", date(2026, 9, 25), 1000)]
    before = reconcile(rec_views(september), books, window=period_window(["2026-09"]))
    assert [r.status for r in before] == [v.WAITING_FOR_SUPPLIER]
    after = reconcile(rec_views(september) + rec_views(october), books, window=period_window(["2026-09", "2026-10"]))
    assert [(r.status, r.period_first_seen, r.reported_late) for r in after] == [(v.MATCHED, "2026-10", True)]


def test_a_document_entered_twice_in_the_books_is_flagged_once():
    first = book("DUP-1", date(2026, 9, 5), 1000)
    second = book("DUP-1", date(2026, 9, 6), 1000)
    rows, _ = run([b.document("DUP-1", date(2026, 9, 5), 1000)], [second, first])
    assert len(rows) == 1 and rows[0].book is first
    assert any(n["code"] == "DUPLICATE_IN_BOOKS" and n["work_item_id"] == str(second.work_item_id) for n in rows[0].notes)


def test_a_book_invoice_without_a_gstin_is_suggested_by_supplier_name_never_confirmed():
    nameless = replace(book("INV-0451", date(2026, 9, 5), 1000), supplier_gstin=None)
    rows, _ = run([b.document("INV-0451", date(2026, 9, 5), 1000)], [nameless])
    assert [(r.status, r.method) for r in rows] == [(v.SUGGESTED, v.METHOD_SUGGESTED)]


def decision(record, kind="CONFIRM", wid=None):
    return DecisionView(record.supplier_gstin, record.doc_key, record.kind, kind, wid)


def test_a_confirmed_suggestion_becomes_a_match_and_a_link_by_hand_pairs_unlike_numbers():
    suggested = book("INV-0452", date(2026, 9, 5), 1000)
    rows, records = run([b.document("INV-0451", date(2026, 9, 6), 1000)], [suggested])
    assert rows[0].status == v.SUGGESTED
    confirmed = reconcile(records, [suggested], decisions=[decision(records[0], "CONFIRM", suggested.work_item_id)],
                          window=WINDOW)
    assert [(r.status, r.method, r.decision) for r in confirmed] == [(v.MATCHED, v.METHOD_PERSON, "CONFIRM")]
    odd = book("SOMETHING-ELSE", date(2026, 9, 15), 1000)
    linked = reconcile(records, [odd], decisions=[decision(records[0], "LINK", odd.work_item_id)], window=WINDOW)
    assert [(r.status, r.method) for r in linked] == [(v.MATCHED, v.METHOD_PERSON)]


def test_not_ours_keeps_the_record_out_of_matching_and_out_of_the_books():
    mine = book("INV-1", date(2026, 9, 5), 1000)
    rows, records = run([b.document("INV-1", date(2026, 9, 5), 1000)], [mine])
    rows = reconcile(records, [mine], decisions=[decision(records[0], "NOT_OURS")], window=WINDOW)
    by = {r.status: r for r in rows}
    assert by[v.NOT_IN_BOOKS].decision == "NOT_OURS" and by[v.WAITING_FOR_SUPPLIER].book is mine


def test_the_window_is_the_imported_periods():
    assert period_window(["2026-09"]) == (date(2026, 9, 1), date(2026, 9, 30))
    assert period_window(["2026-04", "2026-12"]) == (date(2026, 4, 1), date(2026, 12, 31))
    assert period_window([]) is None


def test_the_section_16_4_deadline_is_30_november_after_the_financial_year():
    assert section_16_4_deadline(date(2026, 9, 5)) == date(2027, 11, 30)  # FY 2026-27
    assert section_16_4_deadline(date(2026, 2, 5)) == date(2026, 11, 30)  # FY 2025-26


def test_the_reconciliation_is_deterministic():
    documents = [b.document(f"INV-{n}", date(2026, 9, 1 + n % 25), 1000 + n) for n in range(40)]
    books = [book(f"INV-{n}", date(2026, 9, 1 + n % 25), 1000 + n if n % 7 else 1005 + n) for n in range(0, 60)]
    first, records = run(documents, books)
    second = reconcile(records, books, window=WINDOW)
    shape = lambda rows: [(r.status, r.record.number if r.record else None, r.book.number if r.book else None) for r in rows]
    assert shape(first) == shape(second)


# --------------------------------------------------------------------------------------------------- IMS


def recommend(row, **book_fields):
    if row.book is not None and book_fields:
        row.book = replace(row.book, **book_fields)
    return ims.recommend(row)


def test_accept_needs_agreement_and_no_open_procurement_problem():
    rows, _ = run([b.document("INV-1", date(2026, 9, 5), 1000)], [book("INV-1", date(2026, 9, 5), 1000)])
    row = rows[0]
    assert recommend(row)[0] == v.IMS_ACCEPT and "no purchase-order data" in recommend(row)[1]
    assert recommend(row, has_purchase_order=True, has_receipt=True, case_status="APPROVED")[0] == v.IMS_ACCEPT
    assert "goods are received" in recommend(row, has_purchase_order=True, has_receipt=True)[1]


def test_pending_when_goods_are_not_received_or_a_dispute_is_open_or_it_is_not_in_the_books():
    rows, _ = run([b.document("INV-1", date(2026, 9, 5), 1000)], [book("INV-1", date(2026, 9, 5), 1000)])
    row = rows[0]
    action, reason = recommend(row, has_purchase_order=True, has_receipt=False, case_status="OPEN")
    assert action == v.IMS_PENDING and "goods not yet received" in reason
    assert recommend(row, case_status="NEEDS_REVIEW")[0] == v.IMS_PENDING
    lone, _ = run([b.document("X-1", date(2026, 9, 5), 1000)], [])
    assert ims.recommend(lone[0])[0] == v.IMS_PENDING


def test_pending_when_amounts_differ():
    rows, _ = run([b.document("INV-2", date(2026, 9, 5), 1050)], [book("INV-2", date(2026, 9, 5), 1000)])
    assert ims.recommend(rows[0])[0] == v.IMS_PENDING


def test_reject_only_on_strong_evidence_and_never_for_an_unseen_invoice():
    rows, records = run([b.document("INV-1", date(2026, 9, 5), 1000)], [book("INV-1", date(2026, 9, 5), 1000)])
    disputed = recommend(rows[0], case_status="DISPUTED", case_reason="Short delivery")
    assert disputed[0] == v.IMS_REJECT and "Short delivery" in disputed[1]
    unseen, _ = run([b.document("X-9", date(2026, 9, 5), 1000)], [])
    assert ims.recommend(unseen[0])[0] != v.IMS_REJECT
    ours = reconcile(records, [], decisions=[decision(records[0], "NOT_OURS")], window=WINDOW)
    assert ims.recommend(ours[0])[0] == v.IMS_REJECT
    twice, _ = run([b.document("D-1", date(2026, 9, 5), 1000), b.document("D-1", date(2026, 9, 5), 1000)],
                   [book("D-1", date(2026, 9, 5), 1000)])
    assert [ims.recommend(r)[0] for r in sorted(twice, key=lambda r: r.status)] == [v.IMS_ACCEPT, v.IMS_REJECT]


def test_there_is_nothing_to_do_in_ims_for_a_waiting_invoice_or_an_ineligible_record():
    rows, _ = run([b.document("NE-1", date(2026, 9, 5), 1000, itc_available="N")], [book("W-1", date(2026, 9, 6), 100, supplier=SUPPLIER_B)])
    assert {r.status: ims.recommend(r)[0] for r in rows} == {v.NOT_ELIGIBLE: None, v.WAITING_FOR_SUPPLIER: None}


# --------------------------------------------------------------------------------------------------- 180 days


def test_the_180_day_picture_is_dates_and_whether_it_is_paid():
    unpaid = ims.exposure(book("INV-1", date(2026, 4, 10), 1000), date(2026, 10, 19))
    assert unpaid["reversal_date"] == "2026-10-07" and unpaid["deadline_16_4"] == "2027-11-30" and unpaid["paid"] is False
    assert ims.age_days(unpaid, date(2026, 10, 19)) == 192 and ims.at_risk(unpaid, date(2026, 10, 19))
    assert not ims.at_risk(unpaid, date(2026, 8, 1))  # 113 days
    assert ims.at_risk(unpaid, date(2026, 9, 7))  # 150 days: near
    paid = ims.exposure(replace(book("INV-2", date(2026, 4, 10), 1000), paid_fully=True, paid_on=date(2026, 5, 1)),
                        date(2026, 10, 19))
    assert paid["paid"] is True and not ims.at_risk(paid, date(2026, 10, 19))
    assert ims.exposure(book("CN-1", date(2026, 4, 10), 100, kind="CREDIT_NOTE"), date(2026, 10, 19)) is None
