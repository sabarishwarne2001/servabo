"""ARCH-37 — the action registry.

`perform_action(state, spec)` is a dictionary dispatch. Before ARCH-37 the
executor's `_default_perform_action` was an if/elif over two action types, and
`resolve_selector("webhook")` returned a selector for an action nothing could
perform, so a webhook rule failed at run time with "Unsupported action type".

`_assert_registry_complete` runs at import. Every registered action must have
a config schema, a registered R33 selector, a perform function, and a declared
capability and minimum role; every alias must name one action. A module that
forgets a part stops the process from starting, not the first customer run.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.automation.actions import (
    autonomy_decide,
    chat_post,
    document_tag,
    email_send,
    erp_post,
    gst_remind_supplier,
    legal_hold_place,
    notify_role,
    obligation_create,
    redaction_start,
    review_assign,
    review_escalate,
    supplier_request_document,
    warehouse_export,
    webhook_send,
    work_item_mutate,
)
from app.services.automation.actions.base import (
    MINIMUM_ROLES,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
)

_MODULES = (
    webhook_send,
    redaction_start,
    review_escalate,
    warehouse_export,
    notify_role,
    autonomy_decide,
    email_send,
    work_item_mutate,
    erp_post,  # ARCH47-S1:action-erp-post
    # Session J
    document_tag,
    review_assign,
    legal_hold_place,
    chat_post,
    gst_remind_supplier,
    obligation_create,
    supplier_request_document,
)

ACTIONS: Mapping[str, ActionDefinition] = {
    module.DEFINITION.action_type: module.DEFINITION for module in _MODULES
}

#: The seven actions ARCH-37 sells, in catalog order. `work_item.mutate`
#: predates it and is registered alongside; ARCH-47's `erp.post` is sold with
#: capability.erp_posting and registered alongside too (ERP_ACTION_TYPES).
COMMERCIAL_ACTION_TYPES: tuple[str, ...] = (
    "webhook.send",
    "redaction.start",
    "review.escalate",
    "warehouse.export",
    "notify.role",
    "autonomy.decide",
    "email.send",
)

#: ARCH47-S1:erp-action-types. Registered with the others; gated on capability.erp_posting.
ERP_ACTION_TYPES: tuple[str, ...] = ("erp.post",)

ALIASES: Mapping[str, str] = {
    alias: definition.action_type
    for definition in ACTIONS.values()
    for alias in definition.aliases
}

#: Handled by the executor itself, never by this registry.
LLM_ACTION_TYPES: frozenset[str] = frozenset({"llm.extract", "llm.classify"})


def canonical(action_type: str) -> str:
    normalised = (action_type or "").strip().lower()
    return ALIASES.get(normalised, normalised)


def get(action_type: str) -> ActionDefinition | None:
    return ACTIONS.get(canonical(action_type))


def selector_for(action_type: str) -> str | None:
    definition = get(action_type)
    return definition.selector if definition is not None else None


def perform_action(state: Any, spec: Any) -> ActionOutcome:
    definition = get(spec.action_type)
    if definition is None:
        raise ActionFailure(f"Unsupported action type '{spec.action_type}'.", recoverable=False)
    _recheck_plan(state, definition)
    outcome = definition.perform(state, spec)
    if not isinstance(outcome, ActionOutcome):
        raise TypeError(f"{definition.action_type}.perform returned {type(outcome).__name__}")
    return outcome


def _recheck_plan(state: Any, definition: ActionDefinition) -> None:
    """Session J: a capability or add-on can change after a rule is saved. The run asks again (an action that checks for
    itself, like `erp.post`, still does)."""
    if definition.capability is None and definition.addon is None:
        return
    from app.api import capability_gate
    from app.services.billing import entitlement_service

    organization_id = state.execution.organization_id
    has_cap = definition.capability is None or capability_gate.has_capability(
        state.db, organization_id=organization_id, capability_key=definition.capability)
    has_addon = definition.addon is None or entitlement_service.addon_access(
        state.db, organization_id=organization_id, addon_key=definition.addon).can_maintain
    ok = (
        ((definition.capability is not None and has_cap) or (definition.addon is not None and has_addon))
        if definition.either else (has_cap and has_addon)
    )
    if not ok:
        raise ActionFailure(f"{definition.label} is not included in your plan any more.", recoverable=False)


def _assert_registry_complete() -> None:
    from pydantic import BaseModel

    from app.services import tools as _tools  # noqa: F401
    from app.services.fenced_context import TOOL_SELECTORS
    from app.services.tools import flow_selectors  # noqa: F401  (registers)

    problems: list[str] = []
    for action_type, definition in ACTIONS.items():
        if not (isinstance(definition.config_model, type) and issubclass(definition.config_model, BaseModel)):
            problems.append(f"{action_type}: no config schema")
        if not issubclass(definition.config_model, ActionConfig):
            problems.append(f"{action_type}: config schema does not forbid unknown keys")
        if not definition.selector or definition.selector not in TOOL_SELECTORS:
            problems.append(f"{action_type}: selector {definition.selector!r} is not registered")
        if not callable(definition.perform):
            problems.append(f"{action_type}: no perform")
        if definition.minimum_role not in MINIMUM_ROLES:
            problems.append(f"{action_type}: unknown minimum role {definition.minimum_role!r}")
        if not hasattr(definition, "capability"):
            problems.append(f"{action_type}: no capability declaration")
    missing = [a for a in (*COMMERCIAL_ACTION_TYPES, *ERP_ACTION_TYPES) if a not in ACTIONS]
    if missing:
        problems.append(f"commercial actions not registered: {missing}")
    clashes = [alias for alias in ALIASES if alias in ACTIONS]
    if clashes:
        problems.append(f"aliases shadow action types: {clashes}")
    if len(ALIASES) != sum(len(d.aliases) for d in ACTIONS.values()):
        problems.append("an alias is claimed by two actions")
    if problems:
        raise RuntimeError("ARCH-37 action registry is incomplete: " + "; ".join(problems))


_assert_registry_complete()


__all__ = [
    "ACTIONS",
    "ALIASES",
    "COMMERCIAL_ACTION_TYPES",
    "ERP_ACTION_TYPES",
    "LLM_ACTION_TYPES",
    "ActionDefinition",
    "ActionFailure",
    "ActionOutcome",
    "canonical",
    "get",
    "perform_action",
    "selector_for",
]
