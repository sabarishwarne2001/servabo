"""Session J — rules saved before Session J keep working exactly as before.

The corpus (`automation_compat_corpus.py`) covers every operator on plain inputs and every rule shape the code accepts:
flat ARCH-13 conditions, grouped flow conditions, comma lists, event fields in micros, rules with no document, empty
groups. `golden/automation_compat.json` is what the evaluator answered before Session J. The legacy action aliases and
the `graph_version` DAG shape are replayed below.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.services.automation import conditions, flow_service, graph_service
from app.services.automation_service import _evaluate_condition
from tests.services import automation_compat_corpus as corpus

pytestmark = pytest.mark.no_db


def test_every_stored_shape_evaluates_as_it_did_before() -> None:
    golden = json.loads(corpus.GOLDEN.read_text())
    now = corpus.evaluate_everything(_evaluate_condition, conditions.evaluate_node_config)
    assert set(now) == set(golden), "the corpus and its golden answers must list the same cases"
    changed = sorted(case for case in golden if now[case] != golden[case])
    assert not changed, f"{len(changed)} stored shapes now answer differently, for example {changed[:8]}"


def _rule(**values: object) -> SimpleNamespace:
    base = dict(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="r", event="WORK_ITEM_COMPLETED", conditions=[],
                logic_operator="AND", actions=[], flow_spec=None, graph_version=0, on_error="HALT", priority=100)
    base.update(values)
    return SimpleNamespace(**base)


def test_a_graph_version_rule_flattens_to_the_same_conditions_and_answer() -> None:
    stored = [{"field": "total_amount", "operator": "GREATER_THAN", "value": "100000"},
              {"field": "currency", "operator": "EQUALS", "value": "inr"}]
    doc = corpus.work_item(total_amount=118000, currency="INR")
    legacy = _rule(conditions=stored, actions=[{"action_type": "email", "config": {"recipient": "a@b.co"}}])
    graph = graph_service.flatten_legacy_rule(legacy)  # type: ignore[arg-type]
    node = next(n for n in graph.nodes if n.node_type == "condition")
    assert node.config["conditions"] == stored
    assert conditions.evaluate_node_config(node.config, work_item=doc, event_payload=None) is True
    flow = _rule(flow_spec={"version": 1, "condition_groups": [{"logic_operator": "AND", "conditions": stored}],
                            "groups_operator": "AND", "else_actions": []},
                 actions=[{"action_type": "email.send", "config": {}}])
    flow_graph = graph_service.flatten_legacy_rule(flow)  # type: ignore[arg-type]
    flow_node = next(n for n in flow_graph.nodes if n.node_type == "condition")
    assert conditions.evaluate_node_config(flow_node.config, work_item=doc, event_payload=None) is True


def test_legacy_action_aliases_still_resolve() -> None:
    from app.services.automation import actions as registry

    assert registry.canonical("email") == "email.send"
    assert registry.canonical("send_email") == "email.send"
    assert registry.canonical("webhook") == "webhook.send"
    assert registry.get("email") is registry.get("email.send")


def test_a_condition_row_without_a_value_or_with_a_comma_string_is_still_read() -> None:
    doc = corpus.work_item(currency="INR")
    # the stored shape of a valueless operator, and of a comma list typed before lists were stored as lists
    assert conditions.evaluate_condition({"field": "currency", "operator": "EXISTS"}, work_item=doc, event_payload=None)
    assert conditions.evaluate_condition({"field": "currency", "operator": "IN", "value": "usd, inr"}, work_item=doc, event_payload=None)
    assert flow_service.ALL_OPERATORS >= {"IN", "NOT_IN", "BETWEEN", "EXISTS"}
