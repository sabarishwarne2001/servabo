"""Shared builders for the GST tests: invented GSTINs with valid check characters, GSTR-2B documents in the
documented shape, and the views the pure matching works on."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from app.services.gst import builder as b
from app.services.gst import parse
from app.services.gst.keys import number_key
from app.services.gst.matching import BookView, RecView
from app.services.helm import identity as ident
from tests.services.helm import factories

M = 1_000_000
RECIPIENT = b.make_gstin("27", "AAACM1234F")
SUPPLIER_A = b.make_gstin("27", "AABCS5555K")
SUPPLIER_B = b.make_gstin("29", "AAGCD7777P")


def parsed_return(sections: dict[str, list[dict[str, Any]]], period: str = "2026-09", *, wrap: str = "bare",
                  recipient: str = RECIPIENT) -> parse.ParsedReturn:
    document = b.gstr2b(recipient, period, sections, wrap=wrap)
    return parse.parse_file("gstr2b.json", b.to_bytes(document))[0]


def rec_views(parsed: parse.ParsedReturn) -> list[RecView]:
    return [RecView(
        id=uuid.uuid4(), section=r.section, kind=r.kind, period=parsed.period, supplier_gstin=r.supplier_gstin,
        supplier_name=r.supplier_name, supplier_name_key=ident.key_for(r.supplier_name) if r.supplier_name else None,
        number=r.number, doc_key=r.number_key, doc_date=r.doc_date, value_micros=r.value_micros,
        taxable_micros=r.taxable_micros, igst_micros=r.igst_micros, cgst_micros=r.cgst_micros,
        sgst_micros=r.sgst_micros, cess_micros=r.cess_micros, reverse_charge=r.reverse_charge,
        itc_available=r.itc_available, reason=r.reason, irn=r.irn.lower() if r.irn else None,
        original_key=r.original_key) for r in parsed.records]


def book(number: str, on: date, taxable: float, *, supplier: str = SUPPLIER_A, name: str = "Sahyadri Packaging",
         rate: int = 18, interstate: bool = False, kind: str = "INVOICE", irn: Optional[str] = None, **extra: Any) -> BookView:
    line = b.item(taxable, rate, interstate=interstate)
    igst, cgst, sgst = (int(round(line[k] * M)) for k in ("igst", "cgst", "sgst"))
    tax = igst + cgst + sgst
    fields: dict[str, Any] = dict(
        work_item_id=uuid.uuid4(), number=number, number_key=number_key(number), kind=kind, doc_date=on,
        supplier_gstin=supplier, supplier_name=name, supplier_name_key=ident.key_for(name),
        taxable_micros=int(round(taxable * M)), igst_micros=igst, cgst_micros=cgst, sgst_micros=sgst, cess_micros=0,
        tax_total_micros=tax, total_micros=int(round(taxable * M)) + tax, irn=irn)
    fields.update(extra)
    return BookView(**fields)


def supplier_invoices(documents, *, gstin: str = SUPPLIER_A, name: str = "Sahyadri Packaging", period: str = "09-2026",
                      filed: date = date(2026, 10, 9), notes: bool = False) -> dict[str, Any]:
    return b.supplier(gstin, name, documents, filed_on=filed, period=period, notes=notes)


def book_invoice(db, tenant, *, number, supplier, gstin, on, taxable, rate=18, name="Sahyadri Packaging",
                 buyer_gstin=RECIPIENT, extra=None, workspace=None):
    line = b.item(taxable, rate)
    tax = line["cgst"] + line["sgst"]
    entities = {"vendor_gstin": gstin, "buyer_gstin": buyer_gstin, "subtotal": f"{taxable:.2f}",
                "cgst_amount": f"{line['cgst']:.2f}", "sgst_amount": f"{line['sgst']:.2f}", "tax_amount": f"{tax:.2f}",
                "invoice_date": on.isoformat(), **(extra or {})}
    return factories.invoice(db, workspace=workspace or tenant.workspace, organization_id=tenant.organization.id, number=number,
                             supplier=name, amount=taxable + tax, on=on, supplier_gstin=gstin, extra=entities)


def statement(extra_sections=None, *, period="2026-09"):
    return b.to_bytes(b.gstr2b(RECIPIENT, period, {
        "b2b": [
            supplier_invoices([
                b.document("INV-1001", date(2026, 9, 5), 1000),
                b.document("INV-1003", date(2026, 9, 12), 2100),          # the books say 2000
                b.document("INV-2001", date(2026, 9, 14), 500),            # the books say INV-2002: suggested
                b.document("NE-1", date(2026, 9, 15), 300, itc_available="N", reason="P"),
            ]),
            supplier_invoices([b.document("X-7", date(2026, 9, 16), 700)], gstin=SUPPLIER_B, name="Deccan Plastics"),
        ],
        "cdnr": [supplier_invoices([b.document("CN-1", date(2026, 9, 20), 100, note="C")], notes=True)],
        **(extra_sections or {}),
    }))


