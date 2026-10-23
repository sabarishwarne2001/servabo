"""Final session 1 (1D, F-570): rupees are written in lakh grouping wherever the server writes them for a person.

The builder's sentences already said "₹12,50,000"; the run history's reasons, emails and notices said
"INR 1,250,000.00". One formatter now serves all of them.
"""

from __future__ import annotations

import pytest

from app.core.display_format import format_amount_micros

pytestmark = pytest.mark.no_db

MICROS = 1_000_000


@pytest.mark.parametrize(
    ("units", "currency", "expected"),
    [
        (1_250_000, "INR", "INR 12,50,000.00"),
        (118_000, "INR", "INR 1,18,000.00"),
        (1_000, "INR", "INR 1,000.00"),
        (999, "INR", "INR 999.00"),
        (12_34_56_789, "INR", "INR 12,34,56,789.00"),
        (1_250_000, "USD", "USD 1,250,000.00"),
        (1_250_000, "EUR", "EUR 1,250,000.00"),
        (1_250_000, None, "1,250,000.00"),
    ],
)
def test_amounts_are_grouped_the_way_their_currency_is_read(units, currency, expected):
    assert format_amount_micros(units * MICROS, currency) == expected


def test_negative_rupees_and_paise_keep_their_grouping():
    assert format_amount_micros(-1_250_000 * MICROS, "inr") == "INR -12,50,000.00"
    assert format_amount_micros(int(1234567.5 * MICROS), "INR") == "INR 12,34,567.50"


def test_a_run_history_reason_for_a_rupee_condition_uses_lakh_grouping():
    from app.services.automation import evaluator as ev

    field = ev.FieldInfo("total_amount", "Total amount", "money")
    outcome = ev.evaluate("1,250,000.00", "GREATER_THAN", "10000000", field=field, ctx=ev.EvalContext(currency="INR"), currency="INR")
    assert outcome.reason == "Total amount (INR 12,50,000.00) is not greater than INR 1,00,00,000.00 (no currency on the document; taken as INR)."


def test_the_formatter_is_the_one_the_notices_use():
    from app.core import display_format

    assert display_format.format_amount_micros(25_000_000_000, "INR") == "INR 25,000.00"
    assert display_format.format_amount_micros(2_500_000_000_000, "INR") == "INR 25,00,000.00"
