"""ARCH-37 — save-time validation, storage shape and dry runs for flow rules.

Every refusal is returned as a FastAPI-style issue list
(`[{"loc": ["body", "actions", 2, "config", "endpoint_id"], "msg": ...}]`),
which the console already parses (`services/api/errors.ts`) and maps to the
card that caused it.

WHAT IS CHECKED, AND WHY HERE
=============================

  triggers         known catalog keys the tenant's plan includes
  conditions       event fields every selected trigger carries; operators
                   valid for the field's type; values where required
  actions          registered; allowed for the triggers; config valid against
                   the action's schema; capability or add-on held; author's
                   organization role sufficient; referenced endpoint or
                   destination in this organization and active; template
                   variables from the allowlist
  otherwise        only with at least one condition

The run path re-checks capability, add-on and resource state, because each can
change after a rule is saved.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from pydantic import ValidationError

from app.services.automation import actions as action_registry
from app.services.automation import triggers as catalog
from app.services.automation.actions.base import (
    ROLE_ORGANIZATION_ADMIN,
    SaveContext,
    invalid_variables,
)

MAX_ACTIONS = 10
DOCUMENT_ACTIONS = frozenset(
    {"redaction.start", "review.escalate", "autonomy.decide", "work_item.mutate",
     # Session J: these act on the document the run is about.
     "document.tag", "review.assign", "legal_hold.place"}
)
ALL_OPERATORS = frozenset(op for ops in catalog.OPERATORS_BY_TYPE.values() for op in ops)


class FlowValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        super().__init__("; ".join(f"{'.'.join(map(str, i['loc']))}: {i['msg']}" for i in issues))
        self.issues = issues


@dataclass(frozen=True)
class Authoring:
    """Who is saving, and what their tenant holds."""

    db: Any
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    organization_role: str
    granted_capabilities: frozenset[str]
    addons: frozenset[str]


@dataclass
class NormalisedRule:
    event: str
    trigger_keys: list[str]
    event_types: list[str]
    conditions: list[dict[str, Any]]
    logic_operator: str
    actions: list[dict[str, Any]]
    flow_spec: Optional[dict[str, Any]]
    on_error: str
    issues: list[dict[str, Any]] = field(default_factory=list)


def _issue(loc: Sequence[Any], msg: str, kind: str = "value_error") -> dict[str, Any]:
    return {"loc": ["body", *loc], "msg": msg, "type": kind}


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else model


def action_available(definition: Any, *, capabilities: frozenset[str], addons: frozenset[str]) -> bool:
    """Whether a tenant may use an action: its capability AND its add-on, or (for `either`) one of them."""
    has_cap = definition.capability is None or definition.capability in capabilities
    has_addon = definition.addon is None or definition.addon in addons
    if getattr(definition, "either", False):
        return (definition.capability in capabilities) or (definition.addon in addons)
    return has_cap and has_addon


def _role_ok(minimum: str, organization_role: str) -> bool:
    if minimum == ROLE_ORGANIZATION_ADMIN:
        return organization_role in ("OWNER", "ADMIN")
    return True


def _value_items(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _option_issue(label: str, values: list[str], options: Sequence[Any]) -> Optional[str]:
    allowed = {str(o["value"]).lower(): str(o["label"]) for o in options}
    bad = [v for v in values if v.lower() not in allowed]
    if not bad:
        return None
    shown = ", ".join(f"{l}" for l in allowed.values())
    return f"{', '.join(repr(b) for b in bad)} {'is' if len(bad) == 1 else 'are'} not among the choices for {label}: {shown}."


def _validate_conditions(
    groups: list[dict[str, Any]], trigger_keys: list[str], issues: list[dict[str, Any]], *, check_options: bool = True
) -> None:
    from app.core import finance_schema as fs
    from app.services.automation import document_fields as df
    from app.services.automation import evaluator

    event_fields = {f.path: f for f in catalog.fields_for(trigger_keys)}
    specs, _ = catalog.resolve_trigger_keys(trigger_keys)
    documents = all(spec.has_document for spec in specs)
    derived = {d["key"]: d for d in df.DERIVED_FIELDS}
    for g_index, group in enumerate(groups):
        for c_index, condition in enumerate(group.get("conditions") or []):
            loc = ("condition_groups", g_index, "conditions", c_index)
            path = str(condition.get("field") or "")
            operator = str(condition.get("operator") or "").upper()
            raw_value = condition.get("value")
            items = _value_items(raw_value)
            currency = condition.get("currency")
            field_type: Optional[str] = None
            options: Sequence[Any] = ()
            label = path
            if path.startswith(catalog.EVENT_FIELD_PREFIX):
                spec_field = event_fields.get(path)
                if spec_field is None:
                    issues.append(_issue((*loc, "field"), f"{path!r} is not carried by every selected trigger."))
                    continue
                allowed = catalog.OPERATORS_BY_TYPE[spec_field.type]
                if operator not in allowed:
                    issues.append(_issue((*loc, "operator"), f"{operator} does not apply to a {spec_field.type} field."))
                field_type, label = spec_field.type, spec_field.label
                options = [{"value": v, "label": l} for v, l in spec_field.options]
            else:
                if not documents:
                    issues.append(_issue((*loc, "field"), "The selected trigger has no document to read."))
                if operator not in ALL_OPERATORS:
                    issues.append(_issue((*loc, "operator"), f"Unknown operator {operator!r}."))
                if path in derived:
                    field_type, label = derived[path]["type"], derived[path]["label"]
                else:
                    known = fs.BY_KEY.get(df.canonical_key(path))
                    if known is not None:
                        field_type, label, options = known.type, known.label, [{"value": v, "label": l} for v, l in known.options]
                    elif path == fs.CLASSIFICATION_PATH:
                        field_type, label = "string", "Document type"
                        options = [{"value": v, "label": l} for v, l in fs.CLASSIFICATIONS]
                if operator in catalog.DATE_OPERATORS_NEW and field_type is not None and field_type != "date":
                    issues.append(_issue((*loc, "operator"), f"{operator} compares dates, and {label} is not a date."))
            if operator not in catalog.VALUELESS_OPERATORS and not items:
                issues.append(_issue((*loc, "value"), "A value is required for this operator."))
                continue
            if operator in catalog.DAY_COUNT_OPERATORS and items:
                if not (len(items) == 1 and items[0].isdigit()):
                    issues.append(_issue((*loc, "value"), "Enter a whole number of days (0 or more)."))
            if operator == "BETWEEN" and isinstance(raw_value, (list, tuple)) and len(items) != 2:
                issues.append(_issue((*loc, "value"), "Give a low and a high value."))
            if check_options and options and operator in ("EQUALS", "NOT_EQUALS", "IN", "NOT_IN") and items:
                message = _option_issue(label, items, options)
                if message:
                    issues.append(_issue((*loc, "value"), message))
            if currency:
                if field_type != "money":
                    issues.append(_issue((*loc, "currency"), "A currency applies only to an amount."))
                elif evaluator.known_currency(currency) is None:
                    issues.append(_issue((*loc, "currency"), f"{currency!r} is not a currency this product knows."))


def _store_list_values(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """IN, NOT_IN, BETWEEN and the array operators store a JSON list. A comma string from an older client is split
    exactly as the evaluator always split it, so the rule means what it meant."""
    from app.services.automation import evaluator

    out: list[dict[str, Any]] = []
    for group in groups:
        conditions = []
        for condition in group.get("conditions") or []:
            condition = dict(condition)
            operator = str(condition.get("operator") or "").upper()
            value = condition.get("value")
            if operator in catalog.LIST_VALUE_OPERATORS and isinstance(value, str):
                parts = evaluator.split_between(value) if operator == "BETWEEN" else evaluator.expected_items(value)
                if parts:
                    condition["value"] = parts
            if not condition.get("currency"):
                condition.pop("currency", None)
            conditions.append(condition)
        out.append({**group, "conditions": conditions})
    return out


def _validate_actions(
    key: str,
    actions: list[dict[str, Any]],
    trigger_keys: list[str],
    authoring: Authoring,
    issues: list[dict[str, Any]],
    *,
    legacy: bool,
) -> list[dict[str, Any]]:
    excluded = catalog.excluded_actions_for(trigger_keys)
    specs, _ = catalog.resolve_trigger_keys(trigger_keys)
    documents = all(spec.has_document for spec in specs)
    event_keys = {f.path for f in catalog.fields_for(trigger_keys)}
    ctx = SaveContext(
        db=authoring.db,
        organization_id=authoring.organization_id,
        workspace_id=authoring.workspace_id,
        trigger_keys=tuple(trigger_keys),
    )
    stored: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        loc = (key, index)
        raw_type = str(action.get("action_type") or "")
        definition = action_registry.get(raw_type)
        if definition is None:
            issues.append(_issue((*loc, "action_type"), f"Unknown action {raw_type!r}."))
            continue
        action_type = definition.action_type
        if action_type in excluded:
            issues.append(_issue((*loc, "action_type"), f"{definition.label} cannot run on the selected trigger."))
        allowed_here = catalog.allowed_actions_for(trigger_keys)
        if allowed_here is not None and action_type not in allowed_here:
            issues.append(_issue(
                (*loc, "action_type"),
                f"{definition.label} cannot run on the selected trigger. On Helm, a rule may only notify people, send "
                "an email, post to chat, call a webhook, open a review or tag; it never approves, pays or schedules a payment."))
        if action_type in DOCUMENT_ACTIONS and not documents:
            issues.append(_issue((*loc, "action_type"), f"{definition.label} needs a document."))
        if not action_available(definition, capabilities=authoring.granted_capabilities, addons=authoring.addons):
            if definition.either:
                issues.append(_issue((*loc, "action_type"), f"{definition.label} is not included in your plan. It needs GST Credit, or its add-on.", "plan"))
            elif definition.capability and definition.capability not in authoring.granted_capabilities:
                issues.append(_issue((*loc, "action_type"), f"{definition.label} is not included in your plan.", "plan"))
            else:
                issues.append(_issue((*loc, "action_type"), f"{definition.label} needs an add-on your organization does not have.", "plan"))
        if not _role_ok(definition.minimum_role, authoring.organization_role):
            issues.append(_issue((*loc, "action_type"), f"Only organization owners and admins can add {definition.label}.", "permission"))

        config_values = dict(action.get("config") or {})
        try:
            config = definition.parse(config_values)
        except ValidationError as exc:
            for error in exc.errors():
                issues.append(_issue((*loc, "config", *error["loc"]), error["msg"]))
            continue

        for template_field in definition.template_fields:
            bad = invalid_variables(str(getattr(config, template_field, "") or ""), event_keys=event_keys)
            if bad:
                issues.append(_issue((*loc, "config", template_field), f"Unknown template variable(s): {', '.join(bad)}."))

        if definition.validate_resources is not None:
            for config_key, message in definition.validate_resources(ctx, config).items():
                issues.append(_issue((*loc, "config", config_key), message))

        if legacy and raw_type != action_type:
            # An ARCH-13 client: keep its stored shape so its message is unchanged.
            stored.append({"action_type": raw_type, "config": config_values})
        else:
            stored.append({"action_type": action_type, "config": _dump(config)})
    return stored


def normalise(payload: dict[str, Any], authoring: Authoring, *, check_options: bool = True) -> NormalisedRule:
    """Validate a complete rule document and return its storage shape.

    `check_options` is False when a rule is only switched back on, not edited: a value saved before the choices
    were enforced must not stop someone turning their own rule on again.
    """
    issues: list[dict[str, Any]] = []
    trigger_keys = payload.get("triggers")
    legacy = trigger_keys is None

    if legacy:
        legacy_event = str(payload.get("event") or "")
        mapped = catalog.LEGACY_EVENT_TO_TRIGGER.get(legacy_event)
        if mapped is None:
            issues.append(_issue(("event",), f"Unknown event {legacy_event!r}."))
            trigger_keys = []
        else:
            trigger_keys = [mapped]
    else:
        trigger_keys = list(dict.fromkeys(trigger_keys))
        specs, unknown = catalog.resolve_trigger_keys(trigger_keys)
        for key in unknown:
            issues.append(_issue(("triggers", trigger_keys.index(key)), f"Unknown trigger {key!r}."))
        for spec in specs:
            if not catalog.available_for(spec, capabilities=authoring.granted_capabilities, addons=authoring.addons):
                issues.append(_issue(("triggers", trigger_keys.index(spec.key)), f"{spec.label} is not included in your plan.", "plan"))

    on_error = str(payload.get("on_error") or "HALT")
    actions = [_dump(a) for a in payload.get("actions") or []]
    else_actions = [_dump(a) for a in payload.get("else_actions") or []]
    if not actions:
        issues.append(_issue(("actions",), "Add at least one action."))
    if len(actions) > MAX_ACTIONS or len(else_actions) > MAX_ACTIONS:
        issues.append(_issue(("actions",), f"At most {MAX_ACTIONS} actions per branch."))

    if legacy:
        conditions = [_dump(c) for c in payload.get("conditions") or []]
        groups = [{"logic_operator": payload.get("logic_operator") or "AND", "conditions": conditions}]
        groups_operator = "AND"
    else:
        groups = [_dump(g) for g in payload.get("condition_groups") or []]
        groups = [g for g in groups if g.get("conditions")]
        groups_operator = str(payload.get("groups_operator") or "AND")
    _validate_conditions(groups, trigger_keys, issues, check_options=check_options and not legacy)
    if not legacy:
        groups = _store_list_values(groups)

    has_conditions = any(g.get("conditions") for g in groups)
    if else_actions and not has_conditions:
        issues.append(_issue(("else_actions",), "'Otherwise' actions need at least one condition."))

    stored_actions = _validate_actions("actions", actions, trigger_keys, authoring, issues, legacy=legacy)
    stored_else = _validate_actions("else_actions", else_actions, trigger_keys, authoring, issues, legacy=False)

    if issues:
        raise FlowValidationError(issues)

    from app.services.automation.conditions import flatten

    event_types = catalog.event_types_for(trigger_keys)
    if legacy:
        return NormalisedRule(
            event=str(payload.get("event")),
            trigger_keys=trigger_keys,
            event_types=event_types,
            conditions=groups[0]["conditions"],
            logic_operator=str(groups[0]["logic_operator"]),
            actions=stored_actions,
            flow_spec=None,
            on_error=on_error,
        )
    single_group = len(groups) == 1
    return NormalisedRule(
        event=trigger_keys[0],
        trigger_keys=trigger_keys,
        event_types=event_types,
        conditions=flatten(groups),
        logic_operator=str(groups[0]["logic_operator"]) if single_group else groups_operator,
        actions=stored_actions,
        flow_spec={
            "version": 1,
            "condition_groups": groups,
            "groups_operator": groups_operator,
            "else_actions": stored_else,
        },
        on_error=on_error,
    )


def payload_from_rule(rule: Any, event_types: list[str]) -> dict[str, Any]:
    """The rule as a complete flow document, for merging a partial update."""
    spec = rule.flow_spec if isinstance(rule.flow_spec, dict) else None
    if spec is None:
        return {
            "event": rule.event,
            "conditions": list(rule.conditions or []),
            "logic_operator": rule.logic_operator,
            "actions": list(rule.actions or []),
            "on_error": rule.on_error,
        }
    return {
        "triggers": catalog.trigger_keys_for_events(event_types),
        "condition_groups": list(spec.get("condition_groups") or []),
        "groups_operator": spec.get("groups_operator") or "AND",
        "actions": list(rule.actions or []),
        "else_actions": list(spec.get("else_actions") or []),
        "on_error": rule.on_error,
    }


def rule_view(rule: Any, event_types: list[str], *, paused: bool = False, version: int = 0) -> dict[str, Any]:
    spec = rule.flow_spec if isinstance(rule.flow_spec, dict) else None
    if spec is not None:
        groups = list(spec.get("condition_groups") or [])
        groups_operator = spec.get("groups_operator") or "AND"
        else_actions = list(spec.get("else_actions") or [])
    else:
        groups = (
            [{"logic_operator": rule.logic_operator, "conditions": list(rule.conditions or [])}]
            if rule.conditions
            else []
        )
        groups_operator = "AND"
        else_actions = []
    return {
        "id": rule.id,
        "workspace_id": rule.workspace_id,
        "created_by_user_id": rule.created_by_user_id,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
        "name": rule.name,
        "priority": rule.priority,
        "event": rule.event,
        "is_active": rule.is_active,
        "conditions": list(rule.conditions or []),
        "logic_operator": rule.logic_operator,
        "actions": list(rule.actions or []),
        "triggers": catalog.trigger_keys_for_events(event_types),
        "trigger_events": list(event_types),
        "condition_groups": groups,
        "groups_operator": groups_operator,
        "else_actions": else_actions,
        "is_flow": spec is not None,
        "graph_version": int(rule.graph_version or 0),
        "on_error": rule.on_error,
        "max_runs_per_hour": getattr(rule, "max_runs_per_hour", None),
        "cooldown_hours": getattr(rule, "cooldown_hours", None),
        "effective_runs_per_hour": _effective_runs_per_hour(rule),
        "paused": bool(paused and rule.is_active),
        "version": version,
    }


def _effective_runs_per_hour(rule: Any) -> int:
    from app.services.automation import volume

    return volume.effective_runs_per_hour(rule)


def dry_run(db: Any, *, rule: Any, work_item: Any) -> dict[str, Any]:
    """Evaluate the conditions on a document and report what WOULD run.

    Nothing is performed. A test run that started a redaction or posted to a
    customer's endpoint because an administrator clicked "Test" would be a
    production side effect with no trigger behind it.
    """
    from app.models.workspace import Workspace
    from app.services.automation import conditions, evaluator
    from app.services.automation.contracts import ActionNodeConfig

    started = time.perf_counter()
    workspace = db.get(Workspace, getattr(work_item, "workspace_id", None)) if db is not None else None
    context = evaluator.EvalContext.for_workspace(workspace) if workspace is not None else evaluator.EvalContext()
    spec = rule.flow_spec if isinstance(rule.flow_spec, dict) else None
    if spec is not None:
        groups = list(spec.get("condition_groups") or [])
        matched, traced = conditions.trace_groups(
            groups,
            groups_operator=spec.get("groups_operator"),
            work_item=work_item,
            event_payload=None,
            context=context,
        )
        planned = list(rule.actions or []) if matched else list(spec.get("else_actions") or [])
        branch = "then" if matched else ("otherwise" if planned else "none")
    else:
        matched, traced = conditions.trace_node_config(
            {"conditions": list(rule.conditions or []), "logic_operator": rule.logic_operator},
            work_item=work_item,
            event_payload=None,
            context=context,
        )
        planned = list(rule.actions or []) if matched else []
        branch = "then" if matched else "none"

    lines: list[str] = []
    ok = True
    for index, action in enumerate(planned):
        node = ActionNodeConfig.from_node_config(action)
        definition = action_registry.get(node.action_type)
        if definition is None:
            ok = False
            lines.append(f"#{index + 1} unknown action {node.action_type!r}")
            continue
        try:
            definition.parse(node.authored_parameters())
        except ValidationError as exc:
            ok = False
            lines.append(f"#{index + 1} {definition.label}: invalid config ({exc.error_count()} issue(s))")
            continue
        lines.append(f"#{index + 1} would run: {definition.label}")

    if not planned:
        message = "Conditions were not met; nothing would run."
    else:
        message = f"Conditions {'met' if matched else 'not met'} ({branch} branch). " + "; ".join(lines)
    return {
        "success": ok,
        "matched": bool(matched),
        "notification_sent": False,
        "message": message[:2000],
        "execution_time_ms": round((time.perf_counter() - started) * 1000.0, 2),
        # Session J: what each condition read, wanted and decided, in words.
        "conditions": traced,
    }


__all__ = [
    "Authoring",
    "FlowValidationError",
    "NormalisedRule",
    "dry_run",
    "normalise",
    "payload_from_rule",
    "rule_view",
]
