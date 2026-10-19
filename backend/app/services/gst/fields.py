"""The invoice fields GST Credit reads, under the names the extraction prompt asks for.

`llm_service.ENTITY_EXTRACTION_PROMPT_TEMPLATE` asks the model for the first name of each list; models
drift ("CGST", "central_tax"), so the later names are what a real answer is accepted under.
`tests/services/test_extraction_prompt_contract.py` keeps the two in step: every concept below must be
asked for by the production prompt.

These lists only name things. Reading them (case, separators, nesting) is `corroboration.fields.flatten`.
"""

from __future__ import annotations

from typing import Final

INVOICE_NUMBER_KEYS: Final = ("invoice_number", "invoice_no", "bill_number", "bill_no", "document_number", "number",
                              "invoice_id")
#: A credit or debit note's own number. `invoice_number` is accepted too: models put it there.
NOTE_NUMBER_KEYS: Final = ("credit_note_number", "debit_note_number", "credit_number", "note_number",
                           "invoice_number", "document_number", "number")
INVOICE_DATE_KEYS: Final = ("invoice_date", "bill_date", "document_date", "date", "dated")
SELLER_GSTIN_KEYS: Final = ("vendor_gstin", "supplier_gstin", "seller_gstin", "gstin", "gst_number")
BUYER_GSTIN_KEYS: Final = ("buyer_gstin", "customer_gstin", "recipient_gstin", "bill_to_gstin")
SELLER_NAME_KEYS: Final = ("vendor_name", "supplier_name", "seller_name", "vendor", "supplier", "seller")

TAXABLE_VALUE_KEYS: Final = ("subtotal", "taxable_value", "taxable_amount", "sub_total", "net_amount")
CGST_KEYS: Final = ("cgst_amount", "cgst", "central_gst", "central_tax")
SGST_KEYS: Final = ("sgst_amount", "sgst", "utgst_amount", "state_gst", "state_tax")
IGST_KEYS: Final = ("igst_amount", "igst", "integrated_gst", "integrated_tax")
CESS_KEYS: Final = ("cess_amount", "cess")
TAX_TOTAL_KEYS: Final = ("tax_amount", "tax", "gst_amount", "total_tax", "total_gst")
TOTAL_KEYS: Final = ("total_amount", "grand_total", "invoice_total", "total", "amount_due", "net_payable",
                     "total_payable")

PLACE_OF_SUPPLY_KEYS: Final = ("place_of_supply", "pos")
REVERSE_CHARGE_KEYS: Final = ("reverse_charge", "reverse_charge_applicable", "rcm")
IRN_KEYS: Final = ("irn", "e_invoice_irn", "invoice_reference_number")
NOTE_TYPE_KEYS: Final = ("note_type", "credit_debit_note", "note_kind")
ORIGINAL_INVOICE_NUMBER_KEYS: Final = ("original_invoice_number", "invoice_reference", "against_invoice",
                                       "reference_invoice", "original_invoice", "invoice_ref")
ORIGINAL_INVOICE_DATE_KEYS: Final = ("original_invoice_date", "reference_invoice_date", "invoice_reference_date")

#: Inside one entry of `line_items`.
LINE_HSN_KEYS: Final = ("hsn_sac", "hsn", "hsn_code", "sac", "sac_code")
LINE_TAXABLE_VALUE_KEYS: Final = ("taxable_value", "taxable_amount")
LINE_TAX_RATE_KEYS: Final = ("tax_rate", "gst_rate", "rate_of_tax", "gst_percent")


# --------------------------------------------------------------------------------------------- reading

import re as _re
from typing import Any, Mapping, Optional, Sequence

_GSTIN_SHAPE = _re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def gstin_of(raw: Any) -> Optional[str]:
    """A GSTIN as printed ("27 AAAAA0000A 1Z5", "GSTIN: 27AAAAA0000A1Z5") -> its 15 characters, else None."""
    if raw is None:
        return None
    text = _re.sub(r"[^0-9A-Za-z]", "", str(raw)).upper()
    if len(text) > 15:
        found = _re.search(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", text)
        text = found.group(0) if found else text
    return text if _GSTIN_SHAPE.match(text) else None


def first(flat: Mapping[str, Any], names: Sequence[str]) -> Any:
    """The first listed key present with a value (`flat` is `corroboration.fields.flatten(entities)`)."""
    for name in names:
        if name in flat and flat[name] not in (None, "", []):
            return flat[name]
    return None
