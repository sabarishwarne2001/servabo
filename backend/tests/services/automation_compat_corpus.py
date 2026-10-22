"""Session J — the corpus of rule shapes the automation evaluator accepted BEFORE Session J.

`golden/automation_compat.json` holds what the pre-Session-J evaluator answered for every case here (generated
once, from the unchanged code, by `python -m tests.services.automation_compat_corpus --write`). The compatibility
test replays the corpus through today's evaluator and requires the same answers: a rule saved before Session J keeps
working exactly as before. Only inputs the old evaluator read correctly are here; inputs it silently got wrong
("1,18,000.00" as a number, a comma inside a value) are in the operator tables of test_automation_evaluator.py.
"""

from __future__ import annotations

import itertools
import json
import pathlib
import sys
from types import SimpleNamespace
from typing import Any, Callable

GOLDEN = pathlib.Path(__file__).parent / "golden" / "automation_compat.json"

STRING_ACTUALS: list[Any] = ["Acme Supplies", " acme supplies ", "Invoice", "", None, "100", "INR"]
STRING_TARGETS = ["acme supplies", "Acme", "supplies", "Invoice", "xyz", "INR", "100"]
STRING_OPS = ["EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS", "STARTS_WITH", "ENDS_WITH", "EXISTS", "IS_EMPTY", "IS_NOT_EMPTY"]

NUMBER_ACTUALS: list[Any] = [100, 100.5, "100", "100.50", 0, -5, "abc", None, "1e3"]
NUMBER_TARGETS = ["100", "100.5", "99", "101", "0", "-5", "1000"]
NUMBER_OPS = ["EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL"]

LIST_ACTUALS: list[Any] = ["a", "B", ["a", "c"], ["x"], [], None, "d"]
LIST_TARGETS = ["a,b,c", "a, b", "c", " B ,d", "z"]
LIST_OPS = ["IN", "NOT_IN", "CONTAINS", "NOT_CONTAINS", "ARRAY_CONTAINS_ANY", "ARRAY_CONTAINS_ALL"]

BETWEEN_ACTUALS: list[Any] = [15, "15", 10, 20, 5, 25, "x", None, -3]
BETWEEN_TARGETS = ["10,20", "10..20", "10 - 20", "10-20", "-5,5", "20,10", "10"]


def operator_cases() -> dict[str, tuple[Any, str, str]]:
    cases: dict[str, tuple[Any, str, str]] = {}
    for (i, a), (j, t), op in itertools.product(enumerate(STRING_ACTUALS), enumerate(STRING_TARGETS), STRING_OPS):
        cases[f"str:{op}:{i}:{j}"] = (a, op, t)
    for (i, a), (j, t), op in itertools.product(enumerate(NUMBER_ACTUALS), enumerate(NUMBER_TARGETS), NUMBER_OPS):
        cases[f"num:{op}:{i}:{j}"] = (a, op, t)
    for (i, a), (j, t), op in itertools.product(enumerate(LIST_ACTUALS), enumerate(LIST_TARGETS), LIST_OPS):
        cases[f"list:{op}:{i}:{j}"] = (a, op, t)
    for (i, a), (j, t) in itertools.product(enumerate(BETWEEN_ACTUALS), enumerate(BETWEEN_TARGETS)):
        cases[f"between:{i}:{j}"] = (a, "BETWEEN", t)
    return cases


def work_item(**entities: Any) -> Any:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        workspace_id="00000000-0000-0000-0000-0000000000aa",
        original_filename="invoice-2231.pdf",
        status="COMPLETED",
        page_count=3,
        extracted_entities=entities,
    )


def rule_shapes() -> dict[str, tuple[dict[str, Any], Any, dict[str, Any] | None]]:
    """case id -> (a node config as `graph_service` stores it, a work item, an event payload)."""
    doc = work_item(vendor_name="Acme Supplies", total_amount=118000, currency="INR",
                    classification_details={"document_classification": "Invoice"}, tags=["a", "b"])
    payload = {"variance_micros": 12_500_000, "kind": "DUPLICATE", "exception_count": 3}
    one = lambda f, o, v: {"field": f, "operator": o, "value": v}  # noqa: E731
    shapes: dict[str, tuple[dict[str, Any], Any, dict[str, Any] | None]] = {}
    shapes["flat-and-match"] = ({"conditions": [one("total_amount", "GREATER_THAN", "100000"), one("vendor_name", "CONTAINS", "acme")], "logic_operator": "AND"}, doc, None)
    shapes["flat-and-miss"] = ({"conditions": [one("total_amount", "GREATER_THAN", "100000"), one("vendor_name", "EQUALS", "Other")], "logic_operator": "AND"}, doc, None)
    shapes["flat-or-match"] = ({"conditions": [one("total_amount", "LESS_THAN", "1"), one("currency", "EQUALS", "inr")], "logic_operator": "OR"}, doc, None)
    shapes["flat-or-miss"] = ({"conditions": [one("total_amount", "LESS_THAN", "1"), one("currency", "EQUALS", "usd")], "logic_operator": "OR"}, doc, None)
    shapes["flat-empty-is-false"] = ({"conditions": [], "logic_operator": "AND"}, doc, None)
    shapes["flat-nested-path"] = ({"conditions": [one("classification_details.document_classification", "EQUALS", "invoice")]}, doc, None)
    shapes["flat-extracted-prefix"] = ({"conditions": [one("extracted_entities.vendor_name", "STARTS_WITH", "acme")]}, doc, None)
    shapes["flat-attribute-field"] = ({"conditions": [one("original_filename", "ENDS_WITH", ".pdf")]}, doc, None)
    shapes["flat-page-count"] = ({"conditions": [one("page_count", "GREATER_THAN_OR_EQUAL", "3")]}, doc, None)
    shapes["flat-missing-value-is-false"] = ({"conditions": [{"field": "vendor_name", "operator": "EQUALS", "value": ""}]}, doc, None)
    shapes["flat-valueless-exists"] = ({"conditions": [one("total_amount", "EXISTS", "")]}, doc, None)
    shapes["flat-valueless-empty"] = ({"conditions": [one("po_number", "IS_EMPTY", "")]}, doc, None)
    shapes["flat-in-comma"] = ({"conditions": [one("currency", "IN", "usd, inr ,eur")]}, doc, None)
    shapes["flat-not-in-comma"] = ({"conditions": [one("currency", "NOT_IN", "usd,eur")]}, doc, None)
    shapes["flat-between"] = ({"conditions": [one("total_amount", "BETWEEN", "100000,200000")]}, doc, None)
    shapes["flat-array-any"] = ({"conditions": [one("tags", "ARRAY_CONTAINS_ANY", "b,z")]}, doc, None)
    shapes["flat-array-all"] = ({"conditions": [one("tags", "ARRAY_CONTAINS_ALL", "a,b")]}, doc, None)
    shapes["flat-no-document-event-field"] = ({"conditions": [one("event.kind", "EQUALS", "duplicate")]}, None, payload)
    shapes["flat-no-document-doc-field"] = ({"conditions": [one("vendor_name", "EQUALS", "Acme Supplies")]}, None, payload)
    shapes["event-number-micros"] = ({"conditions": [one("event.variance_micros", "GREATER_THAN", "10000000")]}, doc, payload)
    shapes["event-number-micros-miss"] = ({"conditions": [one("event.variance_micros", "GREATER_THAN", "20000000")]}, doc, payload)
    shapes["event-count"] = ({"conditions": [one("event.exception_count", "GREATER_THAN", "2")]}, doc, payload)
    shapes["event-unknown-key"] = ({"conditions": [one("event.nope", "EXISTS", "")]}, doc, payload)
    shapes["groups-and-of-ors"] = ({"groups_operator": "AND", "groups": [
        {"logic_operator": "OR", "conditions": [one("total_amount", "GREATER_THAN", "1e9"), one("currency", "EQUALS", "INR")]},
        {"logic_operator": "AND", "conditions": [one("vendor_name", "CONTAINS", "acme"), one("event.kind", "EQUALS", "DUPLICATE")]},
    ]}, doc, payload)
    shapes["groups-or-of-ands"] = ({"groups_operator": "OR", "groups": [
        {"logic_operator": "AND", "conditions": [one("total_amount", "LESS_THAN", "5"), one("currency", "EQUALS", "INR")]},
        {"logic_operator": "AND", "conditions": [one("event.exception_count", "EQUALS", "3")]},
    ]}, doc, payload)
    shapes["groups-empty-matches"] = ({"groups": []}, doc, payload)
    shapes["groups-empty-group-skipped"] = ({"groups": [{"logic_operator": "AND", "conditions": []}]}, doc, payload)
    shapes["groups-bad-operator-defaults-and"] = ({"groups_operator": "XOR", "groups": [
        {"logic_operator": "NOPE", "conditions": [one("currency", "EQUALS", "INR"), one("total_amount", "GREATER_THAN", "1")]}]}, doc, payload)
    shapes["blank-field-false"] = ({"conditions": [one("", "EQUALS", "x")]}, doc, None)
    shapes["blank-operator-false"] = ({"conditions": [one("currency", "", "x")]}, doc, None)
    return shapes


def evaluate_everything(evaluate_condition: Callable[[Any, str, str], bool], evaluate_node: Callable[..., bool]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for case_id, (actual, op, target) in operator_cases().items():
        out[case_id] = bool(evaluate_condition(actual, op, target))
    for case_id, (config, doc, payload) in rule_shapes().items():
        out[f"rule:{case_id}"] = bool(evaluate_node(config, work_item=doc, event_payload=payload))
    return out


def main() -> None:
    from app.services.automation import conditions
    from app.services.automation_service import _evaluate_condition

    results = evaluate_everything(_evaluate_condition, conditions.evaluate_node_config)
    if "--write" in sys.argv:
        GOLDEN.write_text(json.dumps(results, indent=0, sort_keys=True) + "\n")
        print(f"wrote {len(results)} cases")
    else:
        print(json.dumps(results)[:200])


if __name__ == "__main__":
    main()
