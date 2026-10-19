"""What the GST Credit page shows: the six figures, the supplier list and the invoice list, read from the stored
reconciliation (`gst_matches`). Amounts are micros of rupees. Nothing on screen is invented: every figure is a sum
or a count over stored rows, and each comes with its one-line meaning and a law link.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import Select, and_, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.types import Boolean, Date

from app.models.gst import GstMatch, GstReturn
from app.services.gst import vocabulary as v

CLAIMABLE_STATUSES = (v.MATCHED, v.MATCHED_WITH_DIFFERENCES, v.NOTE)

FIGURE_MEANING = {
    "claimable_now": ("Claimable now", "Credit on invoices the supplier has reported and that agree with your books "
                      "(net of credit and debit notes).", v.LAW_ITC_2B),
    "waiting": ("Waiting for suppliers", "Invoices in your books that no imported GSTR-2B shows. The credit is "
                "deferred until the supplier reports them.", v.LAW_TIME_LIMIT),
    "differences": ("Differences", "Reported invoices whose amounts differ from your books by more than the "
                    "tolerance. Claim the lower figure and ask the supplier to amend.", v.LAW_ITC_2B),
    "at_risk_180": ("At risk under the 180-day rule", "Invoices not recorded as paid in Servabo that are 150 days "
                    "old or more. If the supplier is not paid within 180 days of the invoice date, credit taken "
                    "may have to be reversed, and interest may apply.", v.LAW_180_DAYS),
    "not_in_books": ("Not in your books", "Suppliers reported these to you; Servabo has not seen the invoice. "
                     "Upload it, or act in IMS.", v.LAW_IMS),
    "not_eligible": ("Not eligible per GSTR-2B", "GSTR-2B marks the credit on these as not available.",
                     v.LAW_ITC_2B),
}


def scope(query: Select, *, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str], period: Optional[str]) -> Select:
    query = query.where(GstMatch.workspace_id.in_(list(workspace_ids)))
    if gstin:
        query = query.where(GstMatch.gstin == gstin)
    if period:
        month_of_book = func.to_char(GstMatch.doc_date, "YYYY-MM")
        query = query.where(or_(GstMatch.period_first_seen == period,
                                and_(GstMatch.record_id.is_(None), month_of_book == period)))
    return query


def _risk_filter(today: date):
    cutoff = today - timedelta(days=v.RISK_NEAR_DAYS)
    return and_(GstMatch.risk.isnot(None), GstMatch.work_item_id.isnot(None),
                cast(GstMatch.risk["paid"].astext, Boolean).is_(False),
                cast(GstMatch.risk["invoice_date"].astext, Date) <= cutoff)


def figures(db: Session, *, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str] = None,
            period: Optional[str] = None, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    duplicate = GstMatch.notes.contains([{"code": "DUPLICATE_RECORD"}])
    not_ours = GstMatch.decision == v.DECISION_NOT_OURS
    supplier = func.coalesce(GstMatch.supplier_gstin, GstMatch.supplier_name)
    differs_amount = func.coalesce(GstMatch.tax_micros, 0) - func.coalesce(GstMatch.itc_micros, 0)
    query = scope(select(
        func.coalesce(func.sum(case((GstMatch.status.in_(CLAIMABLE_STATUSES), GstMatch.itc_micros), else_=0)), 0),
        func.count(case((GstMatch.status.in_((v.MATCHED, v.MATCHED_WITH_DIFFERENCES)), 1))),
        func.coalesce(func.sum(case((GstMatch.status == v.WAITING_FOR_SUPPLIER, GstMatch.itc_micros), else_=0)), 0),
        func.count(case((GstMatch.status == v.WAITING_FOR_SUPPLIER, 1))),
        func.count(func.distinct(case((GstMatch.status == v.WAITING_FOR_SUPPLIER, supplier)))),
        func.count(case((GstMatch.status == v.MATCHED_WITH_DIFFERENCES, 1))),
        func.coalesce(func.sum(case((GstMatch.status == v.MATCHED_WITH_DIFFERENCES, differs_amount), else_=0)), 0),
        func.count(case((_risk_filter(today), 1))),
        func.coalesce(func.sum(case((_risk_filter(today), GstMatch.tax_micros), else_=0)), 0),
        func.count(case((and_(GstMatch.status == v.NOT_IN_BOOKS, ~duplicate, ~func.coalesce(not_ours, False)), 1))),
        func.coalesce(func.sum(case((and_(GstMatch.status == v.NOT_IN_BOOKS, ~duplicate,
                                          ~func.coalesce(not_ours, False)), GstMatch.itc_micros), else_=0)), 0),
        func.count(case((GstMatch.status == v.NOT_ELIGIBLE, 1))),
        func.coalesce(func.sum(case((GstMatch.status == v.NOT_ELIGIBLE, GstMatch.itc_micros), else_=0)), 0),
        func.count(case((GstMatch.status == v.SUGGESTED, 1))),
        func.count(case((GstMatch.status == v.REVERSE_CHARGE, 1))),
        func.count(case((GstMatch.status == v.NOTE, 1))),
        func.count(),
    ), workspace_ids=workspace_ids, gstin=gstin, period=period)
    row = db.execute(query).one()
    (claim_micros, claim_n, wait_micros, wait_n, wait_suppliers, diff_n, diff_micros, risk_n, risk_micros,
     nib_n, nib_micros, ne_n, ne_micros, sug_n, rcm_n, note_n, total_n) = row
    values = {
        "claimable_now": {"amount_micros": int(claim_micros), "count": int(claim_n)},
        "waiting": {"amount_micros": int(wait_micros), "count": int(wait_n), "suppliers": int(wait_suppliers)},
        "differences": {"amount_micros": int(diff_micros), "count": int(diff_n)},
        "at_risk_180": {"amount_micros": int(risk_micros), "count": int(risk_n)},
        "not_in_books": {"amount_micros": int(nib_micros), "count": int(nib_n)},
        "not_eligible": {"amount_micros": int(ne_micros), "count": int(ne_n)},
    }
    out = []
    for key, (title, meaning, law) in FIGURE_MEANING.items():
        out.append({"key": key, "title": title, "meaning": meaning, "law": law, **values[key]})
    return {"figures": out, "suggested": int(sug_n), "reverse_charge": int(rcm_n), "notes": int(note_n),
            "lines": int(total_n), "currency": "INR", "disclaimer": v.NOT_ADVICE}


def returns_overview(db: Session, *, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str] = None) -> dict[str, Any]:
    query = select(GstReturn).where(GstReturn.workspace_id.in_(list(workspace_ids)),
                                    GstReturn.status == v.RETURN_ACTIVE).order_by(GstReturn.gstin, GstReturn.period.desc())
    if gstin:
        query = query.where(GstReturn.gstin == gstin)
    rows = list(db.execute(query).scalars())
    gstins = sorted({r.gstin for r in rows})
    last = max(rows, key=lambda r: r.imported_at, default=None)
    return {
        "gstins": gstins,
        "periods": sorted({r.period for r in rows}, reverse=True),
        "last_import": None if last is None else {
            "imported_at": last.imported_at.isoformat(), "version": last.version, "period": last.period,
            "gstin": last.gstin, "generated_on": last.generated_on.isoformat() if last.generated_on else None,
        },
    }


def supplier_list(db: Session, *, workspace_ids: Sequence[uuid.UUID], gstin: Optional[str], period: Optional[str],
                  offset: int, limit: int) -> dict[str, Any]:
    """Who has not reported what, oldest first."""
    supplier_key = func.coalesce(GstMatch.supplier_gstin, GstMatch.supplier_name, "")
    waiting_n = func.count(case((GstMatch.status == v.WAITING_FOR_SUPPLIER, 1)))
    query = scope(select(
        GstMatch.supplier_gstin, func.max(GstMatch.supplier_name),
        waiting_n,
        func.coalesce(func.sum(case((GstMatch.status == v.WAITING_FOR_SUPPLIER, GstMatch.itc_micros), else_=0)), 0),
        func.min(case((GstMatch.status == v.WAITING_FOR_SUPPLIER, GstMatch.doc_date))),
        func.count(case((GstMatch.status == v.NOT_IN_BOOKS, 1))),
        func.count(case((GstMatch.status == v.MATCHED_WITH_DIFFERENCES, 1))),
        func.count(case((GstMatch.status == v.SUGGESTED, 1))),
        func.count(case((GstMatch.status.in_((v.MATCHED, v.MATCHED_WITH_DIFFERENCES)), 1))),
    ), workspace_ids=workspace_ids, gstin=gstin, period=period).group_by(supplier_key, GstMatch.supplier_gstin)
    rows = db.execute(query).all()
    items = [{
        "supplier_gstin": r[0], "supplier_name": r[1], "waiting_count": int(r[2]), "waiting_micros": int(r[3]),
        "oldest_waiting": r[4].isoformat() if r[4] else None, "not_in_books_count": int(r[5]),
        "differences_count": int(r[6]), "suggested_count": int(r[7]), "matched_count": int(r[8]),
    } for r in rows if r[2] or r[5] or r[6] or r[7]]
    items.sort(key=lambda s: (s["oldest_waiting"] is None, s["oldest_waiting"] or "", -s["waiting_micros"],
                              s["supplier_name"] or ""))
    return {"total": len(items), "items": items[offset:offset + limit], "offset": offset, "limit": limit}


__all__ = ["CLAIMABLE_STATUSES", "FIGURE_MEANING", "figures", "returns_overview", "scope", "supplier_list"]
