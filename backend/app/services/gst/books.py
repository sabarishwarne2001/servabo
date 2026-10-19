"""The books: the purchase invoices and notes Servabo has read, as the GST reconciliation sees them.

A document counts for a return when it is a purchase invoice or note (Helm's document roles) whose buyer GSTIN is
the return's GSTIN. When the buyer GSTIN is missing it counts if it is not one of "our" documents (the seller is
not one of Helm's identities, plus the return's own GSTIN), so no new setting is needed. Documents in another
currency, and those that carry no GST, are not expected in GSTR-2B and are left out.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import normalize as nz
from app.models.helm import HelmSettlement
from app.models.procurement import ProcurementCase
from app.models.workspace import Workspace
from app.services.corroboration import fields as corroboration_fields
from app.services.gst import fields as f
from app.services.gst import vocabulary as v
from app.services.gst.keys import number_key
from app.services.gst.matching import BookView
from app.services.helm import identity as ident
from app.services.helm import ledger, ledger_store

CASE_LIVE_EXCLUDED = "SUPERSEDED"
PAID_SLACK_MICROS = 1_000_000


def _money(raw: Any) -> Optional[int]:
    return ledger.read_money(raw, "INR")


def _date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return nz.parse_document_date(str(raw), format_hint="DD/MM/YYYY")
    except Exception:  # noqa: BLE001 - an unreadable date is a missing date
        return None


def our_identities(db: Session, workspace_id: uuid.UUID, gstin: str) -> ident.Identities:
    base = ledger_store.identities_for_workspace(db, workspace_id)
    own = ident.tax_key(gstin)
    return ident.Identities(base.name_keys, frozenset(base.tax_keys | ({own} if own else set())))


def book_view(fact: ledger.DocumentFacts, *, identities: ident.Identities, gstin: str,
              cases: Mapping[uuid.UUID, ProcurementCase], settlements: Mapping[uuid.UUID, HelmSettlement]) -> Optional[BookView]:
    """The document as a book entry for the return of `gstin`, or None when it is not expected in that GSTR-2B."""
    flat = corroboration_fields.flatten(fact.entities or {})
    buyer_gstin = f.gstin_of(f.first(flat, f.BUYER_GSTIN_KEYS))
    if buyer_gstin is not None:
        if buyer_gstin != gstin:
            return None
    elif ident.we_are_seller(fact.entities, identities):
        return None
    seller_party = ident.seller(fact.entities)
    seller_gstin = f.gstin_of(f.first(flat, f.SELLER_GSTIN_KEYS)) or f.gstin_of(seller_party.tax_id)
    if seller_gstin == gstin:
        return None
    currency = (nz.currency_code(str(f.first(flat, ("currency", "currency_code", "ccy")) or "")) or fact.currency or "INR")
    if currency != "INR":
        return None

    taxable = _money(f.first(flat, f.TAXABLE_VALUE_KEYS))
    igst = _money(f.first(flat, f.IGST_KEYS))
    cgst = _money(f.first(flat, f.CGST_KEYS))
    sgst = _money(f.first(flat, f.SGST_KEYS))
    cess = _money(f.first(flat, f.CESS_KEYS))
    heads = [x for x in (igst, cgst, sgst, cess) if x is not None]
    tax_total = _money(f.first(flat, f.TAX_TOTAL_KEYS))
    if tax_total is None and heads:
        tax_total = sum(heads)
    if (tax_total is not None and tax_total <= 0 and not heads) or (heads and sum(heads) <= 0):
        return None  # no GST on it: not expected in GSTR-2B
    if tax_total is None and seller_gstin is None:
        return None
    total = fact.total_micros if fact.total_micros is not None else _money(f.first(flat, f.TOTAL_KEYS))

    is_note = fact.role == ledger.ROLE_CREDIT_NOTE
    raw_number = f.first(flat, f.NOTE_NUMBER_KEYS if is_note else f.INVOICE_NUMBER_KEYS) or fact.document_number
    number = str(raw_number).strip()[:64] if raw_number else None
    note_type = str(f.first(flat, f.NOTE_TYPE_KEYS) or "").strip().lower()
    kind = v.KIND_INVOICE if not is_note else (v.KIND_DEBIT_NOTE if note_type.startswith("d") else v.KIND_CREDIT_NOTE)
    doc_date = fact.document_date or _date(f.first(flat, f.INVOICE_DATE_KEYS))
    irn = f.first(flat, f.IRN_KEYS)

    case = cases.get(fact.work_item_id)
    settlement = settlements.get(fact.work_item_id)
    paid_on = settlement.paid_on if settlement is not None and settlement.state == "PAID" else None
    paid_fully = bool(paid_on) and (settlement.paid_amount_micros is None or total is None
                                    or settlement.paid_amount_micros + PAID_SLACK_MICROS >= total)
    return BookView(
        work_item_id=fact.work_item_id, number=number, number_key=number_key(number), kind=kind, doc_date=doc_date,
        supplier_gstin=seller_gstin, supplier_name=seller_party.name, supplier_name_key=seller_party.name_key,
        taxable_micros=taxable, igst_micros=igst, cgst_micros=cgst, sgst_micros=sgst, cess_micros=cess,
        tax_total_micros=tax_total, total_micros=total, irn=str(irn).strip()[:64] if irn else None,
        case_status=case.status if case is not None else None,
        case_reason=(case.resolution_reason if case is not None else None),
        has_purchase_order=bool(case is not None and case.po_work_item_id),
        has_receipt=bool(case is not None and case.receipt_work_item_id),
        paid_on=paid_on, paid_fully=paid_fully,
    )


def load_books(db: Session, workspace: Workspace, gstin: str) -> list[BookView]:
    facts = ledger_store.document_facts(db, workspace, roles=(ledger.ROLE_INVOICE, ledger.ROLE_CREDIT_NOTE))
    if not facts:
        return []
    ids = [fact.work_item_id for fact in facts]
    cases: dict[uuid.UUID, ProcurementCase] = {}
    for case in db.execute(select(ProcurementCase).where(
            ProcurementCase.workspace_id == workspace.id, ProcurementCase.invoice_work_item_id.in_(ids),
            ProcurementCase.status != CASE_LIVE_EXCLUDED).order_by(ProcurementCase.created_at)).scalars():
        cases[case.invoice_work_item_id] = case  # the latest case wins
    settlements = {s.work_item_id: s for s in db.execute(
        select(HelmSettlement).where(HelmSettlement.workspace_id == workspace.id,
                                     HelmSettlement.work_item_id.in_(ids))).scalars()}
    identities = our_identities(db, workspace.id, gstin)
    books = (book_view(fact, identities=identities, gstin=gstin, cases=cases, settlements=settlements) for fact in facts)
    return [b for b in books if b is not None]


__all__ = ["book_view", "load_books", "our_identities"]
