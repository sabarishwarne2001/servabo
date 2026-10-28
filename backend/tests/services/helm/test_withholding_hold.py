"""TRINETRA's reviewed withholding and Helm's customer reminders (Final 2T, Phase 1.1).

Helm may chase the cash a customer still owes; it never chases the tax the customer withheld. When
nothing is left to chase in cash, or the amount withheld cannot be told, the reminder is a Guard block
with a plain reason, not a failed action. Pure snapshots, no database."""

from __future__ import annotations

import pytest

from app.services.helm import planner
from app.services.helm import vocabulary as v
from tests.services.helm.test_guard import M, mandate
from tests.services.helm.test_library import CUSTOMER, _receivable, full_book

pytestmark = pytest.mark.no_db

CASE = "11111111-1111-1111-1111-111111111111"


def _reminder(receivable, *, mode="act"):
    s = full_book(receivables=[receivable], counterparties=CUSTOMER)
    plan = planner.compose(s, [mandate("chase_overdue_customers", mode=mode)])
    found = [p for p in plan.proposals if p.candidate.kind == v.ACTION_SEND_REMINDER]
    return plan, found


def test_a_customer_who_still_owes_cash_is_reminded_for_the_net_amount():
    _, found = _reminder(_receivable(4, withheld_micros=2_000 * M, withholding_case_id=CASE))
    assert len(found) == 1
    candidate = found[0].candidate
    assert candidate.amount_micros == 148_000 * M  # 150,000 less 2,000 withheld as TDS
    assert candidate.params["withheld_micros"] == 2_000 * M
    assert "withheld" in candidate.explanation and "TDS" in candidate.explanation
    assert found[0].result.passed and found[0].result.can_run_alone


def test_nothing_left_in_cash_is_a_guard_block_with_a_plain_reason_not_a_failed_action():
    receivable = _receivable(4, withheld_micros=150_000 * M, withholding_case_id=CASE)
    _, found = _reminder(receivable)
    assert len(found) == 1
    result = found[0].result
    assert not result.passed
    check = next(c for c in result.checks if c.id == "withholding")
    assert check.result == v.CHECK_FAIL
    assert "held for withholding review" in check.title.lower()
    assert "TDS" in check.detail and "cash" in check.detail
    assert check.evidence["case_id"] == CASE


def test_a_confirmation_whose_evidence_went_stale_holds_the_reminder_until_it_is_reviewed():
    _, found = _reminder(_receivable(4, withholding_hold="UNKNOWN_AMOUNT", withholding_case_id=CASE))
    assert len(found) == 1 and not found[0].result.passed
    check = next(c for c in found[0].result.checks if c.id == "withholding")
    assert check.result == v.CHECK_FAIL and "evidence" in check.detail


def test_a_held_reminder_is_proposed_under_the_same_key_every_time_so_it_is_never_proposed_twice():
    receivable = _receivable(4, withheld_micros=150_000 * M, withholding_case_id=CASE)
    first = _reminder(receivable)[1][0].candidate.idempotency_key
    second = _reminder(receivable)[1][0].candidate.idempotency_key
    assert first == second


def test_an_invoice_with_no_withholding_is_reminded_exactly_as_before():
    _, found = _reminder(_receivable(4))
    assert found[0].candidate.amount_micros == 150_000 * M
    assert "withholding" not in {c.id for c in found[0].result.checks if c.result == v.CHECK_FAIL}
    assert "withheld_micros" not in found[0].candidate.params


def test_withheld_tax_changes_the_plan_digest_so_the_book_is_replanned():
    plain = full_book(receivables=[_receivable(4)], counterparties=CUSTOMER)
    withheld = full_book(receivables=[_receivable(4, withheld_micros=2_000 * M, withholding_case_id=CASE)],
                         counterparties=CUSTOMER)
    assert plain.digest != withheld.digest
