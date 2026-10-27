"""Invariant (a) of the prompt-injection map (Final session 2A, Phase 3; docs/hardening/PROMPT-INJECTION.md).

No automation action, assistant tool, agent or Helm action can approve a payment, pay, release a hold on a payment,
change a supplier's bank details or mark an invoice paid on its own: a person always does. Each registry is enumerated
here and every entry is given a class; a new entry fails the build until it is classified, and none may be in MONEY.

* Helm: the four payment decisions (schedule, approve, release a hold, mark paid) need a person in every mode, whatever
  the act cap (N-196). Holding a payment is protective and may run alone in Act mode.
* Automation actions and their tool selectors: none moves money; the one that writes to the books (`erp.post`) is a
  record of a bill, and its payment reference objects are covered in ERP below.
* The process agent: only two kinds may apply on their own, and neither touches money.
"""

from __future__ import annotations

import pytest

from app.services.helm import vocabulary as v
from app.services.helm.guard import GuardContext, SYSTEM, guard
from tests.services.helm.test_guard import M, action, book, mandate, payable

MONEY = "MONEY"
#: Helm's actions. MONEY: a person decides every time.
HELM_CLASSES = {
    v.ACTION_SCHEDULE_PAYMENT: MONEY, v.ACTION_APPROVE_PAYMENT: MONEY, v.ACTION_RELEASE_HOLD: MONEY,
    v.ACTION_MARK_PAID: MONEY,
    v.ACTION_HOLD_PAYMENT: "PROTECTIVE",
    v.ACTION_DRAFT_DISPUTE: "OUTBOUND", v.ACTION_DRAFT_RECONCILIATION: "OUTBOUND", v.ACTION_SEND_REMINDER: "OUTBOUND",
    v.ACTION_REQUEST_DOCUMENT: "OUTBOUND", v.ACTION_WEBHOOK: "OUTBOUND", v.ACTION_NOTIFY: "INTERNAL",
    v.ACTION_CREATE_TASK: "INTERNAL", v.ACTION_DECIDE_RENEWAL: "INTERNAL",
}
#: Automation actions (`services/automation/actions`). None is MONEY.
AUTOMATION_CLASSES = {
    "webhook.send": "OUTBOUND", "email.send": "OUTBOUND", "chat.post": "OUTBOUND", "notify.role": "INTERNAL",
    "gst.remind_supplier": "OUTBOUND", "supplier.request_document": "OUTBOUND", "redaction.start": "DOCUMENT",
    "review.escalate": "REVIEW", "review.assign": "REVIEW", "autonomy.decide": "REVIEW", "document.tag": "DOCUMENT",
    "work_item.mutate": "DOCUMENT", "legal_hold.place": "PROTECTIVE", "obligation.create": "INTERNAL",
    "warehouse.export": "EXPORT", "erp.post": "BOOKS",
}
#: Process-agent kinds that may apply without a person.
AGENT_AUTO = {"extraction.approve_consensus": "DOCUMENT", "assertion.accept_engine": "DOCUMENT"}


def test_every_helm_action_is_classified() -> None:
    assert set(HELM_CLASSES) == set(v.ACTION_KINDS), "classify the new Helm action here"
    assert {k for k, c in HELM_CLASSES.items() if c == MONEY} == set(v.PAYMENT_ACTIONS) - {v.ACTION_HOLD_PAYMENT}


@pytest.mark.parametrize("kind", sorted(k for k, c in HELM_CLASSES.items() if c == MONEY))
def test_no_helm_payment_decision_runs_without_a_person_in_any_mode(kind) -> None:
    p = payable(1, amount_micros=1_000 * M, confidence=v.CONFIDENCE_VERIFIED)
    s = book([p])
    for m in (mandate("pay_on_time", mode="act", cap=10_000_000 * M), mandate("pay_on_time", mode="act"),
              mandate("pay_on_time", mode="propose")):
        result = guard(action(p, kind=kind, m=m), s, [m], SYSTEM, GuardContext())
        assert not result.can_run_alone, f"{kind} would run alone under {m.spec.autonomy}"


def test_holding_a_payment_may_still_run_alone_in_act_mode() -> None:
    p = payable(1, amount_micros=1_000 * M, confidence=v.CONFIDENCE_VERIFIED)
    m = mandate("pay_on_time", mode="act")
    assert guard(action(p, kind=v.ACTION_HOLD_PAYMENT, m=m), book([p]), [m], SYSTEM, GuardContext()).can_run_alone


#: Tool selectors that are not an automation action's own (they build specs or agent proposals). None moves money.
OTHER_SELECTORS = {
    "automation.action_selector": "BUILDS A SPEC", "automation.mutation_selector": "BUILDS A SPEC",
    "agent.resolve_review_item": "REVIEW", "agent.assign_review_item": "REVIEW", "agent.reevaluate_case": "REVIEW",
    "agent.request_case_document": "DOCUMENT REQUEST (no email)",
}


def test_every_automation_action_and_tool_selector_is_classified_and_none_moves_money() -> None:
    from app.services import tools  # noqa: F401  (registers the selectors)
    from app.services.automation.actions import ACTIONS
    from app.services.fenced_context import TOOL_SELECTORS
    from app.services.tools import agent_selectors, flow_selectors  # noqa: F401

    assert set(ACTIONS) == set(AUTOMATION_CLASSES), f"classify the new automation action: {set(ACTIONS) ^ set(AUTOMATION_CLASSES)}"
    assert MONEY not in AUTOMATION_CLASSES.values()
    own = {definition.selector for definition in ACTIONS.values()}
    unclassified = set(TOOL_SELECTORS) - own - set(OTHER_SELECTORS)
    assert not unclassified, f"classify the new tool selector: {sorted(unclassified)}"
    assert MONEY not in OTHER_SELECTORS.values()


def test_the_process_agent_applies_on_its_own_only_document_decisions() -> None:
    from app.services.process_intel.agent import vocabulary as av

    assert set(av.AUTO_CAPABLE_KINDS) <= set(AGENT_AUTO)
