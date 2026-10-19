"""The sample company's GSTR-2B (Session F): Meridian Wholesale's own purchase invoices, reported the way a portal
download would carry them, with planted cases so the reconciliation has something true to find.

Generated from the documents already in the sample workspace (so it is right for whatever day the sample was
built), then imported through the real parser and the real engine. Every GSTIN is invented with a valid check
character. Planted (the tests assert that the reconciliation finds exactly this):

* a supplier that never filed (Konkan Logistics): all its invoices wait;
* an invoice reported late (the first of Pune Office Supplies, in the next month's GSTR-2B);
* a value difference (Bharat Industrial Gases' second invoice is reported ₹1,000 higher);
* a near match that only a person can confirm (Sahyadri's third invoice is reported with its number one off);
* a credit note (Shree Ganesh's, against the overcharge);
* an invoice whose credit GSTR-2B marks not available (Pune Office Supplies' second);
* a supplier record Meridian never received (Rajput Hardware Stores, invoice RH-8841);
* a reverse-charge record (Lakshmi Legal Associates, an advocate's fee);
* an unpaid invoice past 150 days (sample_company plants it: Pune Office Supplies, never paid).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.gst import GstReturn
from app.models.workspace import Workspace
from app.services.gst import books as books_module
from app.services.gst import builder, parse, store
from app.services.gst import vocabulary as v
from app.services.gst.keys import period_of
from app.services.helm import ledger

REPORTED_BY_OTHERS = (
    ("RH-8841", "Rajput Hardware Stores", ("27", "AABFR8841M"), 4_850),
    ("LLA-117", "Lakshmi Legal Associates", ("27", "AAEFL1170Q"), 25_000),
)


@dataclass
class Planted2B:
    never_filed_gstin: Optional[str] = None
    never_filed_invoices: list[str] = field(default_factory=list)
    late_number: Optional[str] = None
    difference_number: Optional[str] = None
    suggested_book_number: Optional[str] = None
    suggested_record_number: Optional[str] = None
    credit_note_number: Optional[str] = None
    not_eligible_number: Optional[str] = None
    not_in_books_number: Optional[str] = None
    reverse_charge_number: Optional[str] = None
    unpaid_number: Optional[str] = None
    periods: list[str] = field(default_factory=list)


def _date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001
        return Decimal(0)


def _next_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    return f"{year + (month == 12):04d}-{(month % 12) + 1:02d}"


def _slot(period: str, section: str, gstin: str, name: str, documents: dict[str, dict[tuple[str, str], dict[str, Any]]]
          ) -> list[dict[str, Any]]:
    holder = documents.setdefault(period, {}).setdefault((section, gstin), {"name": name, "docs": []})
    return holder["docs"]


def build_returns(db: Session, workspace: Workspace, *, today: Optional[date] = None,
                  user_id: Optional[uuid.UUID] = None) -> Planted2B:
    """Import the sample company's GSTR-2B returns (idempotent: a period already imported is left as it is)."""
    from app.services.helm import sample_company as sample

    today = today or date.today()
    last = period_of(date(today.year - (today.month == 1), ((today.month - 2) % 12) + 1, 1))
    planted = Planted2B()
    documents = books_module.load_documents(db, workspace)
    invoices = sorted((d for d in documents if d.role == ledger.ROLE_INVOICE
                       and books_module.f.gstin_of(d.entities.get("buyer_gstin")) == sample.GSTIN),
                      key=lambda d: (str(d.entities.get("invoice_date")), str(d.entities.get("invoice_number"))))
    notes = [d for d in documents if d.role == ledger.ROLE_CREDIT_NOTE]
    by_supplier = {s.gstin: s for s in sample.SUPPLIERS}
    seen: set[tuple[str, str]] = set()
    counters: dict[str, int] = {}
    payload: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for doc in invoices:
        e = doc.entities
        gstin = books_module.f.gstin_of(e.get("supplier_gstin") or e.get("vendor_gstin"))
        supplier = by_supplier.get(gstin or "")
        on = _date(e.get("invoice_date"))
        number = str(e.get("invoice_number") or "")
        if supplier is None or on is None or not number or (gstin, number) in seen:
            continue  # a copy of the same bill is one record
        seen.add((gstin or "", number))
        period = period_of(on)
        if period > last:
            continue
        counters[supplier.key] = counters.get(supplier.key, 0) + 1
        index = counters[supplier.key] - 1
        taxable = _money(e.get("subtotal"))
        reported, reported_period, eligible, reason = number, period, "Y", None
        if supplier.key == "konkan":
            planted.never_filed_gstin = gstin
            planted.never_filed_invoices.append(number)
            continue  # never filed: in no GSTR-2B
        if supplier.key == "pos" and index == 0 and _next_period(period) <= last:
            reported_period, planted.late_number = _next_period(period), number
        if supplier.key == "pos" and index == 1:
            eligible, reason, planted.not_eligible_number = "N", "P", number
        if supplier.key == "gases" and index == 1:
            taxable += Decimal(1000)
            planted.difference_number = number
        if supplier.key == "sahyadri" and index == 2:
            reported = number[:-1] + str((int(number[-1]) + 1) % 10)
            planted.suggested_book_number, planted.suggested_record_number = number, reported
        _slot(reported_period, "b2b", gstin or "", supplier.name, payload).append(
            builder.document(reported, on, taxable, itc_available=eligible, reason=reason))
    for doc in notes:
        e = doc.entities
        gstin = books_module.f.gstin_of(e.get("supplier_gstin"))
        on = _date(e.get("date"))
        supplier = by_supplier.get(gstin or "")
        number = str(e.get("credit_note_number") or "")
        if supplier is None or on is None or not number or period_of(on) > last:
            continue
        planted.credit_note_number = number
        _slot(period_of(on), "cdnr", gstin or "", supplier.name, payload).append(
            builder.document(number, on, _money(e.get("subtotal")), note="C"))
    first = min((period_of(_date(d.entities.get("invoice_date")) or today) for d in invoices), default=last)
    mid = sorted(payload)[len(payload) // 2] if payload else last
    for number, name, (state, pan), amount in REPORTED_BY_OTHERS:
        rcm = number.startswith("LLA")
        gstin = builder.make_gstin(state, pan)
        day = date(int(mid[:4]), int(mid[5:7]), 18)
        _slot(mid, "b2b", gstin, name, payload).append(
            builder.document(number, day, amount, reverse_charge=rcm, itc_available="N" if rcm else "Y"))
        if rcm:
            planted.reverse_charge_number = number
        else:
            planted.not_in_books_number = number
    payments = books_module.load_payments(db, workspace.id, [d.work_item_id for d in invoices])
    for doc in invoices:
        on = _date(doc.entities.get("invoice_date"))
        gstin = books_module.f.gstin_of(doc.entities.get("supplier_gstin"))
        if (on is not None and (today - on).days >= v.RISK_NEAR_DAYS and doc.work_item_id not in payments
                and by_supplier.get(gstin or "") is not None and by_supplier[gstin or ""].key == "pos"):
            planted.unpaid_number = str(doc.entities.get("invoice_number"))
            break
    periods = sorted(set(payload) | ({first} if first <= last else set()))
    planted.periods = [p for p in periods if first <= p <= last]
    for period in planted.periods:
        if db.execute(select(func.count()).select_from(GstReturn).where(
                GstReturn.workspace_id == workspace.id, GstReturn.period == period,
                GstReturn.status == v.RETURN_ACTIVE)).scalar_one():
            continue
        sections: dict[str, list[dict[str, Any]]] = {}
        for (section, gstin), holder in sorted(payload.get(period, {}).items()):
            year, month = int(period[:4]), int(period[5:7])
            filed = date(year + (month == 12), (month % 12) + 1, 9)
            sections.setdefault(section, []).append(builder.supplier(
                gstin, holder["name"], holder["docs"], filed_on=filed, period=f"{month:02d}{year}",
                notes=section == "cdnr"))
        data = builder.to_bytes(builder.gstr2b(sample.GSTIN, period, sections, wrap="status"))
        for parsed in parse.parse_file(f"GSTR2B_{period[5:]}{period[:4]}.json", data):
            store.import_parsed(db, workspace=workspace, parsed=parsed, user_id=user_id)
    return planted


__all__ = ["Planted2B", "build_returns"]
