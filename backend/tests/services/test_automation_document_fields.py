"""Session J — a rule reads a document by the canonical name, whatever a model called the field (F-538)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.automation import conditions, document_fields as df
from app.services.automation import evaluator as ev

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
CTX = ev.EvalContext(date_format="DD/MM/YYYY", timezone="Asia/Kolkata", currency="INR", now=NOW)


def doc(**entities: object) -> SimpleNamespace:
    return SimpleNamespace(
        id="d1", workspace_id="w1", original_filename="a.pdf", status="COMPLETED", page_count=1,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc), extracted_entities=entities,
    )


def read(work_item: SimpleNamespace, path: str) -> object:
    return conditions.resolve(path, work_item=work_item, event_payload=None, context=CTX)


@pytest.mark.parametrize(
    "stored,asked",
    [
        ("supplier_gstin", "vendor_gstin"), ("gstin", "vendor_gstin"), ("gst_number", "vendor_gstin"),
        ("Vendor GSTIN", "vendor_gstin"), ("sellerGstin", "vendor_gstin"),
        ("vendor_gstin", "supplier_gstin"), ("vendor_gstin", "gstin"),
        ("supplier", "vendor_name"), ("seller_name", "vendor_name"), ("vendor_name", "supplier_name"),
        ("grand_total", "total_amount"), ("invoice_total", "total_amount"), ("amount_due", "total_amount"),
        ("total_amount", "grand_total"),
        ("central_tax", "cgst_amount"), ("cgst", "cgst_amount"), ("state_gst", "sgst_amount"),
        ("integrated_gst", "igst_amount"), ("taxable_value", "subtotal"), ("total_tax", "tax_amount"),
        ("bill_date", "invoice_date"), ("date", "invoice_date"), ("invoice_date", "date"), ("document_date", "invoice_date"),
        ("payment_due_date", "due_date"), ("pay_by", "due_date"), ("terms_of_payment", "payment_terms"),
        ("e_invoice_irn", "irn"), ("invoice_reference_number", "irn"),
        ("invoice_no", "invoice_number"), ("inv_no", "invoice_number"),
        ("buyer", "customer_name"), ("bill_to", "customer_name"),
        ("against_invoice", "original_invoice_number"), ("pos", "place_of_supply"),
    ],
)
def test_a_field_is_read_under_any_name_a_model_used(stored: str, asked: str) -> None:
    assert read(doc(**{stored: "VALUE-1"}), asked) == "VALUE-1"


def test_the_exact_name_still_wins_over_an_alias() -> None:
    work_item = doc(vendor_gstin="EXACT", supplier_gstin="ALIAS")
    assert read(work_item, "vendor_gstin") == "EXACT"


def test_an_empty_value_does_not_hide_an_alias() -> None:
    assert read(doc(vendor_gstin="", gstin="27AAAAA0000A1Z5"), "vendor_gstin") == "27AAAAA0000A1Z5"


def test_a_name_the_schema_does_not_know_reads_only_itself() -> None:
    work_item = doc(custom_flag="yes", supplier_gstin="G")
    assert read(work_item, "custom_flag") == "yes"
    assert read(work_item, "something_else") is None


def test_a_condition_on_vendor_gstin_now_matches_a_models_supplier_gstin() -> None:
    work_item = doc(supplier_gstin="27AAAAA0000A1Z5")
    condition = {"field": "vendor_gstin", "operator": "STARTS_WITH", "value": "27"}
    assert conditions.evaluate_condition(condition, work_item=work_item, event_payload=None, context=CTX) is True


def test_every_alias_belongs_to_one_field_and_is_never_a_field_itself() -> None:
    seen: dict[str, str] = {}
    from app.core import finance_schema as fs

    for key, names in df.alias_map().items():
        for name in names:
            assert name not in fs.BY_KEY, f"{name} is an alias of {key} but also a field of its own"
            assert name not in seen, f"{name} is claimed by both {seen.get(name)} and {key}"
            seen[name] = key


def test_the_alias_map_includes_what_the_gst_engine_and_helm_already_know() -> None:
    from app.services.gst import fields as gf
    from app.services.helm import ledger as hl

    aliases = df.alias_map()
    assert set(gf.SELLER_GSTIN_KEYS) - {"vendor_gstin"} <= set(aliases["vendor_gstin"])
    assert set(gf.CGST_KEYS) - {"cgst_amount"} <= set(aliases["cgst_amount"])
    assert set(hl.DUE_DATE_KEYS) - {"due_date"} <= set(aliases["due_date"])


# ---- derived fields: worked out when the rule runs, never stored ---------------------------------------------------


def test_age_days_counts_from_the_documents_own_date_in_the_workspace_zone() -> None:
    work_item = doc(invoice_date="2026-05-01")
    assert read(work_item, df.AGE_DAYS) == 173  # 1 May to 21 October (it is 17:30 on the 21st in Kolkata)
    assert read(doc(date="01/05/2026"), df.AGE_DAYS) == 173, "an old-style `date`, read with the workspace's DD/MM"


def test_age_days_falls_back_to_the_upload_date() -> None:
    assert read(doc(), df.AGE_DAYS) == 50  # uploaded 2026-09-01


def test_has_irn_is_true_only_when_an_irn_was_read() -> None:
    assert read(doc(irn="a" * 64), df.HAS_IRN) is True
    assert read(doc(e_invoice_irn="a" * 64), df.HAS_IRN) is True
    assert read(doc(irn="  "), df.HAS_IRN) is False
    assert read(doc(), df.HAS_IRN) is False


def test_days_until_due_is_negative_when_overdue_and_unknown_without_a_date() -> None:
    assert read(doc(due_date="2026-11-02"), df.DAYS_UNTIL_DUE) == 12
    assert read(doc(due_date="2026-10-01"), df.DAYS_UNTIL_DUE) == -20
    assert read(doc(), df.DAYS_UNTIL_DUE) is None


def test_derived_fields_work_in_a_condition_and_are_never_stored() -> None:
    work_item = doc(invoice_date="2026-05-01")
    cond = {"field": df.AGE_DAYS, "operator": "GREATER_THAN", "value": "150"}
    assert conditions.evaluate_condition(cond, work_item=work_item, event_payload=None, context=CTX) is True
    assert "age_days" not in work_item.extracted_entities
    assert not df.is_derived("total_amount") and df.is_derived(df.HAS_IRN)


def test_the_150_day_gst_recipe_condition() -> None:
    cond = {"field": "invoice_date", "operator": "OLDER_THAN_DAYS", "value": "150"}
    assert conditions.evaluate_condition(cond, work_item=doc(invoice_date="2026-05-01"), event_payload=None, context=CTX)
    assert not conditions.evaluate_condition(cond, work_item=doc(invoice_date="2026-08-01"), event_payload=None, context=CTX)


def test_money_condition_reads_the_documents_currency_and_never_converts() -> None:
    cond = {"field": "total_amount", "operator": "GREATER_THAN", "value": "1000000", "currency": "INR"}
    inr = doc(total_amount="₹ 12,50,000.00", currency="INR")
    usd = doc(total_amount="1250000", currency="USD")
    assert conditions.evaluate_condition(cond, work_item=inr, event_payload=None, context=CTX) is True
    assert conditions.evaluate_condition(cond, work_item=usd, event_payload=None, context=CTX) is False
    matched, trace = conditions.trace_condition(cond, work_item=usd, event_payload=None, context=CTX)
    assert matched is False and "never converted" in trace["reason"]


def test_event_money_in_micros_is_read_in_currency_units() -> None:
    cond = {"field": "event.variance", "operator": "GREATER_THAN", "value": "10"}
    payload = {"variance_micros": 12_500_000}
    work_item = doc()
    assert conditions.evaluate_condition(cond, work_item=work_item, event_payload=payload,
                                         event_type="trigger.procurement.completed", context=CTX) is True
    old = {"field": "event.variance_micros", "operator": "GREATER_THAN", "value": "10000000"}
    assert conditions.evaluate_condition(old, work_item=work_item, event_payload=payload,
                                         event_type="trigger.procurement.completed", context=CTX) is True
    other = {"field": "event.variance", "operator": "GREATER_THAN", "value": "13"}
    assert conditions.evaluate_condition(other, work_item=work_item, event_payload=payload,
                                         event_type="trigger.procurement.completed", context=CTX) is False


def test_a_posting_amount_is_money_in_the_postings_own_currency() -> None:
    cond = {"field": "event.amount_value", "operator": "GREATER_THAN", "value": "100000", "currency": "INR"}
    payload = {"amount": "118000.00", "currency": "INR"}
    assert conditions.evaluate_condition(cond, work_item=None, event_payload=payload,
                                         event_type="trigger.posting.failed", context=CTX) is True
    assert conditions.evaluate_condition(cond, work_item=None, event_payload={**payload, "currency": "USD"},
                                         event_type="trigger.posting.failed", context=CTX) is False


def test_the_trace_names_every_condition() -> None:
    config = {"groups": [{"logic_operator": "AND", "conditions": [
        {"field": "total_amount", "operator": "GREATER_THAN", "value": "1000000", "currency": "INR"},
        {"field": "vendor_bank_account", "operator": "EQUALS", "value": "x"},
    ]}]}
    work_item = doc(total_amount="118000", currency="INR", vendor_bank_account="00112233445566")
    matched, entries = conditions.trace_node_config(config, work_item=work_item, event_payload=None, context=CTX)
    assert matched is False and len(entries) == 2
    assert entries[0]["matched"] is False and "INR 1,18,000.00" in entries[0]["actual"]
    assert "00112233445566" not in str(entries) and entries[1]["actual"].endswith("5566")
