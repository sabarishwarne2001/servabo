"""Indian GST on a posting object (Final session 1, 3C): the pieces an Indian books system asks for beside a purchase bill.

A purchase bill in Zoho Books India wants the vendor's GSTIN, the vendor's state (source of supply), the buyer's state (destination of
supply), a GST treatment, and on every line the HSN or SAC code and a tax code. Tally Prime wants the tax booked to the right ledger:
CGST and SGST (two ledgers, half each) when buyer and vendor are in the same state, IGST (one ledger) when they are not.

Everything here is a pure function over what the document says. It never invents a figure: a state, a head or a rate it cannot read is
left out, and a mapping that requires it then says so at render time instead of posting a wrong bill.

Sources: the GSTIN's first two digits are the state code (CBIC GSTIN structure); the two-letter state codes are the ones Zoho Books
uses for `source_of_supply` / `destination_of_supply` (Zoho Books API v3 GST fields, read through a secondary source on 2026-10-22; the
official page could not be opened from the build sandbox: see docs/hardening/UPGRADE-AUDIT.md "Unverified").
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping, Optional

#: GST state code -> the two letters Zoho Books uses.
STATE_LETTERS: dict[str, str] = {
    "01": "JK", "02": "HP", "03": "PB", "04": "CH", "05": "UT", "06": "HR", "07": "DL", "08": "RJ", "09": "UP", "10": "BR",
    "11": "SK", "12": "AR", "13": "NL", "14": "MN", "15": "MZ", "16": "TR", "17": "ML", "18": "AS", "19": "WB", "20": "JH",
    "21": "OD", "22": "CG", "23": "MP", "24": "GJ", "26": "DD", "27": "MH", "29": "KA", "30": "GA", "31": "LD", "32": "KL",
    "33": "TN", "34": "PY", "35": "AN", "36": "TS", "37": "AP", "38": "LA", "97": "OT",
}
#: The rate slabs a line is snapped to (a percentage), so a rounding difference of a paisa still finds its tax code.
SLABS: tuple[Decimal, ...] = tuple(Decimal(x) for x in ("0", "0.25", "3", "5", "12", "18", "28"))
_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def valid_gstin(raw: Any) -> Optional[str]:
    text = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
    return text if _GSTIN.match(text) else None


def state_of(raw: Any) -> Optional[str]:
    """The two-digit state code from a GSTIN, or from a place of supply written "27", "27-Maharashtra" or "Maharashtra (27)"."""
    gstin = valid_gstin(raw)
    if gstin:
        return gstin[:2] if gstin[:2] in STATE_LETTERS else None
    match = re.search(r"(?<!\d)(\d{2})(?!\d)", str(raw or ""))
    return match.group(1) if match and match.group(1) in STATE_LETTERS else None


def slab_of(rate: Decimal) -> Optional[Decimal]:
    nearest = min(SLABS, key=lambda s: abs(s - rate))
    return nearest if abs(nearest - rate) <= Decimal("0.6") else None


def tax_key(intra: bool, rate: Decimal) -> Optional[str]:
    """"GST18" (CGST+SGST at 9% each) or "IGST18": the key a customer's `taxes` lookup table maps to their books' tax id."""
    slab = slab_of(rate)
    if slab is None:
        return None
    text = format(slab.normalize(), "f")
    return f"{'GST' if intra else 'IGST'}{text}"


def describe(*, vendor_gstin: Any, buyer_gstin: Any, place_of_supply: Any, cgst: Optional[Decimal], sgst: Optional[Decimal],
             igst: Optional[Decimal], cess: Optional[Decimal]) -> dict[str, Any]:
    """The `gst` block of the posting object, or {} when the document shows no sign of GST at all."""
    vendor = valid_gstin(vendor_gstin)
    heads = any(x for x in (cgst, sgst, igst))
    if not vendor and not heads:
        return {}
    vendor_state = state_of(vendor)
    destination_state = state_of(buyer_gstin) or state_of(place_of_supply)
    if heads:
        intra: Optional[bool] = bool((cgst or 0) or (sgst or 0)) and not (igst or 0)
    elif vendor_state and destination_state:
        intra = vendor_state == destination_state
    else:
        intra = None
    out: dict[str, Any] = {"treatment": "business_gst" if vendor else "business_none"}
    if vendor:
        out["vendor_gstin"] = vendor
    for key, value in (("vendor_state", vendor_state), ("destination_state", destination_state),
                       ("vendor_state_code", STATE_LETTERS.get(vendor_state or "")),
                       ("destination_state_code", STATE_LETTERS.get(destination_state or ""))):
        if value:
            out[key] = value
    if intra is not None:
        out["intra_state"] = intra
    for key, value in (("cgst", cgst), ("sgst", sgst), ("igst", igst), ("cess", cess)):
        if value is not None:
            out[key] = format(Decimal(value), "f")
    return out


def line_key(gst: Mapping[str, Any], *, line_amount: Optional[Decimal], line_tax: Optional[Decimal], subtotal: Optional[Decimal],
             tax_total: Optional[Decimal]) -> Optional[str]:
    """The tax code of one line, from its own tax when it states one, else from the document's overall rate."""
    intra = gst.get("intra_state")
    if intra is None:
        return None
    if line_amount and line_tax is not None:
        rate = Decimal(line_tax) * 100 / Decimal(line_amount)
    elif subtotal and tax_total is not None:
        rate = Decimal(tax_total) * 100 / Decimal(subtotal)
    else:
        return None
    return tax_key(bool(intra), rate)


__all__ = ["STATE_LETTERS", "describe", "line_key", "slab_of", "state_of", "tax_key", "valid_gstin"]
