"""IMS recommendations and the 180-day exposure: decision support on top of the matching, reasons always shown.

Servabo recommends; a person acts on the GST portal's Invoice Management System. Accept needs agreement with
the books and, where procurement data exists, goods received and no open dispute. Pending is the safe default.
Reject needs strong evidence: a duplicate of a record already accepted, a person's "not ours", or a three-way
matching dispute a person flagged against the supplier. Never Reject merely because Servabo has not seen the
invoice.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from app.services.gst import vocabulary as v
from app.services.gst.matching import BookView, MatchOut, section_16_4_deadline

CASE_DISPUTED = "DISPUTED"
CASE_NEEDS_REVIEW = "NEEDS_REVIEW"
CASE_OPEN = "OPEN"


def recommend(row: MatchOut) -> tuple[Optional[str], Optional[str]]:
    """(IMS action, the reason in words) for a row that has a supplier record; (None, None) when there is nothing
    to act on in IMS."""
    rec = row.record
    if rec is None:
        return None, None
    if row.decision == v.DECISION_NOT_OURS:
        return v.IMS_REJECT, "You marked this record 'not ours'. Reject it on the portal if it is not your purchase."
    if row.duplicate_of_record is not None:
        return v.IMS_REJECT, "The supplier reported this document twice; this copy duplicates one you already have."
    book = row.book
    if row.status == v.NOT_IN_BOOKS:
        return v.IMS_PENDING, ("Servabo has not seen this invoice. Keep it Pending while you upload or find it; "
                               "the portal may limit how long a record can stay Pending, so check its IMS page.")
    if row.status == v.SUGGESTED:
        return v.IMS_PENDING, "Confirm which of your invoices this is first; then it can be accepted."
    if row.status in (v.NOT_ELIGIBLE, v.REVERSE_CHARGE):
        return None, None
    if book is not None and book.case_status == CASE_DISPUTED:
        why = f" Reason given: {book.case_reason}" if book.case_reason else ""
        return v.IMS_REJECT, "A three-way-match dispute was flagged against this supplier's invoice." + why
    if row.status == v.MATCHED_WITH_DIFFERENCES:
        return v.IMS_PENDING, ("An amount differs from your books. Keep it Pending and ask the supplier to amend; "
                               "claim the lower figure meanwhile.")
    if book is not None and book.case_status == CASE_NEEDS_REVIEW:
        return v.IMS_PENDING, "Three-way matching has an open exception on this invoice. Settle it first."
    if book is not None and book.has_purchase_order and not book.has_receipt:
        return v.IMS_PENDING, "No goods receipt is recorded for the purchase order yet; goods not yet received."
    if row.status == v.NOTE:
        if book is not None:
            return v.IMS_ACCEPT, "The note agrees with the note in your books."
        return v.IMS_PENDING, "Servabo has not seen this credit or debit note; check it before accepting."
    if row.status == v.MATCHED:
        if book is not None and book.has_receipt:
            return v.IMS_ACCEPT, "Matches your books within tolerance and the goods are received."
        return v.IMS_ACCEPT, "Matches your books within tolerance; there is no purchase-order data to check."
    return v.IMS_PENDING, "Check this record before accepting."


def exposure(book: BookView, today: date) -> Optional[dict[str, Any]]:
    """The 180-day picture of one purchase invoice (credit notes have none). Dates only, so the stored value does
    not change from day to day; the age is worked out where it is read (`age_days`)."""
    if book.kind != v.KIND_INVOICE or book.doc_date is None:
        return None
    return {
        "invoice_date": book.doc_date.isoformat(),
        "reversal_date": (book.doc_date + timedelta(days=v.RISK_LIMIT_DAYS)).isoformat(),
        "deadline_16_4": section_16_4_deadline(book.doc_date).isoformat(),
        "paid": bool(book.paid_fully),
        "paid_on": book.paid_on.isoformat() if book.paid_on else None,
    }


def age_days(risk: Optional[dict[str, Any]], today: date) -> Optional[int]:
    if not risk or not risk.get("invoice_date"):
        return None
    return (today - date.fromisoformat(risk["invoice_date"])).days


def at_risk(risk: Optional[dict[str, Any]], today: date) -> bool:
    """Unpaid and at 150 days or more from the invoice date (near or past 180)."""
    days = age_days(risk, today)
    return bool(risk) and not risk.get("paid") and days is not None and days >= v.RISK_NEAR_DAYS


__all__ = ["age_days", "at_risk", "exposure", "recommend"]
