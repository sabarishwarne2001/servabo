"""Helm learns GST (Session F, Phase 4): the 180-day mandate, the hold-until-reported mandate, the Guard's "GST credit
secured" check and the Request action. Pure snapshots, no database."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.helm import planner
from app.services.helm import snapshot as snap
from app.services.helm import vocabulary as v
from app.services.helm.guard import Actor, GuardContext, SYSTEM, guard
from app.services.helm.mandates import base, registry
from tests.services.helm.test_guard import M, TODAY, action, mandate, payable
from tests.services.helm.test_library import candidates, drift, full_book

pytestmark = pytest.mark.no_db

ME = "27AAACM1234F1Z5"
SUPPLIER = "27AABCS5555K1Z7"


def gst_payable(n: int, *, age: int, gst: int = 18_000, status: str | None = None, imported: bool = True, **kw):
    """An open invoice that is `age` days old and carries `gst` rupees of GST."""
    base_kw = dict(invoice_date=TODAY - timedelta(days=age), due_date=TODAY + timedelta(days=30),
                   amount_micros=118_000 * M, gst_micros=gst * M, gst_status=status, gst_gstin=ME if status else None,
                   gst_supplier_gstin=SUPPLIER if status else None, gst_period_imported=imported and bool(status))
    base_kw.update(kw)
    return payable(n, **base_kw)


# --------------------------------------------------------------------------------------------- 180 days


def test_a_gst_invoice_has_a_deadline_180_days_from_its_date_and_others_have_none():
    assert gst_payable(1, age=40).gst_deadline == TODAY - timedelta(days=40) + timedelta(days=180)
    assert payable(2, invoice_date=TODAY - timedelta(days=40)).gst_deadline is None  # no GST printed
    assert gst_payable(3, age=40, invoice_date=None).gst_deadline is None


def test_the_mandate_reads_holding_drifting_and_breached():
    comfortable = full_book(payables=[gst_payable(1, age=40)])
    assert drift("gst_pay_within_180_days", comfortable).state == base.HOLDING
    near = full_book(payables=[gst_payable(1, age=165)])  # last day in 15 days, nothing planned
    assert drift("gst_pay_within_180_days", near).state == base.DRIFTING
    past = full_book(payables=[gst_payable(1, age=200)])
    result = drift("gst_pay_within_180_days", past)
    assert result.state == base.BREACHED and "added back" in result.detail and "interest may apply" in result.detail
    assert "calculate" not in result.detail.lower()  # it says interest may apply; it never works it out
    paid = full_book(payables=[gst_payable(1, age=200, settlement_state=v.SETTLEMENT_PAID)])
    assert drift("gst_pay_within_180_days", paid).state == base.HOLDING


def test_the_buffer_moves_the_deadline_earlier():
    s = full_book(payables=[gst_payable(1, age=150)])
    m = mandate("gst_pay_within_180_days", {"buffer_days": 20})
    terms = registry.template("gst_pay_within_180_days").optimizer(s, m)
    due, kind, why = terms.deadlines["p1"]
    assert due == TODAY - timedelta(days=150) + timedelta(days=160) and kind == "GST180" and "Section 16(2)" in why


def test_the_optimizer_treats_the_180_day_deadline_as_hard_and_the_earlier_deadline_wins():
    s = full_book(payables=[gst_payable(1, age=170, due_date=TODAY + timedelta(days=60)),
                            gst_payable(2, age=100, due_date=TODAY + timedelta(days=60), udyam_number="UDYAM-MH-12-0001234",
                                        msme_deadline=TODAY + timedelta(days=5))],
                  cash={"INR": snap.Cash(currency="INR", amount_micros=10_000_000 * M, as_of=TODAY,
                                         source=v.CASH_SOURCE_MANUAL, age_days=0)})
    composition = planner.compose(s, [mandate("pay_on_time", n=1), mandate("gst_pay_within_180_days", n=2),
                                      mandate("msme_pay_within_limit", n=3)])
    schedule = composition.solution.schedule
    assert schedule["p1"] is not None and schedule["p1"] <= TODAY + timedelta(days=10)  # day 180 is TODAY + 10
    assert schedule["p2"] is not None and schedule["p2"] <= TODAY + timedelta(days=5)   # MSMED Act is earlier than day 180
    pay = {p.candidate.promise_id: p.candidate for p in composition.proposals if p.candidate.kind == v.ACTION_SCHEDULE_PAYMENT}
    assert pay["p1"].mandate.template == "gst_pay_within_180_days" and "deadline" in pay["p1"].explanation
    assert pay["p2"].mandate.template == "msme_pay_within_limit"


def test_when_cash_cannot_cover_everything_the_law_deadlines_are_kept_and_the_company_rule_gives_way():
    s = full_book(payables=[gst_payable(1, age=172, amount_micros=100_000 * M),
                            payable(2, amount_micros=100_000 * M, due_date=TODAY + timedelta(days=3))],
                  cash={"INR": snap.Cash(currency="INR", amount_micros=120_000 * M, as_of=TODAY,
                                         source=v.CASH_SOURCE_MANUAL, age_days=0)})
    composition = planner.compose(s, [mandate("pay_on_time", {"hard": True}, n=1), mandate("gst_pay_within_180_days", n=2)])
    schedule = composition.solution.schedule
    assert schedule["p1"] is not None and schedule["p1"] <= TODAY + timedelta(days=8)  # the 180th day
    assert "pay_on_time hard deadlines" in (composition.solution.conflict.relaxed if composition.solution.conflict else [])


def test_a_payment_after_the_180th_day_needs_a_person():
    p = gst_payable(1, age=170)
    s = full_book(payables=[p])
    m = mandate("gst_pay_within_180_days")
    act = action(p, m=m)
    late = act.__class__(**{**act.__dict__, "run_date": TODAY + timedelta(days=30)})
    result = guard(late, s, [m], SYSTEM, GuardContext())
    check = next(c for c in result.checks if c.id == "limit:gst_pay_within_180_days")
    assert check.result == v.CHECK_APPROVAL and "after the 180th day" in check.detail
    ok = guard(act, s, [m], SYSTEM, GuardContext())
    assert next(c for c in ok.checks if c.id == "limit:gst_pay_within_180_days").result == v.CHECK_PASS


def test_the_backtest_finds_a_gst_invoice_paid_after_180_days():
    from types import SimpleNamespace

    paid_late = gst_payable(1, age=250, settlement_state=v.SETTLEMENT_PAID, paid_on=TODAY - timedelta(days=30))
    history = SimpleNamespace(snapshot=full_book(payables=[paid_late]), end=TODAY, within=lambda d: True)
    findings = registry.template("gst_pay_within_180_days").backtest(history, mandate("gst_pay_within_180_days"))
    assert len(findings) == 1 and findings[0].category == base.CATEGORY_GST_180 and findings[0].honesty == v.HONESTY_CONFIRMED
    assert "interest may apply" in findings[0].summary


# --------------------------------------------------------------------------------------------- Request


def test_a_supplier_whose_invoices_are_missing_from_gstr_2b_gets_one_request_a_month():
    s = full_book(payables=[gst_payable(1, age=40, status="WAITING_FOR_SUPPLIER"),
                            gst_payable(2, age=50, status="WAITING_FOR_SUPPLIER"),
                            gst_payable(3, age=30, status="MATCHED"),
                            gst_payable(4, age=45, status="WAITING_FOR_SUPPLIER", imported=False)])
    m, out = candidates("gst_pay_within_180_days", s)
    requests = [c for c in out if c.kind == v.ACTION_REQUEST_DOCUMENT]
    assert len(requests) == 1
    one = requests[0]
    assert one.params["topic"] == "GST_REPORTING" and one.params["supplier_gstin"] == SUPPLIER and one.params["gstin"] == ME
    assert one.params["invoices"] == ["INV-2", "INV-1"] and "Section 16(2)(aa)" in one.explanation
    assert registry.template("gst_pay_within_180_days").propose(s, mandate("gst_pay_within_180_days", {"ask_suppliers": False})) == []
    again = registry.template("gst_pay_within_180_days").propose(s, m)[0]
    assert again.idempotency_key == one.idempotency_key  # the same month, the same action: sent once


# --------------------------------------------------------------------------------------------- hold until reported


def test_an_unreported_invoice_is_held_and_a_reported_one_is_not():
    s = full_book(payables=[gst_payable(1, age=40, status="WAITING_FOR_SUPPLIER"), gst_payable(2, age=40, status="MATCHED"),
                            gst_payable(3, age=40, status="WAITING_FOR_SUPPLIER", imported=False)])
    m, out = candidates("gst_hold_until_reported", s)
    assert [(c.kind, c.promise_id, c.params["reason"]) for c in out] == [(v.ACTION_HOLD_PAYMENT, "p1", "GST_NOT_REPORTED")]
    assert drift("gst_hold_until_reported", s).state == base.DRIFTING


def test_the_threshold_keeps_small_invoices_out():
    small = gst_payable(1, age=40, status="WAITING_FOR_SUPPLIER", amount_micros=10_000 * M)
    large = gst_payable(2, age=40, status="WAITING_FOR_SUPPLIER", amount_micros=500_000 * M)
    s = full_book(payables=[small, large])
    m, out = candidates("gst_hold_until_reported", s, {"threshold": {"amount_micros": 50_000 * M, "currency": "INR"}})
    assert [c.promise_id for c in out] == ["p2"]


@pytest.mark.parametrize("deadline", ["180", "msme"])
def test_it_never_holds_an_invoice_past_a_legal_deadline_and_lists_the_follow_up_instead(deadline):
    extra = dict(age=40)
    if deadline == "180":
        extra = dict(age=175)  # day 180 is in 5 days: inside the 10 safety days
    else:
        extra["udyam_number"] = "UDYAM-MH-12-0001234"
        extra["msme_deadline"] = TODAY + timedelta(days=4)
    s = full_book(payables=[gst_payable(1, status="WAITING_FOR_SUPPLIER", **extra)])
    m, out = candidates("gst_hold_until_reported", s)
    assert out == []
    result = drift("gst_hold_until_reported", s)
    assert "paid on time" in result.detail.lower() and "follow-up" in result.detail
    risks = registry.template("gst_hold_until_reported").forecast(s, m, None)
    assert len(risks) == 1 and "pays it on time instead of holding it" in risks[0].summary and "report it in GSTR-1" in risks[0].summary
    assert registry.template("gst_hold_until_reported").optimizer(s, m).exclude == {}  # the plan pays it


def test_a_hold_is_released_when_the_deadline_nears_so_the_next_run_pays_it():
    held = gst_payable(1, age=175, status="WAITING_FOR_SUPPLIER", settlement_state=v.SETTLEMENT_HELD,
                       settlement_source=v.SOURCE_HELM, hold_code="GST_NOT_REPORTED", hold_reason="held")
    s = full_book(payables=[held])
    composition = planner.compose(s, [mandate("gst_hold_until_reported")])
    kinds = [(p.candidate.kind, p.candidate.promise_id) for p in composition.proposals]
    assert (v.ACTION_RELEASE_HOLD, "p1") in kinds
    still = gst_payable(2, age=40, status="WAITING_FOR_SUPPLIER", settlement_state=v.SETTLEMENT_HELD,
                        settlement_source=v.SOURCE_HELM, hold_code="GST_NOT_REPORTED")
    again = planner.compose(full_book(payables=[still]), [mandate("gst_hold_until_reported")])
    assert not [p for p in again.proposals if p.candidate.kind == v.ACTION_RELEASE_HOLD]
    reported = gst_payable(3, age=40, status="MATCHED", settlement_state=v.SETTLEMENT_HELD,
                           settlement_source=v.SOURCE_HELM, hold_code="GST_NOT_REPORTED")
    released = planner.compose(full_book(payables=[reported]), [mandate("gst_hold_until_reported")])
    assert [p.candidate.promise_id for p in released.proposals if p.candidate.kind == v.ACTION_RELEASE_HOLD] == ["p3"]


def test_the_hold_is_off_by_default_and_proposes_rather_than_acts():
    assert "gst_hold_until_reported" not in registry.recommended(None)
    assert "gst_pay_within_180_days" in registry.recommended(None)
    gallery = {c["key"]: c for c in registry.library()}
    assert gallery["gst_hold_until_reported"]["defaults"]["threshold"] is None
    assert gallery["gst_hold_until_reported"]["required"] == []
    assert gallery["gst_hold_until_reported"]["readback"]["sentence"].startswith("Hold the payment of an invoice")
    assert gallery["gst_pay_within_180_days"]["law_links"] and "chartered accountant" in gallery["gst_pay_within_180_days"]["disclaimer"]
    assert registry.parse_spec({"template": "gst_hold_until_reported", "kind": "limit", "params": {}}).autonomy.mode == v.AUTONOMY_PROPOSE


# --------------------------------------------------------------------------------------------- the Guard


def _gst(p):
    s = full_book(payables=[p])
    result = guard(action(p), s, [], SYSTEM, GuardContext())
    return next(c for c in result.checks if c.id == "gst")


def test_the_guard_passes_a_matched_invoice():
    for status in ("MATCHED", "MATCHED_WITH_DIFFERENCES"):
        check = _gst(gst_payable(1, age=40, status=status))
        assert check.result == v.CHECK_PASS and check.title == "GST credit secured"


def test_the_guard_asks_a_person_when_the_supplier_has_not_reported_and_returns_exist():
    check = _gst(gst_payable(1, age=40, status="WAITING_FOR_SUPPLIER"))
    assert check.result == v.CHECK_APPROVAL
    assert "Section 16(2)(aa)" in check.detail and "not tax advice" in check.detail


def test_the_guard_says_nothing_when_no_return_covers_the_invoice_or_it_carries_no_gst():
    assert _gst(gst_payable(1, age=40, status="WAITING_FOR_SUPPLIER", imported=False)).result == v.CHECK_SKIP
    assert _gst(gst_payable(2, age=40)).result == v.CHECK_SKIP  # no return imported at all
    no_gst = payable(3, invoice_date=TODAY - timedelta(days=40))
    assert _gst(no_gst).result == v.CHECK_SKIP and "no GST" in _gst(no_gst).detail
    assert _gst(gst_payable(4, age=40, status="NOT_IN_BOOKS")).result == v.CHECK_SKIP


def test_the_check_is_skipped_for_what_is_not_a_payment():
    p = gst_payable(1, age=40, status="WAITING_FOR_SUPPLIER")
    s = full_book(payables=[p])
    hold = action(p, kind=v.ACTION_HOLD_PAYMENT)
    result = guard(hold, s, [], SYSTEM, GuardContext())
    assert next(c for c in result.checks if c.id == "gst").result == v.CHECK_SKIP
