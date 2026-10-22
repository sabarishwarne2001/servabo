"""ARCH-37 — condition groups and trigger-payload fields. Session J — typed values and traces.

A flow-builder rule stores its conditions as groups:

    {"groups_operator": "AND",
     "groups": [{"logic_operator": "OR", "conditions": [...]}, ...]}

Each condition's `field` is either a document path (resolved exactly as before ARCH-37, by
`automation_service.resolve_field`, now also through the canonical alias map), `event.<key>`, which reads the trigger
event's payload, or one of three derived document fields (`document.age_days`, `document.has_irn`,
`document.days_until_due`) worked out when the rule runs.

A condition is `{field, operator, value}`, with an optional `currency` for an amount. `value` is a string, or a list for
IN, NOT_IN, BETWEEN and the array operators; a comma string is still read, as it always was.

An empty group list matches: a flow rule with no conditions runs on every occurrence of its trigger, which is what
"When an anomaly is detected, notify Finance admins" means.

`trace_*` return what each condition read, what it wanted and what it decided, in words (identifiers masked), for a
run's trace. The plain `evaluate_*` functions return only the verdict, as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.core import finance_schema as fs
from app.services.automation import document_fields as df
from app.services.automation import evaluator as ev
from app.services.automation.triggers import EVENT_FIELD_PREFIX, TRIGGER_BY_EVENT, VALUELESS_OPERATORS

MAX_GROUPS = 10
MAX_CONDITIONS_PER_GROUP = 20


def _attr(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _nested(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


@dataclass(frozen=True)
class Resolved:
    value: Any
    info: ev.FieldInfo
    #: The currency the record itself states for an amount (the document's `currency`, an event's `currency`).
    currency: Optional[str] = None


def _event_field(event_type: Optional[str], key: str) -> Any:
    spec = TRIGGER_BY_EVENT.get(event_type or "")
    if spec is None:
        return None
    return next((f for f in spec.fields if f.key == key), None)


def resolve_detailed(
    field_path: str,
    *,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> Resolved:
    ctx = context or ev.EvalContext()
    if field_path.startswith(EVENT_FIELD_PREFIX):
        key = field_path[len(EVENT_FIELD_PREFIX):]
        payload = event_payload or {}
        declared = _event_field(event_type, key)
        if declared is None:
            return Resolved(_nested(payload, key), ev.FieldInfo(field_path, ev.humanize(key)))
        stored_key = getattr(declared, "source_key", "") or key
        currency = payload.get(declared.currency_key) if getattr(declared, "currency_key", "") else None
        return Resolved(
            _nested(payload, stored_key),
            ev.FieldInfo(field_path, declared.label, declared.type, getattr(declared, "unit", None) or None),
            str(currency) if currency else None,
        )
    if df.is_derived(field_path):
        meta = next(d for d in df.DERIVED_FIELDS if d["key"] == field_path)
        return Resolved(df.derived_value(work_item, field_path, ctx), ev.FieldInfo(field_path, meta["label"], meta["type"]))
    if work_item is None:
        return Resolved(None, ev.FieldInfo(field_path, ev.humanize(field_path)))
    from app.services.automation_service import resolve_field

    value = resolve_field(work_item, field_path)
    canonical = df.canonical_key(field_path)
    declared_doc = fs.BY_KEY.get(canonical)
    info = ev.FieldInfo(field_path, declared_doc.label if declared_doc else ev.humanize(field_path), declared_doc.type if declared_doc else "string")
    currency = None
    if info.type == "money":
        from app.core import normalize

        raw = df.read_by_alias(df._entities(work_item), "currency")
        currency = normalize.currency_code(str(raw)) if raw else None
    return Resolved(value, info, currency)


def resolve(
    field_path: str,
    *,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> Any:
    return resolve_detailed(
        field_path, work_item=work_item, event_payload=event_payload, event_type=event_type, context=context
    ).value


def _value_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return not [v for v in value if str(v).strip()]
    return str(value).strip() == ""


def trace_condition(
    condition: Any,
    *,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> tuple[bool, dict[str, Any]]:
    """(matched, a trace entry saying what was read, what was wanted and the verdict)."""
    ctx = context or ev.EvalContext()
    field_path = _attr(condition, "field")
    operator = _attr(condition, "operator")
    value = _attr(condition, "value")
    currency = _attr(condition, "currency")
    entry: dict[str, Any] = {
        "field": field_path if isinstance(field_path, str) else "",
        "operator": str(operator or "").upper().strip(),
    }

    def fail(reason: str) -> tuple[bool, dict[str, Any]]:
        return False, {**entry, "label": ev.humanize(entry["field"]), "expected": "", "actual": "", "matched": False, "reason": reason}

    if not isinstance(field_path, str) or not field_path.strip():
        return fail("This condition has no field, so it did not match.")
    if not isinstance(operator, str) or not operator.strip():
        return fail("This condition has no comparison, so it did not match.")
    normalised = operator.upper().strip()
    if normalised not in VALUELESS_OPERATORS and _value_missing(value):
        return fail("This condition has no value to compare with, so it did not match.")
    resolved = resolve_detailed(
        field_path.strip(), work_item=work_item, event_payload=event_payload, event_type=event_type, context=ctx
    )
    outcome = ev.evaluate(
        resolved.value, normalised, value,
        field=resolved.info, ctx=ctx, currency=str(currency) if currency else None, actual_currency=resolved.currency,
    )
    return outcome.matched, {
        **entry,
        "operator": normalised,
        "label": resolved.info.name,
        "expected": outcome.expected_text,
        "actual": outcome.actual_text,
        "matched": outcome.matched,
        "reason": outcome.reason,
    }


def evaluate_condition(
    condition: Any,
    *,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> bool:
    return trace_condition(
        condition, work_item=work_item, event_payload=event_payload, event_type=event_type, context=context
    )[0]


def _combine(results: Sequence[bool], operator: str) -> bool:
    if not results:
        return True
    return any(results) if operator == "OR" else all(results)


def _operator(value: Any) -> str:
    text = str(value or "AND").upper().strip()
    return text if text in ("AND", "OR") else "AND"


def trace_groups(
    groups: Sequence[Any],
    *,
    groups_operator: Any,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> tuple[bool, list[dict[str, Any]]]:
    outcomes: list[bool] = []
    entries: list[dict[str, Any]] = []
    for g_index, group in enumerate(groups or ()):
        conditions = list(_attr(group, "conditions") or [])
        if not conditions:
            continue
        results: list[bool] = []
        for c_index, condition in enumerate(conditions):
            matched, entry = trace_condition(
                condition, work_item=work_item, event_payload=event_payload, event_type=event_type, context=context
            )
            results.append(matched)
            entries.append({"group": g_index, "index": c_index, **entry})
        outcomes.append(_combine(results, _operator(_attr(group, "logic_operator"))))
    return _combine(outcomes, _operator(groups_operator)), entries


def evaluate_groups(
    groups: Sequence[Any],
    *,
    groups_operator: Any,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> bool:
    return trace_groups(
        groups, groups_operator=groups_operator, work_item=work_item, event_payload=event_payload,
        event_type=event_type, context=context,
    )[0]


def trace_node_config(
    config: Mapping[str, Any],
    *,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """A condition node's config, grouped (ARCH-37) or flat (ARCH-13), with the reason for each condition."""
    if "groups" in config:
        return trace_groups(
            config.get("groups") or [],
            groups_operator=config.get("groups_operator"),
            work_item=work_item,
            event_payload=event_payload,
            event_type=event_type,
            context=context,
        )
    flat = list(config.get("conditions") or [])
    if not flat:
        return False, []
    entries: list[dict[str, Any]] = []
    results: list[bool] = []
    for index, condition in enumerate(flat):
        matched, entry = trace_condition(
            condition, work_item=work_item, event_payload=event_payload, event_type=event_type, context=context
        )
        results.append(matched)
        entries.append({"group": 0, "index": index, **entry})
    return _combine(results, _operator(config.get("logic_operator"))), entries


def evaluate_node_config(
    config: Mapping[str, Any],
    *,
    work_item: Any,
    event_payload: Optional[Mapping[str, Any]],
    event_type: Optional[str] = None,
    context: Optional[ev.EvalContext] = None,
) -> bool:
    return trace_node_config(
        config, work_item=work_item, event_payload=event_payload, event_type=event_type, context=context
    )[0]


def flatten(groups: Sequence[Any]) -> list[dict[str, Any]]:
    """Every condition in every group, for the legacy `conditions` column."""
    flat: list[dict[str, Any]] = []
    for group in groups or ():
        for condition in _attr(group, "conditions") or ():
            entry: dict[str, Any] = {
                "field": _attr(condition, "field"),
                "operator": _attr(condition, "operator"),
                "value": _attr(condition, "value") or "",
            }
            if _attr(condition, "currency"):
                entry["currency"] = _attr(condition, "currency")
            flat.append(entry)
    return flat


__all__ = [
    "MAX_CONDITIONS_PER_GROUP",
    "MAX_GROUPS",
    "Resolved",
    "evaluate_condition",
    "evaluate_groups",
    "evaluate_node_config",
    "flatten",
    "resolve",
    "resolve_detailed",
    "trace_condition",
    "trace_groups",
    "trace_node_config",
]
