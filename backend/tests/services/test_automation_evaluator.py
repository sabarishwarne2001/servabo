"""Session J, Phase 1 — conditions that are always right: operator x type x value tables.

Every row is `(id, actual, operator, value, kwargs, expected)`. `CASES` is a plain list so the same rows can be put to the
evaluator as it was before Session J (`scratch run against HEAD~`), which is how the defects were proven (F-535 to
F-538): numbers in grouped or currency-marked forms never matched, dates had no comparison, a comma split a value, and a
trigger's micros were typed as micros.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.services.automation import evaluator as ev

pytestmark = pytest.mark.no_db

# 2026-10-21 20:30 UTC is 2026-10-22 02:00 in Asia/Kolkata: "today" depends on the workspace's zone.
NOW = datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc)
IST_DDMM = ev.EvalContext(date_format="DD/MM/YYYY", timezone="Asia/Kolkata", currency="INR", now=NOW)
UTC_MMDD = ev.EvalContext(date_format="MM/DD/YYYY", timezone="UTC", currency="USD", now=NOW)
NO_FORMAT = ev.EvalContext(date_format=None, timezone="UTC", currency=None, now=NOW)

MONEY = ev.FieldInfo("total_amount", "Total amount", "money")
NUMBER = ev.FieldInfo("exception_count", "Exceptions", "number")
DATE = ev.FieldInfo("invoice_date", "Invoice date", "date")
MICROS = ev.FieldInfo("event.variance", "Variance", "money", unit="micros")
RAW_MICROS = ev.FieldInfo("event.variance_micros", "Variance (micros, old)", "number")
TEXT = ev.FieldInfo("vendor_name", "Supplier name", "string")


def row(case_id: str, actual: Any, op: str, value: Any, expected: bool, **kwargs: Any) -> tuple[str, Any, str, Any, dict[str, Any], bool]:
    return case_id, actual, op, value, kwargs, expected


CASES: list[tuple[str, Any, str, Any, dict[str, Any], bool]] = [
    # ---- numbers and money: every form a document or a model really gives (F-535)
    row("money-indian-grouping", "1,18,000.00", "GREATER_THAN", "100000", True, field=MONEY),
    row("money-plain-string", "118000", "GREATER_THAN", "100000", True, field=MONEY),
    row("money-rupee-symbol", "₹ 1,18,000", "GREATER_THAN", "100000", True, field=MONEY),
    row("money-inr-code", "INR 118,000.00", "GREATER_THAN", "100000", True, field=MONEY),
    row("money-rs-word", "Rs. 1,18,000", "GREATER_THAN", "100000", True, field=MONEY),
    row("money-eu-grouping", "1.18.000,00", "GREATER_THAN", "100000", True, field=MONEY),
    row("money-western-grouping", "1,180,000.50", "GREATER_THAN", "1000000", True, field=MONEY),
    row("money-int", 118000, "GREATER_THAN", "100000", True, field=MONEY),
    row("money-float", 118000.0, "GREATER_THAN", "100000", True, field=MONEY),
    row("money-decimal", Decimal("118000.00"), "GREATER_THAN", "100000", True, field=MONEY),
    row("money-accounting-negative-below", "(1,200.00)", "LESS_THAN", "0", True, field=MONEY),
    row("money-accounting-negative-not-above", "(1,200.00)", "GREATER_THAN", "100", False, field=MONEY),
    row("money-negative-greater", "(1,200.00)", "GREATER_THAN", "-5000", True, field=MONEY),
    row("money-value-typed-in-indian-grouping", "118000", "GREATER_THAN", "1,00,000", True, field=MONEY),
    row("money-gte-equal", "1,00,000", "GREATER_THAN_OR_EQUAL", "100000", True, field=MONEY),
    row("money-gt-equal-is-false", "1,00,000", "GREATER_THAN", "100000", False, field=MONEY),
    row("money-lte", "99,999.99", "LESS_THAN_OR_EQUAL", "100000", True, field=MONEY),
    row("money-lt", "1,18,000", "LESS_THAN", "100000", False, field=MONEY),
    row("money-not-a-number", "TBD", "GREATER_THAN", "100000", False, field=MONEY),
    row("money-sentence-is-not-a-number", "Invoice 2231", "GREATER_THAN", "5", False, field=MONEY),
    row("money-letters-around-digits", "12abc", "GREATER_THAN", "5", False, field=NUMBER),
    row("money-empty-string", "", "GREATER_THAN", "5", False, field=MONEY),
    row("money-missing", None, "GREATER_THAN", "5", False, field=MONEY),
    row("number-grouped-in-a-plain-field", "1,18,000.00", "GREATER_THAN", "100000", True),
    row("number-scientific-still-reads", "1e3", "EQUALS", "1000", False),
    row("number-equals-typed-compares-numbers", "100.00", "EQUALS", "100", True, field=NUMBER),
    row("number-equals-untyped-stays-text", "100.00", "EQUALS", "100", False),
    row("number-not-equals-typed", "100.00", "NOT_EQUALS", "100", False, field=NUMBER),
    row("money-between-list", "1,18,000", "BETWEEN", ["100000", "200000"], True, field=MONEY),
    row("money-between-list-miss", "2,50,000", "BETWEEN", ["100000", "200000"], False, field=MONEY),
    row("money-between-string-range", "150000", "BETWEEN", "100000..200000", True, field=MONEY),
    row("money-between-bound-not-a-number", "150000", "BETWEEN", ["100000", "lots"], False, field=MONEY),
    row("money-between-one-bound", "150000", "BETWEEN", ["100000"], False, field=MONEY),
    # ---- the one reading that cannot be decided is refused, not guessed
    row("money-ambiguous-no-currency", "1.234", "GREATER_THAN", "1000", False, field=MONEY, ctx=NO_FORMAT),
    row("money-single-comma-group-with-currency", "1,234", "GREATER_THAN", "1000", True, field=MONEY, ctx=IST_DDMM),
    # ---- currency: named by the rule, never converted (F-535)
    row("currency-same-in-the-text", "₹ 1,18,000", "GREATER_THAN", "100000", True, field=MONEY, currency="INR"),
    row("currency-other-in-the-text", "$1,200", "GREATER_THAN", "100", False, field=MONEY, currency="INR"),
    row("currency-other-by-field", "118000", "GREATER_THAN", "100000", False, field=MONEY, currency="INR", actual_currency="USD"),
    row("currency-same-by-field", "118000", "GREATER_THAN", "100000", True, field=MONEY, currency="INR", actual_currency="INR"),
    row("currency-document-says-name-in-words", "118000", "GREATER_THAN", "100000", True, field=MONEY, currency="INR", actual_currency="Indian Rupees"),
    row("currency-none-on-the-document-takes-the-workspace-currency", "118000", "GREATER_THAN", "100000", True, field=MONEY, currency="INR", ctx=IST_DDMM),
    row("currency-workspace-is-another-currency", "118000", "GREATER_THAN", "100000", False, field=MONEY, currency="INR", ctx=UTC_MMDD),
    row("currency-not-named-by-the-rule-compares-the-numbers", "$1,200", "GREATER_THAN", "100", True, field=MONEY),
    # ---- a trigger's micros are shown and entered in currency units (F-536)
    row("micros-over-in-units", 12_500_000, "GREATER_THAN", "10", True, field=MICROS),
    row("micros-not-over-in-units", 12_500_000, "GREATER_THAN", "20", False, field=MICROS),
    row("micros-between-in-units", 12_500_000, "BETWEEN", ["10", "15"], True, field=MICROS),
    row("micros-with-decimals", 12_500_000, "GREATER_THAN_OR_EQUAL", "12.5", True, field=MICROS),
    row("micros-old-field-keeps-its-raw-meaning", 12_500_000, "GREATER_THAN", "10000000", True, field=RAW_MICROS),
    row("micros-old-field-not-reinterpreted", 12_500_000, "GREATER_THAN", "20000000", False, field=RAW_MICROS),
    # ---- dates (F-536): comparisons, windows, the workspace's format and zone
    row("date-older-than-yes", "2026-05-01", "OLDER_THAN_DAYS", "150", True, field=DATE, ctx=IST_DDMM),
    row("date-older-than-no", "2026-06-01", "OLDER_THAN_DAYS", "150", False, field=DATE, ctx=IST_DDMM),
    row("date-older-than-exactly-is-not-older", "2026-05-24", "OLDER_THAN_DAYS", "151", False, field=DATE, ctx=IST_DDMM),
    row("date-within-next-in", "2026-11-10", "WITHIN_NEXT_DAYS", "30", True, field=DATE, ctx=IST_DDMM),
    row("date-within-next-too-far", "2026-12-01", "WITHIN_NEXT_DAYS", "30", False, field=DATE, ctx=IST_DDMM),
    row("date-within-next-already-past", "2026-10-01", "WITHIN_NEXT_DAYS", "30", False, field=DATE, ctx=IST_DDMM),
    row("date-within-next-today", "2026-10-22", "WITHIN_NEXT_DAYS", "0", True, field=DATE, ctx=IST_DDMM),
    row("date-within-last-in", "2026-10-18", "WITHIN_LAST_DAYS", "7", True, field=DATE, ctx=IST_DDMM),
    row("date-within-last-too-old", "2026-10-01", "WITHIN_LAST_DAYS", "7", False, field=DATE, ctx=IST_DDMM),
    row("date-within-last-in-the-future", "2026-10-30", "WITHIN_LAST_DAYS", "7", False, field=DATE, ctx=IST_DDMM),
    row("date-before", "2026-10-01", "BEFORE", "2026-10-31", True, field=DATE, ctx=IST_DDMM),
    row("date-before-same-day", "2026-10-31", "BEFORE", "2026-10-31", False, field=DATE, ctx=IST_DDMM),
    row("date-on-or-before-same-day", "2026-10-31", "ON_OR_BEFORE", "2026-10-31", True, field=DATE, ctx=IST_DDMM),
    row("date-after", "2026-11-02", "AFTER", "2026-10-31", True, field=DATE, ctx=IST_DDMM),
    row("date-on-or-after", "2026-10-31", "ON_OR_AFTER", "2026-10-31", True, field=DATE, ctx=IST_DDMM),
    row("date-day-first-workspace", "03/04/2026", "AFTER", "2026-03-31", True, field=DATE, ctx=IST_DDMM),
    row("date-month-first-workspace", "03/04/2026", "AFTER", "2026-03-31", False, field=DATE, ctx=UTC_MMDD),
    row("date-unambiguous-ignores-the-format", "25/12/2026", "AFTER", "2026-12-01", True, field=DATE, ctx=UTC_MMDD),
    row("date-ambiguous-without-a-format", "03/04/2026", "AFTER", "2026-03-31", False, field=DATE, ctx=NO_FORMAT),
    row("date-text-month", "3 April 2026", "BEFORE", "2026-04-04", True, field=DATE, ctx=NO_FORMAT),
    row("date-not-a-date", "soon", "BEFORE", "2026-04-04", False, field=DATE, ctx=IST_DDMM),
    row("date-missing", None, "BEFORE", "2026-04-04", False, field=DATE, ctx=IST_DDMM),
    row("date-timestamp-in-the-workspace-zone", "2026-10-21T20:30:00+00:00", "ON_OR_AFTER", "2026-10-22", True, field=DATE, ctx=IST_DDMM),
    row("date-timestamp-in-utc-zone", "2026-10-21T20:30:00+00:00", "ON_OR_AFTER", "2026-10-22", False, field=DATE, ctx=UTC_MMDD),
    row("date-days-value-not-a-number", "2026-10-01", "OLDER_THAN_DAYS", "many", False, field=DATE, ctx=IST_DDMM),
    row("date-days-value-negative", "2026-10-01", "OLDER_THAN_DAYS", "-3", False, field=DATE, ctx=IST_DDMM),
    # ---- lists are lists: a comma inside a value is part of the value (F-537)
    row("list-in-a-value-with-a-comma", "Acme, Inc", "IN", ["Acme, Inc", "Beta"], True),
    row("list-in-comma-string-splits-as-before", "Acme, Inc", "IN", "Acme, Inc", False),
    row("list-in-comma-string-reads-as-before", "beta", "IN", "Acme,Beta", True),
    row("list-not-in-with-a-comma", "Acme, Inc", "NOT_IN", ["Acme, Inc"], False),
    row("list-not-in-miss", "Gamma", "NOT_IN", ["Acme, Inc", "Beta"], True),
    row("list-in-case-and-space", " BETA ", "IN", [" beta "], True),
    row("list-in-with-an-actual-list", ["x", "Beta"], "IN", ["Beta"], True),
    row("list-array-any", ["a", "b"], "ARRAY_CONTAINS_ANY", ["b", "z"], True),
    row("list-array-all", ["a", "b"], "ARRAY_CONTAINS_ALL", ["a", "b"], True),
    row("list-array-all-miss", ["a"], "ARRAY_CONTAINS_ALL", ["a", "b"], False),
    row("list-array-item-with-a-comma", ["Acme, Inc"], "ARRAY_CONTAINS_ANY", ["Acme, Inc"], True),
    row("list-empty-list-value", "a", "IN", [], False),
    # ---- fixed values and booleans
    row("option-equals", "HIGH", "EQUALS", "high", True),
    row("boolean-equals", True, "EQUALS", "true", True),
    row("boolean-not-equals", False, "NOT_EQUALS", "true", True),
    # ---- the plain text operators are unchanged
    row("text-contains", "Acme Supplies", "CONTAINS", "supplies", True, field=TEXT),
    row("text-starts-with", "Acme Supplies", "STARTS_WITH", "acme", True, field=TEXT),
    row("text-ends-with", "Acme Supplies", "ENDS_WITH", "ltd", False, field=TEXT),
    row("valueless-exists", "x", "EXISTS", "", True),
    row("valueless-is-empty", "  ", "IS_EMPTY", "", True),
    row("valueless-is-not-empty", [], "IS_NOT_EMPTY", "", False),
]


def decide(actual: Any, op: str, value: Any, kwargs: dict[str, Any]) -> ev.Outcome:
    params = dict(kwargs)
    ctx = params.pop("ctx", IST_DDMM if "field" in params and params["field"] in (DATE, MONEY, MICROS) else None)
    return ev.evaluate(actual, op, value, ctx=ctx, **params)


@pytest.mark.parametrize("case_id,actual,op,value,kwargs,expected", CASES, ids=[c[0] for c in CASES])
def test_condition_table(case_id: str, actual: Any, op: str, value: Any, kwargs: dict[str, Any], expected: bool) -> None:
    outcome = decide(actual, op, value, kwargs)
    assert outcome.matched is expected, f"{case_id}: {outcome.reason}"
    assert outcome.reason.endswith("."), "every verdict comes with a reason in words"


# ---- the trace says why, in words, and masks what is sensitive -------------------------------------------------


def test_a_value_that_cannot_be_read_says_so() -> None:
    outcome = ev.evaluate("TBD", "GREATER_THAN", "100000", field=MONEY, ctx=IST_DDMM)
    assert outcome.matched is False
    assert "Total amount 'TBD' is not a number" in outcome.reason


def test_the_trace_states_actual_expected_and_result() -> None:
    outcome = ev.evaluate("1,18,000.00", "GREATER_THAN", "1000000", field=MONEY, ctx=IST_DDMM, currency="INR")
    assert outcome.matched is False
    assert outcome.reason == (
        "Total amount (INR 118,000.00) is not greater than INR 1,000,000.00 (no currency on the document; taken as INR)."
    )
    assert outcome.actual_text == "INR 118,000.00" and outcome.expected_text == "INR 1,000,000.00"


def test_a_currency_mismatch_is_explained_and_never_converted() -> None:
    outcome = ev.evaluate("$1,200", "GREATER_THAN", "100", field=MONEY, ctx=IST_DDMM, currency="INR")
    assert outcome.matched is False
    assert "never converted" in outcome.reason and "USD" in outcome.reason and "INR" in outcome.reason


def test_an_ambiguous_date_names_the_workspace_setting() -> None:
    outcome = ev.evaluate("03/04/2026", "AFTER", "2026-03-31", field=DATE, ctx=NO_FORMAT)
    assert "workspace date format" in outcome.reason


def test_a_window_states_today_in_the_workspaces_zone() -> None:
    outcome = ev.evaluate("2026-05-01", "OLDER_THAN_DAYS", "150", field=DATE, ctx=IST_DDMM)
    assert "today is 2026-10-22" in outcome.reason and "174 days old" in outcome.reason
    assert IST_DDMM.today.isoformat() == "2026-10-22" and UTC_MMDD.today.isoformat() == "2026-10-21"


@pytest.mark.parametrize(
    "key,value,hidden",
    [
        ("vendor_bank_account", "00112233445566", "00112233445566"),
        ("vendor_email", "accounts@acme.example", "accounts"),
        ("vendor_address", "12 MIDC, Pune 411019", "MIDC"),
        ("vendor_pan", "AAAAA0000A", "AAAAA0000A"),
        ("irn", "a" * 64, "a" * 64),
        ("candidate_name", "Jane Doe", "Jane Doe"),
    ],
)
def test_sensitive_values_are_masked_in_the_trace(key: str, value: str, hidden: str) -> None:
    info = ev.FieldInfo(key, key, "string")
    outcome = ev.evaluate(value, "EQUALS", "other", field=info)
    assert hidden not in outcome.reason and hidden not in outcome.actual_text


def test_amounts_dates_and_words_are_shown_in_the_trace() -> None:
    outcome = ev.evaluate("Acme Supplies", "EQUALS", "Other Ltd", field=TEXT)
    assert "Acme Supplies" in outcome.reason
    money = ev.evaluate("118000", "GREATER_THAN", "5", field=MONEY, ctx=IST_DDMM, currency="INR")
    assert "118,000.00" in money.reason


def test_parse_number_reads_every_form() -> None:
    for text, expected in [("1,18,000.00", "118000"), ("₹ 1,18,000", "118000"), ("INR 118,000.00", "118000"),
                           ("(1,200.00)", "-1200"), ("1.18.000,00", "118000"), (" 42 ", "42"), ("-7.5", "-7.5")]:
        parsed = ev.parse_number(text, currency_hint="INR")
        assert parsed.value == Decimal(expected), text
    assert ev.parse_number("TBD").value is None
    assert ev.parse_number("nan").value is None
    assert ev.parse_number(float("inf")).value is None
