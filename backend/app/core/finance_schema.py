"""The fields Servabo reads off a document, in one place (Session J).

Two things used to list them separately and drifted apart: the extraction prompt
(`llm_service.ENTITY_EXTRACTION_PROMPT_TEMPLATE`) and the automation builder's `STANDARD_FIELDS`, which still named the
old six-field prompt (`date`, no GSTINs, no tax heads, no due date, no IRN). Both are now built from the table below:

  * the prompt's field lists are rendered by `prompt_block`, character for character what the prompt said before
    (`tests/services/test_finance_schema.py` pins that), and
  * the builder offers `FIELDS` with their labels, types, examples and the document type they belong to.

`tests/services/test_finance_schema.py` also fails when the prompt text and this table disagree, which is what happens
if someone edits one by hand.

This module is pure data. The alias map (every name a model may use for a field: `supplier_gstin`, `gstin`,
`gst_number` for `vendor_gstin`) is built in `app/services/automation/document_fields.py`, from the key lists the batch
canonical layer, the GST Credit engine and Helm already keep, so there is still one list of aliases per concept.

Field types: `string`, `number`, `money` (an amount; a currency goes with it), `date`, `boolean`, `array`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional

STRING: Final = "string"
NUMBER: Final = "number"
MONEY: Final = "money"
DATE: Final = "date"
BOOLEAN: Final = "boolean"
ARRAY: Final = "array"

#: Document types a field group belongs to, as the extraction prompt names them.
GROUP_COMMERCIAL: Final = "Invoice, receipt or purchase order"
GROUP_RESUME: Final = "Résumé"
GROUP_CONTRACT: Final = "Contract"


@dataclass(frozen=True)
class DocField:
    key: str
    label: str
    type: str
    example: str
    group: str = GROUP_COMMERCIAL
    #: What follows "key:" in the prompt line ("" for a bare key).
    prompt_note: str = ""
    #: The set the field is chosen from (value, label), when it has a short fixed list.
    options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LineField:
    key: str
    label: str
    type: str
    prompt_note: str = ""


FIELDS: Final[tuple[DocField, ...]] = (
    DocField("invoice_number", "Invoice number", STRING, "INV-2231", prompt_note="the number printed on an invoice, bill or credit/debit note"),
    DocField("invoice_date", "Invoice date", DATE, "2026-09-01", prompt_note="the date printed on an invoice, bill or credit/debit note"),
    DocField("po_date", "Purchase order date", DATE, "2026-08-20", prompt_note="the date of a purchase order"),
    DocField("receipt_date", "Receipt date", DATE, "2026-08-30", prompt_note="the date goods were received, on a goods receipt"),
    DocField("delivery_date", "Delivery date", DATE, "2026-09-10", prompt_note="the delivery date a purchase order asks for"),
    DocField("due_date", "Due date", DATE, "2026-10-01"),
    DocField("payment_terms", "Payment terms", STRING, "Net 45", prompt_note='as printed, for example "Net 45"'),
    DocField("po_number", "Purchase order number", STRING, "PO-5001", prompt_note="the purchase order the document refers to, or its own number on a purchase order"),
    DocField("receipt_number", "Receipt number", STRING, "GRN-118", prompt_note="the number of a goods receipt or delivery note"),
    DocField("vendor_name", "Supplier name", STRING, "Acme Supplies Ltd", prompt_note="the seller"),
    DocField("vendor_gstin", "Supplier GSTIN", STRING, "27AAAAA0000A1Z5", prompt_note="the seller's 15-character GSTIN"),
    DocField("vendor_pan", "Supplier PAN", STRING, "AAAAA0000A"),
    DocField("vendor_address", "Supplier address", STRING, "12 MIDC, Pune"),
    DocField("vendor_email", "Supplier email", STRING, "accounts@acme.example"),
    DocField("vendor_bank_account", "Supplier bank account", STRING, "00112233445566", prompt_note="the seller's bank account number, as printed"),
    DocField("vendor_ifsc", "Supplier IFSC", STRING, "HDFC0001234"),
    DocField("udyam_number", "Supplier Udyam number", STRING, "UDYAM-MH-00-0000000", prompt_note="the seller's Udyam registration number"),
    DocField("customer_name", "Customer name", STRING, "Bharat Traders", prompt_note="the buyer (bill to)"),
    DocField("buyer_gstin", "Buyer GSTIN", STRING, "29BBBBB1111B1Z6", prompt_note="the buyer's 15-character GSTIN"),
    DocField("place_of_supply", "Place of supply", STRING, "Maharashtra"),
    DocField("currency", "Currency", STRING, "INR", prompt_note="ISO code such as INR"),
    DocField("subtotal", "Taxable value", MONEY, "100000.00", prompt_note="the taxable value before tax"),
    DocField("cgst_amount", "CGST", MONEY, "9000.00"),
    DocField("sgst_amount", "SGST", MONEY, "9000.00"),
    DocField("igst_amount", "IGST", MONEY, "0.00"),
    DocField("cess_amount", "Cess", MONEY, "0.00"),
    DocField("tax_amount", "Total tax", MONEY, "18000.00", prompt_note="total tax"),
    DocField("total_amount", "Total amount", MONEY, "118000.00", prompt_note="the amount payable"),
    DocField("reverse_charge", "Reverse charge", BOOLEAN, "false", prompt_note="true or false, as the document states"),
    DocField("irn", "e-invoice IRN", STRING, "a 64-character reference", prompt_note="the e-invoice Invoice Reference Number"),
    DocField("note_type", "Note type", STRING, "credit", prompt_note='"credit" or "debit", for a credit or debit note only',
             options=(("credit", "Credit note"), ("debit", "Debit note"))),
    DocField("credit_note_number", "Credit or debit note number", STRING, "CN-14", prompt_note="the note's own number, for a credit or debit note only"),
    DocField("original_invoice_number", "Original invoice number", STRING, "INV-2200", prompt_note="the invoice a credit or debit note refers to"),
    DocField("original_invoice_date", "Original invoice date", DATE, "2026-08-01"),
    DocField("line_items", "Line items", ARRAY, "3 lines"),
)

#: Inside one entry of `line_items`.
LINE_FIELDS: Final[tuple[LineField, ...]] = (
    LineField("description", "Description", STRING),
    LineField("hsn_sac", "HSN or SAC code", STRING, "the HSN or SAC code"),
    LineField("quantity", "Quantity", NUMBER),
    LineField("unit", "Unit", STRING),
    LineField("unit_price", "Unit price", MONEY),
    LineField("taxable_value", "Taxable value", MONEY),
    LineField("tax_rate", "Tax rate", NUMBER, "percent"),
    LineField("amount", "Amount", MONEY),
    LineField("received_quantity", "Received quantity", NUMBER, "on a goods receipt, the quantity received"),
)

RESUME_FIELDS: Final[tuple[DocField, ...]] = (
    DocField("candidate_name", "Candidate name", STRING, "Jane Doe", GROUP_RESUME),
    DocField("email", "Email", STRING, "jane@example.com", GROUP_RESUME),
    DocField("phone_number", "Phone number", STRING, "+91 98765 43210", GROUP_RESUME),
    DocField("core_skills", "Core skills", ARRAY, "Python, SQL", GROUP_RESUME),
    DocField("degree_education", "Education", STRING, "B.Com", GROUP_RESUME),
    DocField("years_of_experience", "Years of experience", NUMBER, "6", GROUP_RESUME),
)

CONTRACT_FIELDS: Final[tuple[DocField, ...]] = (
    DocField("agreement_number", "Agreement number", STRING, "MSA-2026-04", GROUP_CONTRACT),
    DocField("agreement_date", "Agreement date", DATE, "2026-01-01", GROUP_CONTRACT),
    DocField("termination_date", "Termination date", DATE, "2027-01-01", GROUP_CONTRACT),
    DocField("party_names", "Parties", ARRAY, "Acme Ltd, Bharat Traders", GROUP_CONTRACT),
    DocField("governing_law", "Governing law", STRING, "India", GROUP_CONTRACT),
    DocField("value_amount", "Contract value", MONEY, "2500000.00", GROUP_CONTRACT),
)

#: The document classes the classifier names, as the "Classification" field's choices.
CLASSIFICATION_PATH: Final = "classification_details.document_classification"
CLASSIFICATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("Invoice", "Invoice"),
    ("Purchase Order", "Purchase order"),
    ("Receipt", "Receipt"),
    ("Resume", "Résumé"),
    ("Contract", "Contract"),
    ("Other", "Other"),
)

ALL_FIELDS: Final[tuple[DocField, ...]] = FIELDS + RESUME_FIELDS + CONTRACT_FIELDS
BY_KEY: Final[dict[str, DocField]] = {f.key: f for f in ALL_FIELDS}


def _line(key: str, note: str) -> str:
    return f"- {key}: {note}" if note else f"- {key}"


def prompt_block(group: str) -> str:
    """The prompt's bullet list for one document group, exactly as the prompt shows it."""
    if group == GROUP_COMMERCIAL:
        lines: list[str] = []
        for field in FIELDS:
            if field.key == "line_items":
                lines.append("- line_items: a list; each entry has")
                for sub in LINE_FIELDS:
                    lines.append("  " + _line(sub.key, sub.prompt_note))
            else:
                lines.append(_line(field.key, field.prompt_note))
        return "\n".join(lines)
    members = RESUME_FIELDS if group == GROUP_RESUME else CONTRACT_FIELDS
    return "\n".join(_line(field.key, field.prompt_note) for field in members)


def field_type(path: str) -> Optional[str]:
    """The declared type of a document field by its canonical key, or None for a field the schema does not name."""
    field = BY_KEY.get(path)
    return field.type if field is not None else None


__all__ = [
    "ALL_FIELDS",
    "ARRAY",
    "BOOLEAN",
    "BY_KEY",
    "CLASSIFICATIONS",
    "CLASSIFICATION_PATH",
    "CONTRACT_FIELDS",
    "DATE",
    "DocField",
    "FIELDS",
    "GROUP_COMMERCIAL",
    "GROUP_CONTRACT",
    "GROUP_RESUME",
    "LINE_FIELDS",
    "LineField",
    "MONEY",
    "NUMBER",
    "RESUME_FIELDS",
    "STRING",
    "field_type",
    "prompt_block",
]
