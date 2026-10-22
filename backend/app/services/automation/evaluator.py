"""Session J — the condition evaluator: right answers, and the reason for each.

`evaluate(actual, operator, expected, field=..., ctx=...)` decides one condition and says why, in words, so a run's
trace can state each condition's actual value, the expected value and the result.

WHAT CHANGED, AND WHAT DID NOT
==============================
Unchanged, exactly: every string, list and array operator on the values the old evaluator read correctly. The
compatibility corpus (`tests/services/automation_compat_corpus.py`) holds 1,122 answers of the old code and requires
the same answers from this one.

Fixed:
  * NUMBERS. The old evaluator compared `float(actual)`, so `"1,18,000.00"`, `"₹ 1,18,000"`, `"INR 118,000.00"`,
    `"(1,200.00)"` and `"1.18.000,00"` never matched "greater than": the comparison returned False in silence. Numbers
    are now `Decimal`s read by `app.core.normalize` (`money_micros`, with its currency detection). A value that cannot
    be read does NOT match, and the reason says so ("total_amount 'TBD' is not a number").
  * MONEY. A `money` field is entered and shown in currency units. A trigger's micros (`variance_micros`) are turned
    into units by the field's declared `unit`, so a stored rule that still says `event.variance_micros` keeps its raw
    micros meaning. A condition may name a currency; an amount in another currency does not match and is never
    converted.
  * DATES. BEFORE, AFTER, ON_OR_BEFORE, ON_OR_AFTER, WITHIN_NEXT_DAYS, WITHIN_LAST_DAYS and OLDER_THAN_DAYS, read with
    the workspace's date format (`03/04/2026` is 3 April or 4 March) and with "today" in the workspace's time zone.
  * LISTS. `IN`, `NOT_IN`, `BETWEEN` and the array operators take a JSON list, so "Acme, Inc" is one value. A comma
    string still works, as it always did.

This module imports no model and no session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence

from app.core import normalize as nz
from app.core.display_format import format_amount_micros

VALUELESS = frozenset({"EXISTS", "IS_EMPTY", "IS_NOT_EMPTY"})
NUMERIC_COMPARISONS = frozenset({"GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL"})
DATE_COMPARISONS = frozenset({"BEFORE", "AFTER", "ON_OR_BEFORE", "ON_OR_AFTER"})
DATE_WINDOWS = frozenset({"WITHIN_NEXT_DAYS", "WITHIN_LAST_DAYS", "OLDER_THAN_DAYS"})
DATE_OPERATORS = DATE_COMPARISONS | DATE_WINDOWS
LIST_OPERATORS = frozenset({"IN", "NOT_IN", "BETWEEN", "ARRAY_CONTAINS_ANY", "ARRAY_CONTAINS_ALL"})
MICROS = Decimal(1_000_000)

#: (when it matched, when it did not): the words a trace uses.
PHRASES: dict[str, tuple[str, str]] = {
    "EQUALS": ("equals", "does not equal"),
    "NOT_EQUALS": ("does not equal", "equals"),
    "CONTAINS": ("contains", "does not contain"),
    "NOT_CONTAINS": ("does not contain", "contains"),
    "STARTS_WITH": ("starts with", "does not start with"),
    "ENDS_WITH": ("ends with", "does not end with"),
    "GREATER_THAN": ("is greater than", "is not greater than"),
    "LESS_THAN": ("is less than", "is not less than"),
    "GREATER_THAN_OR_EQUAL": ("is at least", "is below"),
    "LESS_THAN_OR_EQUAL": ("is at most", "is above"),
    "BETWEEN": ("is between", "is not between"),
    "IN": ("is one of", "is not one of"),
    "NOT_IN": ("is not one of", "is one of"),
    "ARRAY_CONTAINS_ANY": ("includes one of", "includes none of"),
    "ARRAY_CONTAINS_ALL": ("includes all of", "is missing some of"),
    "BEFORE": ("is before", "is not before"),
    "AFTER": ("is after", "is not after"),
    "ON_OR_BEFORE": ("is on or before", "is after"),
    "ON_OR_AFTER": ("is on or after", "is before"),
    "WITHIN_NEXT_DAYS": ("is within the next", "is not within the next"),
    "WITHIN_LAST_DAYS": ("is within the last", "is not within the last"),
    "OLDER_THAN_DAYS": ("is older than", "is not older than"),
    "EXISTS": ("has a value", "has no value"),
    "IS_EMPTY": ("is empty", "is not empty"),
    "IS_NOT_EMPTY": ("is not empty", "is empty"),
}


# --------------------------------------------------------------------------------------------------- the context


@dataclass(frozen=True)
class EvalContext:
    """What a condition needs to know about the workspace it runs in."""

    date_format: Optional[str] = None
    timezone: str = "UTC"
    #: The workspace's currency: what an amount with no currency of its own is taken to be in.
    currency: Optional[str] = None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def _zone(self) -> Any:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            return ZoneInfo(self.timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            return ZoneInfo("UTC")

    def local_date(self, moment: datetime) -> date:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(self._zone()).date()

    @property
    def today(self) -> date:
        return self.local_date(self.now)

    @classmethod
    def for_workspace(cls, workspace: Any, *, now: Optional[datetime] = None) -> "EvalContext":
        return cls(
            date_format=getattr(workspace, "date_format", None),
            timezone=getattr(workspace, "timezone", None) or "UTC",
            currency=(getattr(workspace, "currency", None) or None),
            now=now or datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class FieldInfo:
    """What the evaluator needs to know about the field a condition reads."""

    key: str
    label: str = ""
    type: str = "string"
    #: "micros": the stored value is millionths of a currency unit, the rule is written in units.
    unit: Optional[str] = None

    @property
    def name(self) -> str:
        return self.label or humanize(self.key)


def humanize(key: str) -> str:
    text = re.sub(r"[._]+", " ", key.replace("event.", "").replace("classification_details.", "")).strip()
    return text[:1].upper() + text[1:] if text else key


@dataclass(frozen=True)
class Outcome:
    matched: bool
    reason: str
    actual_text: str = ""
    expected_text: str = ""


# ------------------------------------------------------------------------------------------------------ masks

_SENSITIVE_KEYS = re.compile(
    r"(bank|account|iban|ifsc|pan\b|_pan|aadhaar|ssn|passport|password|secret|token|email|phone|mobile|address|udyam|irn|"
    r"candidate|degree|signature)",
    re.IGNORECASE,
)


def mask(key: str, text: str) -> str:
    """A value for a trace. Identifiers and personal details are masked; amounts, dates and words are shown."""
    value = str(text)
    if not value:
        return value
    if not _SENSITIVE_KEYS.search(key or ""):
        return value if len(value) <= 80 else value[:77] + "…"
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}…@{domain}"
    if re.search(r"address", key or "", re.IGNORECASE):
        return "(hidden)"
    digits = re.sub(r"\D", "", value)
    if len(value) <= 4:
        return "•" * len(value)
    if len(digits) >= len(value) - 2:  # an account or phone number: the last four
        return "•" * max(len(value) - 4, 2) + value[-4:]
    return value[:2] + "•" * min(max(len(value) - 3, 2), 12) + value[-1:]


# --------------------------------------------------------------------------------------------------- parsing


@dataclass(frozen=True)
class ParsedNumber:
    value: Optional[Decimal]
    error: str = ""
    #: A currency the text itself named (a symbol or a word), else None.
    currency: Optional[str] = None


#: ISO codes accepted as a marker around an amount ("CHF 1,200"), besides the symbols and words `normalize` knows.
_MARKER_CODES = frozenset(
    "INR USD EUR GBP JPY AUD CAD SGD AED CHF CNY HKD NZD SEK NOK DKK ZAR BRL KRW MXN THB MYR IDR PHP SAR QAR".split()
)


def known_currency(code: Any) -> Optional[str]:
    """An ISO code this product knows (never an invented three letters), or None. "inr", "Indian Rupees", "₹" -> "INR"."""
    resolved = nz.currency_code(str(code)) if code else None
    return resolved if resolved in _MARKER_CODES else None


def _is_currency_marker(letters: str) -> bool:
    """True when the text left around an amount's digits is only a currency: ₹, Rs., INR, US$, Indian Rupees."""
    squeezed = " ".join(letters.upper().split())
    if squeezed in _MARKER_CODES or squeezed.rstrip(".") in nz._CURRENCY_WORDS or squeezed in nz._CURRENCY_NAMES:
        return True
    return all(ch in nz._CURRENCY_SYMBOLS for ch in letters.replace(" ", "")) and bool(letters.strip())


def parse_number(raw: Any, *, currency_hint: Optional[str] = None) -> ParsedNumber:
    """`118000`, `"1,18,000.00"`, `"₹ 1,18,000"`, `"INR 118,000.00"`, `"(1,200.00)"`, `"1.18.000,00"` -> Decimal.

    The plain forms (what `float()` read) go through `Decimal` as they always did. Anything else is read by
    `normalize.money_micros`, and only when what is left around the digits is a currency: "Invoice 2231" is not 2231.
    """
    if isinstance(raw, bool):
        return ParsedNumber(Decimal(int(raw)))
    if isinstance(raw, (int, Decimal)):
        return ParsedNumber(Decimal(raw))
    if isinstance(raw, float):
        return ParsedNumber(Decimal(repr(raw))) if raw == raw and raw not in (float("inf"), float("-inf")) else ParsedNumber(None, "is not a finite number")
    if not isinstance(raw, str):
        return ParsedNumber(None, "is not a number")
    text = raw.strip()
    if not text:
        return ParsedNumber(None, "is empty")
    try:
        plain = Decimal(text)
        if plain.is_finite():
            return ParsedNumber(plain)
    except InvalidOperation:
        pass
    letters = re.sub(r"[\d.,()+\-]", "", text).strip()
    if letters and not _is_currency_marker(letters):
        return ParsedNumber(None, "is not a number")
    try:
        money = nz.money_micros(text, currency_hint=currency_hint)
    except nz.AmbiguousValue:
        return ParsedNumber(None, "could be read two ways (a decimal or a thousands group); give the amount a currency")
    except nz.NormalizationError:
        return ParsedNumber(None, "is not a number")
    detected = None if money.currency == "XXX" else money.currency
    return ParsedNumber(Decimal(money.micros) / MICROS, currency=detected if letters else None)


@dataclass(frozen=True)
class ParsedDate:
    value: Optional[date]
    error: str = ""


_TIME_PART = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def parse_date(raw: Any, ctx: EvalContext) -> ParsedDate:
    """A date off a document or an event, read with the workspace's date format. A moment is placed in the workspace's zone."""
    if isinstance(raw, datetime):
        return ParsedDate(ctx.local_date(raw))
    if isinstance(raw, date):
        return ParsedDate(raw)
    if not isinstance(raw, str) or not raw.strip():
        return ParsedDate(None, "is not a date")
    text = raw.strip()
    if _TIME_PART.match(text):
        try:
            return ParsedDate(ctx.local_date(datetime.fromisoformat(text.replace("Z", "+00:00"))))
        except ValueError:
            pass
    try:
        return ParsedDate(nz.parse_document_date(text, format_hint=ctx.date_format))
    except nz.AmbiguousValue:
        return ParsedDate(None, "reads as both day-first and month-first; set the workspace date format")
    except nz.NormalizationError:
        return ParsedDate(None, "is not a date")


def expected_items(expected: Any) -> list[str]:
    """A list value as stored (a JSON list), or a legacy comma string."""
    if isinstance(expected, (list, tuple)):
        return [str(item).strip() for item in expected if str(item).strip()]
    return [part.strip() for part in str(expected or "").split(",") if part.strip()]


def _plain(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value).strip()


def _amount_text(value: Decimal, currency: Optional[str]) -> str:
    return format_amount_micros(int((value * MICROS).to_integral_value()), currency)


# ------------------------------------------------------------------------------------------------- evaluate


def _done(
    matched: bool, info: FieldInfo, operator: str, actual_text: str, expected_text: str, *, tail: str = ""
) -> Outcome:
    phrase = PHRASES.get(operator, (operator.lower().replace("_", " "),) * 2)[0 if matched else 1]
    sentence = f"{info.name} ({actual_text}) {phrase} {expected_text}".rstrip() + (f" {tail}" if tail else "") + "."
    return Outcome(matched, sentence, actual_text, expected_text)


def _cannot(info: FieldInfo, actual: Any, problem: str, *, expected_side: bool = False) -> Outcome:
    shown = mask(info.key, _plain(actual))
    if expected_side:
        return Outcome(False, f"The value in the rule {problem}, so {info.name} could not be compared.", shown, "")
    return Outcome(False, f"{info.name} '{shown}' {problem}, so this condition could not match.", shown, "")


def evaluate(
    actual: Any,
    operator: str,
    expected: Any,
    *,
    field: Optional[FieldInfo] = None,
    ctx: Optional[EvalContext] = None,
    currency: Optional[str] = None,
    actual_currency: Optional[str] = None,
) -> Outcome:
    """Decide one condition. `expected` is the stored value: a string, a list, or None."""
    info = field or FieldInfo(key="value")
    ctx = ctx or EvalContext()
    op = (operator or "").upper().strip()
    expected_str = _plain(expected)

    if op == "EXISTS":
        return _done(actual is not None, info, op, "", "")
    actual_is_empty = (
        actual is None
        or str(actual).strip() == ""
        or (isinstance(actual, (list, dict, set)) and len(actual) == 0)
    )
    if op == "IS_EMPTY":
        return _done(actual_is_empty, info, op, "", "")
    if op == "IS_NOT_EMPTY":
        return _done(not actual_is_empty, info, op, "", "")

    if actual is None:
        matched = op in ("NOT_EQUALS", "NOT_CONTAINS", "NOT_IN")
        return Outcome(matched, f"{info.name} has no value, so this condition {'matched' if matched else 'could not match'}.", "", expected_str)

    if op in DATE_OPERATORS:
        return _date_operator(actual, op, expected, info, ctx)
    if op in NUMERIC_COMPARISONS or op == "BETWEEN":
        return _numeric_operator(actual, op, expected, info, ctx, currency, actual_currency)
    if op in ("EQUALS", "NOT_EQUALS") and info.type in ("money", "number"):
        numeric = _numeric_equality(actual, op, expected, info, ctx, currency, actual_currency)
        if numeric is not None:
            return numeric
    return _text_operator(actual, op, expected, info)


def _text_operator(actual: Any, op: str, expected: Any, info: FieldInfo) -> Outcome:
    """The string, list and array operators, answering exactly as the evaluator always did."""
    target = _plain(expected)
    shown_actual = mask(info.key, _plain(actual))
    shown_expected = target
    actual_str = str(actual).strip()
    actual_lower = actual_str.lower()
    target_lower = target.lower()

    if op in ("CONTAINS", "NOT_CONTAINS"):
        if isinstance(actual, (list, tuple, set)):
            contained = target_lower in [str(x).strip().lower() for x in actual]
        else:
            contained = target_lower in actual_lower
        matched = contained if op == "CONTAINS" else not contained
        return _done(matched, info, op, shown_actual, shown_expected)
    if op in ("EQUALS", "NOT_EQUALS"):
        same = actual_lower == target_lower
        return _done(same if op == "EQUALS" else not same, info, op, shown_actual, shown_expected)
    if op == "STARTS_WITH":
        return _done(actual_lower.startswith(target_lower), info, op, shown_actual, shown_expected)
    if op == "ENDS_WITH":
        return _done(actual_lower.endswith(target_lower), info, op, shown_actual, shown_expected)
    if op in ("IN", "NOT_IN"):
        wanted = [item.lower() for item in expected_items(expected)]
        if isinstance(actual, (list, tuple, set)):
            hit = any(str(x).strip().lower() in wanted for x in actual)
        else:
            hit = actual_lower in wanted
        shown_expected = ", ".join(expected_items(expected))
        return _done(hit if op == "IN" else not hit, info, op, shown_actual, shown_expected)
    if op in ("ARRAY_CONTAINS_ANY", "ARRAY_CONTAINS_ALL"):
        wanted_set = {item.lower() for item in expected_items(expected)}
        shown_expected = ", ".join(expected_items(expected))
        if not wanted_set or not isinstance(actual, (list, tuple, set)):
            return _done(False, info, op, shown_actual, shown_expected)
        have = {str(x).strip().lower() for x in actual}
        matched = bool(have & wanted_set) if op == "ARRAY_CONTAINS_ANY" else wanted_set.issubset(have)
        return _done(matched, info, op, shown_actual, shown_expected)
    return Outcome(False, f"The comparison {op or '(none)'} is not one this version knows, so it did not match.", shown_actual, shown_expected)


def _money_context(
    actual: Any, info: FieldInfo, ctx: EvalContext, currency: Optional[str], actual_currency: Optional[str]
) -> tuple[Optional[Decimal], Optional[str], Optional[str], str]:
    """(units, the currency it is in, the currency it was ASSUMED to be in, problem)."""
    hint = (actual_currency or currency or ctx.currency)
    parsed = parse_number(actual, currency_hint=hint)
    if parsed.value is None:
        return None, None, None, parsed.error
    units = parsed.value / MICROS if info.unit == "micros" else parsed.value
    named = parsed.currency or (nz.currency_code(actual_currency) if actual_currency else None)
    if named:
        return units, named, None, ""
    assumed = (ctx.currency or "").upper() or None
    return units, assumed, assumed, ""


def _numeric_operator(
    actual: Any, op: str, expected: Any, info: FieldInfo, ctx: EvalContext,
    currency: Optional[str], actual_currency: Optional[str],
) -> Outcome:
    wanted_currency = nz.currency_code(currency) if currency else None
    units, actual_ccy, assumed, problem = _money_context(actual, info, ctx, wanted_currency, actual_currency)
    if units is None:
        return _cannot(info, actual, problem)
    if wanted_currency and actual_ccy and wanted_currency != actual_ccy:
        text = _amount_text(units, actual_ccy)
        return Outcome(
            False,
            f"{info.name} ({text}) is in {actual_ccy}, the rule is in {wanted_currency}. Amounts in different currencies are never converted, so this did not match.",
            text, wanted_currency,
        )
    show_ccy = actual_ccy if (info.type == "money" or wanted_currency) else None
    actual_text = _amount_text(units, show_ccy) if show_ccy else _trim(units)
    tail = f"(no currency on the document; taken as {assumed})" if assumed and wanted_currency else ""

    if op == "BETWEEN":
        bounds = _between_bounds(expected, wanted_currency or actual_ccy)
        if bounds is None:
            return _cannot(info, expected, "does not give a low and a high number", expected_side=True)
        low, high = bounds
        if low is None or high is None:
            return _cannot(info, expected, "has a bound that is not a number", expected_side=True)
        shown = f"{_amount_text(low, show_ccy) if show_ccy else _trim(low)} and {_amount_text(high, show_ccy) if show_ccy else _trim(high)}"
        return _done(low <= units <= high, info, op, actual_text, shown, tail=tail)

    target = parse_number(_plain(expected), currency_hint=wanted_currency or actual_ccy)
    if target.value is None:
        return _cannot(info, expected, f"'{_plain(expected)}' {target.error}", expected_side=True)
    target_text = _amount_text(target.value, show_ccy) if show_ccy else _trim(target.value)
    compare = {
        "GREATER_THAN": units > target.value,
        "LESS_THAN": units < target.value,
        "GREATER_THAN_OR_EQUAL": units >= target.value,
        "LESS_THAN_OR_EQUAL": units <= target.value,
    }[op]
    return _done(compare, info, op, actual_text, target_text, tail=tail)


def split_between(expected: Any) -> list[str]:
    """The parts of a BETWEEN value: a list as stored, or a legacy string ("10,20", "10..20", "10 - 20", "10-20")."""
    if isinstance(expected, (list, tuple)):
        return [str(p).strip() for p in expected if str(p).strip()]
    normalised = _plain(expected).replace("..", ",").replace(" - ", ",")
    if "," not in normalised and "-" in normalised:
        split_at = normalised.find("-", 1)
        if split_at != -1:
            normalised = normalised[:split_at] + "," + normalised[split_at + 1:]
    return [p.strip() for p in normalised.split(",") if p.strip()]


def _between_bounds(expected: Any, currency_hint: Optional[str]) -> Optional[tuple[Optional[Decimal], Optional[Decimal]]]:
    parts = split_between(expected)
    if len(parts) != 2:
        return None
    low, high = parse_number(parts[0], currency_hint=currency_hint), parse_number(parts[1], currency_hint=currency_hint)
    return low.value, high.value


def _numeric_equality(
    actual: Any, op: str, expected: Any, info: FieldInfo, ctx: EvalContext,
    currency: Optional[str], actual_currency: Optional[str],
) -> Optional[Outcome]:
    """EQUALS on a number or money field compares the numbers (100 equals 100.00). None: fall back to text."""
    wanted_currency = nz.currency_code(currency) if currency else None
    units, actual_ccy, _assumed, _problem = _money_context(actual, info, ctx, wanted_currency, actual_currency)
    target = parse_number(_plain(expected), currency_hint=wanted_currency or actual_ccy)
    if units is None or target.value is None:
        return None
    if wanted_currency and actual_ccy and wanted_currency != actual_ccy:
        return Outcome(False, f"{info.name} is in {actual_ccy}, the rule is in {wanted_currency}; amounts are never converted.", "", wanted_currency)
    show_ccy = actual_ccy if info.type == "money" else None
    same = units == target.value
    return _done(same if op == "EQUALS" else not same, info, op,
                 _amount_text(units, show_ccy) if show_ccy else _trim(units),
                 _amount_text(target.value, show_ccy) if show_ccy else _trim(target.value))


def _trim(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if "." not in text else text.rstrip("0").rstrip(".")


def _date_operator(actual: Any, op: str, expected: Any, info: FieldInfo, ctx: EvalContext) -> Outcome:
    seen = parse_date(actual, ctx)
    if seen.value is None:
        return _cannot(info, actual, seen.error)
    day = seen.value
    shown_actual = day.isoformat()
    today = ctx.today
    if op in DATE_WINDOWS:
        try:
            days = int(Decimal(_plain(expected)))
        except (InvalidOperation, ValueError):
            return _cannot(info, expected, f"'{_plain(expected)}' is not a number of days", expected_side=True)
        if days < 0:
            return _cannot(info, expected, "is a negative number of days", expected_side=True)
        gap = (day - today).days
        if op == "WITHIN_NEXT_DAYS":
            matched = 0 <= gap <= days
            tail = f"(today is {today.isoformat()}; {gap} days away)" if gap >= 0 else f"(today is {today.isoformat()}; it was {-gap} days ago)"
        elif op == "WITHIN_LAST_DAYS":
            matched = 0 <= -gap <= days
            tail = f"(today is {today.isoformat()}; {-gap} days ago)" if gap <= 0 else f"(today is {today.isoformat()}; it is {gap} days away)"
        else:
            matched = (-gap) > days
            tail = f"(today is {today.isoformat()}; {-gap} days old)" if gap <= 0 else f"(today is {today.isoformat()}; it is {gap} days ahead)"
        return _done(matched, info, op, shown_actual, f"{days} days", tail=tail)
    target = parse_date(_plain(expected), ctx)
    if target.value is None:
        return _cannot(info, expected, f"'{_plain(expected)}' {target.error}", expected_side=True)
    other = target.value
    matched = {
        "BEFORE": day < other,
        "AFTER": day > other,
        "ON_OR_BEFORE": day <= other,
        "ON_OR_AFTER": day >= other,
    }[op]
    return _done(matched, info, op, shown_actual, other.isoformat())


__all__ = [
    "DATE_OPERATORS",
    "EvalContext",
    "FieldInfo",
    "LIST_OPERATORS",
    "Outcome",
    "VALUELESS",
    "evaluate",
    "expected_items",
    "humanize",
    "known_currency",
    "mask",
    "parse_date",
    "parse_number",
    "split_between",
]
