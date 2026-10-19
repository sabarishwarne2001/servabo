"""Builds GSTR-2B JSON in the documented shape, from invented data: the sample company's returns and the test
fixtures. Every GSTIN made here has a valid check character and an invented PAN, so nothing here is a real
taxpayer. The shape follows the format described in the build brief and is **unverified against a real portal
download** (docs/product/GST-CREDIT.md)."""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from app.services.entities.normalize import gstin_check_char


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    """A GSTIN with a valid check character: state code (2 digits), PAN (10), entity number, 'Z', check."""
    first14 = f"{state}{pan}{entity}Z"
    return first14 + gstin_check_char(first14)


def _money(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _d(day: date) -> str:
    return f"{day.day:02d}-{day.month:02d}-{day.year}"


def item(taxable: Any, rate: int = 18, *, interstate: bool = False, cess: Any = 0, number: int = 1) -> dict[str, Any]:
    """One tax line: intra-state splits the tax into CGST and SGST, inter-state is all IGST."""
    taxable = Decimal(str(taxable))
    tax = (taxable * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if interstate:
        heads = {"igst": _money(tax), "cgst": 0, "sgst": 0}
    else:
        half = (tax / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        heads = {"igst": 0, "cgst": _money(half), "sgst": _money(half)}
    return {"num": number, "rt": rate, "txval": _money(taxable), **heads, "cess": _money(cess)}


def document(number: str, on: date, taxable: Any, *, rate: int = 18, interstate: bool = False, pos: str = "27",
             reverse_charge: bool = False, itc_available: str = "Y", reason: Optional[str] = None, irn: Optional[str] = None,
             note: Optional[str] = None, value: Optional[Any] = None, original: Optional[tuple[str, date]] = None,
             cess: Any = 0) -> dict[str, Any]:
    """An invoice (`inum`) or, with `note` "C"/"D", a credit/debit note (`ntnum`)."""
    line = item(taxable, rate, interstate=interstate, cess=cess)
    total = value if value is not None else Decimal(str(taxable)) + Decimal(str(line["igst"] + line["cgst"] + line["sgst"] + line["cess"]))
    doc: dict[str, Any] = {
        ("ntnum" if note else "inum"): number, "dt": _d(on), "val": _money(total), "pos": pos,
        "rev": "Y" if reverse_charge else "N", "itcavl": itc_available, "diffprcnt": "1", "srctyp": "e-Invoice" if irn else "GSTR1",
        "items": [line],
    }
    if note:
        doc["typ"] = note
        doc["suptyp"] = "Regular"
    else:
        doc["typ"] = "R"
    if reason:
        doc["rsn"] = reason
    if irn:
        doc["irn"] = irn
        doc["irngendate"] = _d(on)
    if original:
        doc["oinum" if not note else "ontnum"] = original[0]
        doc["oidt" if not note else "ontdt"] = _d(original[1])
    return doc


def supplier(gstin: str, name: str, documents: list[dict[str, Any]], *, filed_on: date, period: str,
             notes: bool = False) -> dict[str, Any]:
    return {"ctin": gstin, "trdnm": name, "supfildt": _d(filed_on), "supprd": period, ("nt" if notes else "inv"): documents}


def gstr2b(recipient: str, period: str, sections: dict[str, list[dict[str, Any]]], *, generated_on: Optional[date] = None,
           version: str = "1.0", wrap: str = "status") -> dict[str, Any]:
    """The statement. `period` is "YYYY-MM". `wrap`: "status" = {status, data: {chksum, data}}, "data" = {data}, "bare"."""
    year, month = int(period[:4]), int(period[5:7])
    generated = generated_on or date(year + (month == 12), (month % 12) + 1, 14)
    body = {"gstin": recipient, "rtnprd": f"{month:02d}{year}", "version": version, "gendt": _d(generated),
            "itcsumm": {"cpsumm": {"b2b": {"igst": 0, "cgst": 0, "sgst": 0, "cess": 0}}}, "docdata": sections}
    if wrap == "status":
        return {"status": 1, "data": {"chksum": "invented", "data": body}}
    if wrap == "data":
        return {"data": body}
    return body


def to_bytes(document_: dict[str, Any]) -> bytes:
    return json.dumps(document_).encode("utf-8")


__all__ = ["document", "gstr2b", "item", "make_gstin", "supplier", "to_bytes"]
