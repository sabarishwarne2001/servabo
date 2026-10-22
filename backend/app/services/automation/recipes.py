"""Session J, Phase 5 — recipes: ready-made rules a new customer starts from instead of a blank page.

One list, here, served by `GET /automation/recipes`. Each recipe is a complete rule document, the same shape a save takes,
so "Use this recipe" opens the builder with it filled in and the person adjusts it in plain words. A recipe never holds a
secret or an id from a tenant: where a rule needs something only the tenant has (a Slack channel, a supplier's case
template, an approver's email) the recipe lists it under `fill_ins`, and the builder asks for it before saving.

`tests/engines/test_automation_recipes_live.py` saves EVERY recipe (with its fill-ins answered) on an Enterprise tenant, so
a recipe that stops validating, or names a trigger or action that no longer exists, fails the build.

Money is written in currency units with an explicit currency, never in micros. No recipe moves money: nothing approves,
pays or schedules a payment.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.automation import actions as action_registry
from app.services.automation import flow_service
from app.services.automation.triggers import TRIGGERS_BY_KEY, available_for

CATEGORIES = ("Invoices", "Compliance", "GST", "Follow-ups", "Team")

INVOICE = {"field": "classification_details.document_classification", "operator": "EQUALS", "value": "Invoice"}


def _rule(name: str, triggers: list[str], actions: list[dict[str, Any]], *, groups: Optional[list[list[dict[str, Any]]]] = None,
          groups_operator: str = "AND", else_actions: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return {
        "name": name,
        "triggers": triggers,
        "groups_operator": groups_operator,
        "condition_groups": [{"logic_operator": "AND", "conditions": group} for group in (groups or [])],
        "actions": actions,
        "else_actions": else_actions or [],
        "on_error": "CONTINUE",
    }


def _step(action_type: str, **config: Any) -> dict[str, Any]:
    return {"action_type": action_type, "config": config}


def _fill(path: str, kind: str, label: str, hint: str) -> dict[str, str]:
    return {"path": path, "kind": kind, "label": label, "hint": hint}


RECIPES: tuple[dict[str, Any], ...] = (
    {
        "id": "hold-big-invoices",
        "title": "Hold invoices above ₹10 lakh for review",
        "summary": "Any invoice over ₹10,00,000 waits for a person to check it before anything else happens.",
        "category": "Invoices",
        "icon": "shield",
        "fill_ins": [],
        "rule": _rule("Hold invoices above ₹10 lakh for review", ["document.completed"], [
            _step("review.escalate", reason="Invoice above ₹10 lakh: a person checks it first."),
        ], groups=[[INVOICE, {"field": "total_amount", "operator": "GREATER_THAN", "value": "1000000", "currency": "INR"}]]),
    },
    {
        "id": "tag-high-value",
        "title": "Tag high-value invoices",
        "summary": "Put a “high-value” tag on every invoice over ₹5 lakh so they are easy to find and filter.",
        "category": "Invoices",
        "icon": "tag",
        "fill_ins": [],
        "rule": _rule("Tag high-value invoices", ["document.completed"], [
            _step("document.tag", add=["high-value"]),
        ], groups=[[INVOICE, {"field": "total_amount", "operator": "GREATER_THAN", "value": "500000", "currency": "INR"}]]),
    },
    {
        "id": "missing-irn",
        "title": "Flag invoices with no e-invoice IRN",
        "summary": "Tag an invoice that has no IRN and tell your admins, so it is chased before the return is filed.",
        "category": "Compliance",
        "icon": "alert",
        "fill_ins": [],
        "rule": _rule("Flag invoices with no e-invoice IRN", ["document.completed"], [
            _step("document.tag", add=["missing-irn"]),
            _step("notify.role", roles=["ADMIN"], title="No IRN: {{document.filename}}",
                  message="This invoice has no e-invoice IRN. Ask the supplier for it.", priority="WARNING"),
        ], groups=[[INVOICE, {"field": "document.has_irn", "operator": "EQUALS", "value": "false"}]]),
    },
    {
        "id": "due-soon",
        "title": "Tell finance about invoices due within 3 days",
        "summary": "When an invoice is due in three days or less, your finance admins get a note so nothing is paid late.",
        "category": "Invoices",
        "icon": "clock",
        "fill_ins": [],
        "rule": _rule("Invoices due within 3 days", ["document.completed"], [
            _step("notify.role", roles=["ADMIN", "BILLING"], title="Due soon: {{document.filename}}",
                  message="This invoice is due within 3 days.", priority="WARNING"),
        ], groups=[[INVOICE, {"field": "document.days_until_due", "operator": "LESS_THAN_OR_EQUAL", "value": "3"}]]),
    },
    {
        "id": "anomaly-alert",
        "title": "Tell finance admins when an anomaly is found",
        "summary": "A possible duplicate or odd amount is caught by Forensic audit; your admins hear about it at once.",
        "category": "Compliance",
        "icon": "alert",
        "fill_ins": [],
        "rule": _rule("Anomaly found: tell admins", ["anomaly.detected"], [
            _step("notify.role", roles=["ADMIN"], title="Anomaly found: {{document.filename}}",
                  message="{{trigger.label}} on {{document.filename}}.", priority="ERROR"),
        ]),
    },
    {
        "id": "bank-account-changed",
        "title": "Tell finance when a supplier\u2019s bank account changes",
        "summary": "A changed bank account on a supplier\u2019s invoice is the classic payment fraud. Finance is told before anything is paid.",
        "category": "Compliance",
        "icon": "alert",
        "fill_ins": [],
        "rule": _rule("Supplier bank account changed: tell finance", ["payment_risk.flagged"], [
            _step("notify.role", roles=["ADMIN", "BILLING"], title="Bank account changed: {{document.filename}}",
                  message="The supplier\u2019s bank account differs from before. Check it with the supplier before paying.",
                  priority="ERROR"),
        ], groups=[[{"field": "event.kind", "operator": "EQUALS", "value": "BANK_ACCOUNT_CHANGED"}]]),
    },
    {
        "id": "payment-risk-chat",
        "title": "Post payment-risk flags to Slack or Teams",
        "summary": "A changed bank account or a suspicious supplier is posted to your finance channel the moment it is flagged.",
        "category": "Compliance",
        "icon": "chat",
        "fill_ins": [_fill("actions.0.config.endpoint_id", "chat_endpoint", "Slack or Teams channel",
                           "Add a channel under Integrations first, then choose it here.")],
        "rule": _rule("Payment-risk flag: post to chat", ["payment_risk.flagged"], [
            _step("chat.post", endpoint_id="", title="Payment-risk flag", message="{{trigger.label}}: {{document.filename}}"),
        ]),
    },
    {
        "id": "failed-document-chat",
        "title": "Post to chat when a document fails to process",
        "summary": "If a document cannot be read, your team hears about it in chat instead of finding out days later.",
        "category": "Team",
        "icon": "chat",
        "fill_ins": [_fill("actions.0.config.endpoint_id", "chat_endpoint", "Slack or Teams channel",
                           "Add a channel under Integrations first, then choose it here.")],
        "rule": _rule("Document failed: post to chat", ["document.failed"], [
            _step("chat.post", endpoint_id="", title="A document failed", message="{{document.filename}} could not be processed."),
        ]),
    },
    {
        "id": "litigation-hold",
        "title": "Hold anything tagged “litigation”",
        "summary": "The moment a document gets the tag “litigation” it is placed under a legal hold, so it cannot be deleted.",
        "category": "Compliance",
        "icon": "lock",
        "fill_ins": [],
        "rule": _rule("Hold anything tagged litigation", ["document.field_changed"], [
            _step("legal_hold.place", reason="Tagged litigation"),
        ], groups=[[{"field": "document.tags", "operator": "ARRAY_CONTAINS_ANY", "value": ["litigation"]}]]),
    },
    {
        "id": "contract-renewal",
        "title": "Follow up on contracts ending in 60 days",
        "summary": "A contract that ends within 60 days gets a renewal follow-up with a due date, so it is not missed.",
        "category": "Follow-ups",
        "icon": "calendar",
        "fill_ins": [],
        "rule": _rule("Contract ending soon: follow up", ["document.completed"], [
            _step("obligation.create", title="Renew or end: {{document.filename}}", kind="RENEWAL", due_in_days=30),
        ], groups=[[{"field": "classification_details.document_classification", "operator": "EQUALS", "value": "Contract"},
                    {"field": "termination_date", "operator": "WITHIN_NEXT_DAYS", "value": "60"}]]),
    },
    {
        "id": "weekly-digest",
        "title": "A Monday reminder to clear the review queue",
        "summary": "Every Monday your admins are reminded to look at what is waiting for review.",
        "category": "Team",
        "icon": "calendar",
        "fill_ins": [],
        "rule": _rule("Monday review reminder", ["schedule.weekly"], [
            _step("notify.role", roles=["ADMIN"], title="Review queue", message="Start the week by clearing the review queue."),
        ]),
    },
    {
        "id": "gst-chase-supplier",
        "title": "Remind a supplier whose invoice is missing from GSTR-2B",
        "summary": "When an invoice has waited for its supplier past your notice period, the supplier gets a polite reminder (once a week).",
        "category": "GST",
        "icon": "mail",
        "fill_ins": [],
        "rule": _rule("Remind suppliers missing from GSTR-2B", ["gst.waiting_for_supplier"], [
            _step("gst.remind_supplier", at_most_every_days=7),
        ]),
    },
    {
        "id": "gst-risk-chat",
        "title": "Tell finance when GST credit is at risk of reversal",
        "summary": "The 180-day clock is nearly up on an unpaid invoice; your admins are told while there is still time to pay it.",
        "category": "GST",
        "icon": "alert",
        "fill_ins": [],
        "rule": _rule("GST credit at risk: tell admins", ["gst.reversal_risk"], [
            _step("notify.role", roles=["ADMIN", "BILLING"], title="GST credit at risk",
                  message="{{trigger.label}}: {{document.filename}}", priority="WARNING"),
        ]),
    },
    {
        "id": "assign-reviewer",
        "title": "Send documents tagged \u201cneeds-review\u201d to a named reviewer",
        "summary": "Tag a document \u201cneeds-review\u201d and it lands with the person you choose, due in two days.",
        "category": "Team",
        "icon": "user",
        "fill_ins": [_fill("actions.0.config.assignee_email", "member_email", "Reviewer",
                           "Choose the person who works these reviews.")],
        "rule": _rule("Tagged needs-review: assign a reviewer", ["document.field_changed"], [
            _step("review.assign", assignee_email="", reason="Tagged needs-review.", due_in_hours=48),
        ], groups=[[{"field": "document.tags", "operator": "ARRAY_CONTAINS_ANY", "value": ["needs-review"]}]]),
    },
    {
        "id": "obligation-overdue",
        "title": "Escalate overdue obligations to admins",
        "summary": "An obligation that has passed its due date is sent to your admins the same day.",
        "category": "Follow-ups",
        "icon": "clock",
        "fill_ins": [],
        "rule": _rule("Overdue obligation: tell admins", ["obligation.overdue"], [
            _step("notify.role", roles=["ADMIN"], title="Overdue", message="{{trigger.label}}: {{document.filename}}",
                  priority="ERROR"),
        ]),
    },
    {
        "id": "big-invoice-email",
        "title": "Email the CFO about invoices above ₹25 lakh",
        "summary": "A short email to one person for the few invoices that matter most.",
        "category": "Invoices",
        "icon": "mail",
        "fill_ins": [_fill("actions.0.config.recipient", "email", "Who to email", "The address that should receive it.")],
        "rule": _rule("Email about invoices above ₹25 lakh", ["document.completed"], [
            _step("email.send", recipient="", subject="Large invoice: {{document.filename}}",
                  body="An invoice above ₹25 lakh has just been read: {{document.filename}}."),
        ], groups=[[INVOICE, {"field": "total_amount", "operator": "GREATER_THAN", "value": "2500000", "currency": "INR"}]]),
    },
)


def _locked(recipe: dict[str, Any], authoring: Any) -> Optional[dict[str, Optional[str]]]:
    """Why a recipe is not open to this tenant: the words, and the capability the upgrade dialog should name."""
    for key in recipe["rule"]["triggers"]:
        spec = TRIGGERS_BY_KEY[key]
        if not available_for(spec, capabilities=authoring.granted_capabilities, addons=authoring.addons):
            return {
                "reason": "Needs the GST Credit add-on or a plan that includes GST Credit." if spec.addon else "Not included in your plan.",
                "capability": spec.capability or spec.addon,
                "feature": spec.label,
            }
    for step in [*recipe["rule"]["actions"], *recipe["rule"]["else_actions"]]:
        definition = action_registry.get(step["action_type"])
        if definition is not None and not flow_service.action_available(
                definition, capabilities=authoring.granted_capabilities, addons=authoring.addons):
            return {"reason": "Not included in your plan.", "capability": definition.capability or definition.addon,
                    "feature": definition.label}
    return None


def build(authoring: Any) -> list[dict[str, Any]]:
    """The recipes, each marked available (or not, with the reason) for this tenant."""
    out: list[dict[str, Any]] = []
    for recipe in RECIPES:
        locked = _locked(recipe, authoring)
        triggers = [TRIGGERS_BY_KEY[k].label for k in recipe["rule"]["triggers"]]
        out.append({
            **recipe,
            "available": locked is None,
            "unavailable_reason": locked["reason"] if locked else None,
            # What the upgrade dialog names when a locked recipe is chosen.
            "locked_capability": locked["capability"] if locked else None,
            "locked_feature": locked["feature"] if locked else None,
            "trigger_labels": triggers,
        })
    return out


def fill(recipe_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    """The recipe's rule with its fill-ins answered (`path` is `actions.0.config.endpoint_id`). For tests and the builder."""
    import copy

    recipe = next(r for r in RECIPES if r["id"] == recipe_id)
    rule = copy.deepcopy(recipe["rule"])
    for path, value in answers.items():
        target: Any = rule
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        target[parts[-1]] = value
    return rule


__all__ = ["CATEGORIES", "RECIPES", "build", "fill"]
