"""Session J, Phase 1 — conditions that are always right, through the real pipeline and API.

* an amount a model wrote as "₹ 1,18,000.00" fires "total over 1,00,000 INR"; "TBD" does not, and the run's trace says why;
* an amount in another currency does not match a rule written in rupees and is never converted;
* a rule on `vendor_gstin` reads a model's `supplier_gstin`;
* a person's correction of a field is what the next condition reads;
* the save refuses a value outside a field's choices, in words, and stores IN and BETWEEN as lists;
* the catalog offers the finance schema, with money, dates and choices typed.
"""

from __future__ import annotations

from typing import Any

from tests.engines.conftest import Engines


def _rule(conditions: list[dict[str, Any]], name: str = "Big invoices", operator: str = "AND") -> dict[str, Any]:
    return {
        "name": name,
        "triggers": ["document.completed"],
        "condition_groups": [{"logic_operator": operator, "conditions": conditions}],
        "groups_operator": "AND",
        "actions": [{"action_type": "notify.role", "config": {"roles": ["ADMIN"], "title": "Hit: {{document.filename}}",
                                                              "message": "{{rule.name}} matched."}}],
    }


def _invoice(engines: Engines, number: str, entities: dict[str, Any]) -> str:
    return str(engines.process(f"{number}.pdf", [["ACME SUPPLIES LTD", "TAX INVOICE", f"Invoice Number: {number}"]],
                               marker=number, classification="Invoice",
                               entities={"vendor_name": "Acme Supplies Ltd", "invoice_number": number, **entities}))


def _executions(engines: Engines, rule_id: str) -> dict[str, dict[str, Any]]:
    page = engines.get("/automation/executions", params={"rule_id": rule_id}).json()
    return {str(e["work_item_id"]): e for e in page["items"]}


def _condition_trace(engines: Engines, execution_id: str) -> list[dict[str, Any]]:
    nodes = engines.get(f"/automation/executions/{execution_id}/nodes").json()
    return [c for n in nodes for c in n.get("conditions", [])]


def test_an_amount_in_any_written_form_is_compared_as_a_number(engines: Engines) -> None:
    rule = engines.post("/automation/rules", _rule([
        {"field": "total_amount", "operator": "GREATER_THAN", "value": "100000", "currency": "INR"}])).json()
    grouped = _invoice(engines, "INV-J1-A", {"total_amount": "₹ 1,18,000.00", "currency": "INR"})
    small = _invoice(engines, "INV-J1-B", {"total_amount": "₹ 9,500.00", "currency": "INR"})
    unreadable = _invoice(engines, "INV-J1-C", {"total_amount": "TBD", "currency": "INR"})
    dollars = _invoice(engines, "INV-J1-D", {"total_amount": "1,25,000.00", "currency": "USD"})

    runs = _executions(engines, rule["id"])
    assert runs[grouped]["actions_executed"] == 1, "the grouped, rupee-marked amount did not fire the rule"
    for quiet in (small, unreadable, dollars):
        assert runs[quiet]["actions_executed"] == 0

    why_not = _condition_trace(engines, runs[unreadable]["id"])
    assert why_not and why_not[0]["matched"] is False
    assert "Total amount 'TBD' is not a number" in why_not[0]["reason"]
    usd = _condition_trace(engines, runs[dollars]["id"])[0]
    assert "never converted" in usd["reason"] and "USD" in usd["reason"]
    fired = _condition_trace(engines, runs[grouped]["id"])[0]
    assert fired["matched"] is True and fired["actual"] == "INR 1,18,000.00" and fired["expected"] == "INR 1,00,000.00"


def test_a_rule_on_vendor_gstin_reads_the_name_a_model_used(engines: Engines) -> None:
    rule = engines.post("/automation/rules", _rule([
        {"field": "vendor_gstin", "operator": "STARTS_WITH", "value": "27"}], name="Maharashtra suppliers")).json()
    by_alias = _invoice(engines, "INV-J2-A", {"supplier_gstin": "27AAAAA0000A1Z5"})
    other = _invoice(engines, "INV-J2-B", {"vendor_gstin": "29BBBBB1111B1Z6"})
    runs = _executions(engines, rule["id"])
    assert runs[by_alias]["actions_executed"] == 1 and runs[other]["actions_executed"] == 0


def test_a_correction_is_what_the_next_condition_reads(engines: Engines) -> None:
    rule = engines.post("/automation/rules", _rule([
        {"field": "total_amount", "operator": "GREATER_THAN", "value": "100000", "currency": "INR"}])).json()
    work_item = _invoice(engines, "INV-J3-A", {"total_amount": "1,180.00", "currency": "INR"})

    before = engines.post(f"/automation/rules/{rule['id']}/test", {"work_item_id": work_item})
    assert before.status_code == 200 and before.json()["matched"] is False
    assert "(INR 1,180.00)" in before.json()["conditions"][0]["reason"]

    fixed = engines.patch(f"/work-items/{work_item}/fields", {"corrections": {"total_amount": "₹ 1,18,000.00"},
                                                               "reason": "The model dropped a digit"},
                          as_user=engines.tenant.contributor)
    assert fixed.status_code == 200, fixed.text

    after = engines.post(f"/automation/rules/{rule['id']}/test", {"work_item_id": work_item})
    assert after.json()["matched"] is True
    assert after.json()["conditions"][0]["actual"] == "INR 1,18,000.00"


def test_the_save_refuses_a_value_outside_the_fields_choices_in_words(engines: Engines) -> None:
    body = {
        "name": "Anomalies", "triggers": ["anomaly.detected"],
        "condition_groups": [{"logic_operator": "AND", "conditions": [
            {"field": "event.kind", "operator": "EQUALS", "value": "DUPLICATE"}]}],
        "actions": [{"action_type": "notify.role", "config": {"roles": ["ADMIN"]}}],
    }
    refused = engines.post("/automation/rules", body)
    assert refused.status_code == 422, refused.text
    messages = " ".join(str(i["msg"]) for i in refused.json()["detail"])
    assert "'DUPLICATE' is not among the choices for Finding kind" in messages and "Duplicate document" in messages

    body["condition_groups"][0]["conditions"][0]["value"] = "DUPLICATE_DOCUMENT"
    assert engines.post("/automation/rules", body).status_code == 201


def test_lists_are_stored_as_lists_and_old_comma_strings_still_save(engines: Engines) -> None:
    body = _rule([
        {"field": "vendor_name", "operator": "IN", "value": ["Acme, Inc", "Beta"]},
        {"field": "currency", "operator": "NOT_IN", "value": "USD,EUR"},
        {"field": "total_amount", "operator": "BETWEEN", "value": "100000..500000", "currency": "INR"},
    ], name="Lists")
    created = engines.post("/automation/rules", body)
    assert created.status_code == 201, created.text
    stored = created.json()["condition_groups"][0]["conditions"]
    assert stored[0]["value"] == ["Acme, Inc", "Beta"]
    assert stored[1]["value"] == ["USD", "EUR"]
    assert stored[2]["value"] == ["100000", "500000"] and stored[2]["currency"] == "INR"


def test_a_currency_belongs_only_on_an_amount_and_must_be_a_known_one(engines: Engines) -> None:
    wrong_field = engines.post("/automation/rules", _rule([
        {"field": "vendor_name", "operator": "EQUALS", "value": "Acme", "currency": "INR"}], name="W1"))
    assert wrong_field.status_code == 422 and "A currency applies only to an amount" in wrong_field.text
    unknown = engines.post("/automation/rules", _rule([
        {"field": "total_amount", "operator": "GREATER_THAN", "value": "5", "currency": "ZZZ"}], name="W2"))
    assert unknown.status_code == 422 and "not a currency this product knows" in unknown.text


def test_date_operators_need_a_date_and_a_whole_number_of_days(engines: Engines) -> None:
    bad_field = engines.post("/automation/rules", _rule([
        {"field": "vendor_name", "operator": "OLDER_THAN_DAYS", "value": "5"}], name="D1"))
    assert bad_field.status_code == 422 and "compares dates" in bad_field.text
    bad_days = engines.post("/automation/rules", _rule([
        {"field": "invoice_date", "operator": "OLDER_THAN_DAYS", "value": "five"}], name="D2"))
    assert bad_days.status_code == 422 and "whole number of days" in bad_days.text
    ok = engines.post("/automation/rules", _rule([
        {"field": "invoice_date", "operator": "OLDER_THAN_DAYS", "value": "150"}], name="D3"))
    assert ok.status_code == 201, ok.text
    derived = engines.post("/automation/rules", _rule([
        {"field": "document.age_days", "operator": "GREATER_THAN", "value": "150"}], name="D4"))
    assert derived.status_code == 201, derived.text


def test_the_catalog_offers_the_finance_schema_typed(engines: Engines) -> None:
    catalog = engines.get("/automation/catalog").json()
    fields = {f["key"]: f for f in catalog["document_fields"]}
    for key in ("vendor_gstin", "buyer_gstin", "cgst_amount", "due_date", "irn", "invoice_date"):
        assert key in fields, key
    assert fields["total_amount"]["type"] == "money" and fields["invoice_date"]["type"] == "date"
    assert fields["document.age_days"]["source"] == "derived"
    assert {o["value"] for o in fields["note_type"]["options"]} == {"credit", "debit"}
    assert "OLDER_THAN_DAYS" in catalog["operators"]["date"] and "WITHIN_NEXT_DAYS" in catalog["operators"]["date"]
    assert "BETWEEN" in catalog["operators"]["money"] and "IN" not in catalog["operators"]["money"]
    assert set(catalog["workspace"]) == {"currency", "date_format", "timezone"}
    triggers = {t["key"]: t for t in catalog["triggers"]}
    posting = {f["key"]: f for f in triggers["posting.failed"]["fields"]}
    assert posting["event.amount_value"]["type"] == "money" and posting["event.state"]["options"]
    variance = {f["key"]: f for f in triggers["procurement.completed"]["fields"]}
    assert variance["event.variance"]["unit"] == "micros" and variance["event.variance_micros"]["legacy"] is True
