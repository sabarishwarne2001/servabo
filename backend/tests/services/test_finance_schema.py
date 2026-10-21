"""Session J — the extraction prompt and the builder's field list are one table, and a test notices if they part.

`app/core/finance_schema.py` is the only list of the fields Servabo reads off a document. The prompt's bullet lists are
rendered from it, and so is the automation builder's field picker (which used to carry `STANDARD_FIELDS`, the old six-field
prompt). A person who edits the prompt text by hand, or adds a field in one place only, fails here.
"""

from __future__ import annotations

import re

import pytest

from app.core import finance_schema as fs
from app.services.automation import catalog_service, document_fields
from app.services.llm_service import ENTITY_EXTRACTION_PROMPT_TEMPLATE as PROMPT

pytestmark = pytest.mark.no_db

SECTION = re.compile(r"\n(Invoice / Receipt / Purchase Order|Resume|Contract|Other)\n")


def _prompt_sections() -> dict[str, str]:
    parts = SECTION.split(PROMPT)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _keys(block: str) -> list[str]:
    return re.findall(r"^- ([a-z_]+)", block, flags=re.MULTILINE)


def test_the_prompts_commercial_fields_are_exactly_the_schemas() -> None:
    block = _prompt_sections()["Invoice / Receipt / Purchase Order"]
    asked = _keys(block)
    assert asked == [f.key for f in fs.FIELDS], "the prompt and finance_schema list different invoice fields"
    sub = re.findall(r"^  - ([a-z_]+)", block, flags=re.MULTILINE)
    assert sub == [f.key for f in fs.LINE_FIELDS]


def test_the_prompts_resume_and_contract_fields_are_exactly_the_schemas() -> None:
    sections = _prompt_sections()
    assert _keys(sections["Resume"]) == [f.key for f in fs.RESUME_FIELDS]
    assert _keys(sections["Contract"]) == [f.key for f in fs.CONTRACT_FIELDS]


def test_the_prompt_text_still_carries_each_fields_instruction() -> None:
    for field in fs.FIELDS:
        if field.prompt_note:
            assert f"- {field.key}: {field.prompt_note}" in PROMPT
    assert "- line_items: a list; each entry has" in PROMPT


def test_a_field_the_schema_lacks_would_be_caught() -> None:
    block = _prompt_sections()["Invoice / Receipt / Purchase Order"]
    drifted = block.replace("- irn:", "- e_invoice_irn:")
    assert _keys(drifted) != [f.key for f in fs.FIELDS]


def test_the_builder_offers_the_finance_schema_not_the_old_six_fields() -> None:
    offered = {f["key"]: f for f in document_fields.catalog_fields()}
    for key in ("vendor_gstin", "buyer_gstin", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount", "due_date",
                "irn", "invoice_date", "total_amount", "place_of_supply", "payment_terms", "original_invoice_number"):
        assert key in offered, f"{key} is read by the prompt but the builder does not offer it"
    assert "date" not in offered, "the old prompt's `date` is now invoice_date (a rule on `date` still reads it)"
    assert offered["total_amount"]["type"] == "money" and offered["invoice_date"]["type"] == "date"
    assert offered["reverse_charge"]["type"] == "boolean"
    for key in ("document.age_days", "document.has_irn", "document.days_until_due", "document.tags"):
        assert offered[key]["source"] == "derived"
    assert not hasattr(catalog_service, "STANDARD_FIELDS")


def test_every_schema_field_the_prompt_asks_for_has_a_label_type_and_example() -> None:
    for field in fs.ALL_FIELDS:
        assert field.label and field.example and field.type in {
            fs.STRING, fs.NUMBER, fs.MONEY, fs.DATE, fs.BOOLEAN, fs.ARRAY}, field.key


def test_amounts_are_money_and_dates_are_dates() -> None:
    for key in ("subtotal", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount", "tax_amount", "total_amount", "value_amount"):
        assert fs.field_type(key) == fs.MONEY, key
    for key in ("invoice_date", "po_date", "receipt_date", "delivery_date", "due_date", "original_invoice_date", "agreement_date"):
        assert fs.field_type(key) == fs.DATE, key
