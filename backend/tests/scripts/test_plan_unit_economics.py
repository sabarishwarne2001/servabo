"""Every plan keeps a healthy gross margin even when used to its limits (campaign session 1).

    pytest tests/scripts/test_plan_unit_economics.py -q

The cost of one seat (one organization on Free) using every allowance to the full,
priced at the price book's own cost bases (`scripts/seed_price_book.py`, the figures
the margin service reports COGS from), against the plan's price per seat:

  * OCR pages at the self-hosted OCR cost basis;
  * input and output tokens at the cost basis of the model a new workspace runs
    (`AI_MODELS[GROQ][0]`, `openai/gpt-oss-120b`; campaign session 2);
  * storage at the object storage cost basis per GB-month;
  * embedding: every OCR page indexed at ~500 tokens.

A paid plan must keep at least 60% gross margin at its ceilings (typical use is far
below them), and a Free trial account must cost at most $1.00: it is an acquisition
cost, not a product. Changing a limit or a cost basis so that this no longer holds
needs a decision, not a quiet edit.

Final session 2A (N-187): a plan is sold in dollars and in rupees, monthly and yearly
(`seed_quota_tiers.PLAN_PRICES`), with ONE set of allowances. So every rule is checked
against EVERY published price, as a price per seat per month in dollars: a yearly price
is divided by twelve, a rupee price is converted at the fixed planning rate (₹90 to the
dollar, `payment_fees.INR_PER_USD_PLANNING`), and the fee is Dodo's for that payment
(international for dollars, the domestic Indian fee for rupees; a yearly payment's fee is
spread over its twelve months). The lowest price of each plan is therefore the binding one.
Free's ceiling rose from $0.25 to $1.00 with the 14-day trial of 100 documents (N-187).

The platform also serves a dearer model on its own keys (GPT-OSS 120B), so a seat whose
tokens all go to the dearest model it serves must still keep at least 50% (N-046). Premium
models (Gemini, Groq's Preview models) run on the organization's own key (N-054).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import byok_providers
from app.core.ai_models import AI_MODELS, PLATFORM_SERVED_MODELS
from app.schemas.ai_settings import AIProvider
from tests.security.plans import _price_book_seed, _seed

#: Tokens written to the embedding index per OCR page (a page of text).
EMBEDDING_TOKENS_PER_PAGE = 500
MIN_PAID_GROSS_MARGIN = Decimal("0.60")
MIN_PAID_GROSS_MARGIN_DEAREST_MODEL = Decimal("0.50")
MAX_FREE_MONTHLY_COST_USD = Decimal("1.00")  # N-187 (was $0.25 for the 7-day trial)


def _cost_basis(event_type: str, provider: str, model: str | None = None) -> Decimal:
    for row in _price_book_seed().PLACEHOLDER_ENTRIES:
        if (
            row["event_type"] == event_type
            and row.get("provider") == provider
            and row.get("model") == model
            and row.get("tier_key") is None
            and row.get("cost_basis_micros") is not None
        ):
            return Decimal(str(row["cost_basis_micros"]))
    raise AssertionError(f"no cost basis for {event_type} / {provider} / {model}")


def _quantity(entries: dict, key: str) -> Decimal:
    row = entries.get(key)
    return Decimal(str(row["max_quantity"])) if row and row.get("max_quantity") is not None else Decimal(0)


def _dearest_platform_cost(event_type: str) -> Decimal:
    """The highest cost basis among the models the platform pays for.

    Campaign session 2 (N-054): the platform's own keys serve only PLATFORM_SERVED_MODELS (a
    call with any other model runs on the organization's key or is answered by the platform
    default, `tests/services/test_platform_served_models.py`). Before, every model of a
    provider whose key the platform holds counted, and at the suppliers' real prices
    (`test_price_book_matches_supplier_rates.py`) Gemini 2.5 Pro made an Enterprise seat cost
    $2,223 a month: exactly why those models moved to the customer's key.
    """
    served = [
        (provider, model)
        for provider, models in PLATFORM_SERVED_MODELS.items()
        for model in models
        if byok_providers.platform_key_for(provider) is not None
    ]
    assert served, "the platform serves no model on its own keys"
    return max(_cost_basis(event_type, provider, model) for provider, model in served)


def cost_at_ceilings_usd(plan: str, *, dearest_model: bool = False) -> Decimal:
    entries = {row["limit_key"]: row for row in _seed().PLACEHOLDER_TIERS[plan]["entries"]}
    pages = _quantity(entries, "ocr.page")
    if dearest_model:
        input_cost = _dearest_platform_cost("llm.input_token")
        output_cost = _dearest_platform_cost("llm.output_token")
    else:
        # Campaign session 2: the model a new workspace actually runs (the primary default,
        # `AI_MODELS[GROQ][0]`, GPT-OSS 120B since commit 233a3c0), not the cheaper 20B
        # this test assumed.
        default_model = AI_MODELS[AIProvider.GROQ][0]
        input_cost = _cost_basis("llm.input_token", "groq", default_model)
        output_cost = _cost_basis("llm.output_token", "groq", default_model)
    micros = (
        pages * _cost_basis("ocr.page", "paddleocr")
        + _quantity(entries, "llm.input_token") * input_cost
        + _quantity(entries, "llm.output_token") * output_cost
        + _quantity(entries, "storage.gb_month") * _cost_basis("storage.gb_month", "internal")
        + pages * EMBEDDING_TOKENS_PER_PAGE * _cost_basis("embedding.token", "sentence_transformers")
    )
    return micros / Decimal(1_000_000)


#: Every price a paid plan is published at (N-187), one test case each.
PRICES = [pytest.param(p, id=f"{p['tier']}-{p['currency']}-{p['interval']}") for p in _seed().PLAN_PRICES]
MONTHS = {"month": 1, "year": 12}


def monthly_price_usd(price: dict) -> Decimal:
    """What one seat pays a month at this price, in dollars (rupees at the planning rate)."""
    from app.core.payment_fees import inr_to_usd_micros

    micros = int(price["unit_amount_micros"])
    if price["currency"] == "INR":
        micros = inr_to_usd_micros(micros)
    return Decimal(micros) / Decimal(1_000_000) / MONTHS[price["interval"]]


def monthly_fee_usd(price: dict) -> Decimal:
    """Dodo's fee on one seat's payment at this price, spread over the months it pays for, in dollars."""
    from app.core.payment_fees import dodo_fee_micros, dodo_india_fee_micros, inr_to_usd_micros

    micros = int(price["unit_amount_micros"])
    if price["currency"] == "INR":
        fee = dodo_india_fee_micros(inr_to_usd_micros(micros), subscription=True)
    else:
        fee = dodo_fee_micros(micros, international=True, subscription=True)
    return Decimal(fee) / Decimal(1_000_000) / MONTHS[price["interval"]]


def test_every_paid_plan_is_published_in_both_currencies() -> None:
    """N-187: dollars for the world and rupees for India; a plan missing a currency would go unchecked here."""
    by_plan: dict[str, set[str]] = {}
    for price in _seed().PLAN_PRICES:
        by_plan.setdefault(price["tier"], set()).add(price["currency"])
    assert by_plan == {"developer": {"USD", "INR"}, "business": {"USD", "INR"}, "enterprise": {"USD", "INR"}}


@pytest.mark.parametrize("price", PRICES)
def test_a_paid_seat_used_to_its_limits_keeps_a_healthy_margin(price: dict) -> None:
    monthly = monthly_price_usd(price)
    cost = cost_at_ceilings_usd(price["tier"])
    margin = (monthly - cost) / monthly
    assert margin >= MIN_PAID_GROSS_MARGIN, (
        f"{price['tier']} {price['currency']} {price['interval']}: ${cost:.2f} of cost at the ceilings against "
        f"${monthly:.2f} per seat per month is a {margin:.0%} gross margin (under {MIN_PAID_GROSS_MARGIN:.0%})"
    )


@pytest.mark.parametrize("price", PRICES)
def test_a_paid_seat_on_the_dearest_platform_model_still_keeps_half(price: dict) -> None:
    monthly = monthly_price_usd(price)
    cost = cost_at_ceilings_usd(price["tier"], dearest_model=True)
    margin = (monthly - cost) / monthly
    assert margin >= MIN_PAID_GROSS_MARGIN_DEAREST_MODEL, (
        f"{price['tier']} {price['currency']} {price['interval']}: ${cost:.2f} of cost at the ceilings on the dearest "
        f"platform model against ${monthly:.2f} per seat per month is a {margin:.0%} gross margin "
        f"(under {MIN_PAID_GROSS_MARGIN_DEAREST_MODEL:.0%})"
    )


def test_free_costs_little_even_used_to_its_limits() -> None:
    cost = cost_at_ceilings_usd("free")
    assert cost <= MAX_FREE_MONTHLY_COST_USD, f"a Free trial account costs ${cost:.2f} at its limits"


# ---------------------------------------------------------------------------
# Website and payments session (C12): after Dodo Payments' fees.
# ---------------------------------------------------------------------------

#: Every paid price keeps at least this gross margin at its ceilings after Dodo's fees, for one seat (the dearest
#: case: the fixed part of the fee weighs most on a single seat). If one does not, trim the allowance (never the
#: price) and record why.
MIN_PAID_GROSS_MARGIN_AFTER_FEES = Decimal("0.55")
#: Typical use, for the report in docs/hardening/COSTS.md: a fifth of each allowance.
TYPICAL_SHARE = Decimal("0.2")


@pytest.mark.parametrize("price", PRICES)
def test_a_paid_seat_keeps_55_percent_at_its_ceilings_after_dodo_fees(price: dict) -> None:
    monthly = monthly_price_usd(price)
    fee = monthly_fee_usd(price)
    cost = cost_at_ceilings_usd(price["tier"])
    margin = (monthly - cost - fee) / monthly
    assert margin >= MIN_PAID_GROSS_MARGIN_AFTER_FEES, (
        f"{price['tier']} {price['currency']} {price['interval']}: ${cost:.2f} of cost at the ceilings and "
        f"${fee:.2f} of Dodo fees against ${monthly:.2f} per seat per month is a {margin:.0%} gross margin "
        f"(under {MIN_PAID_GROSS_MARGIN_AFTER_FEES:.0%})"
    )


def test_dodo_fees_are_the_published_schedule() -> None:
    from app.core.payment_fees import dodo_fee_micros, dodo_india_fee_micros, inr_to_usd_micros

    # $49: 4% + 1.5% + 0.5% = $2.94, plus $0.40.
    assert dodo_fee_micros(49_000_000) == 3_340_000
    # A domestic one-off payment: 4% + $0.40.
    assert dodo_fee_micros(100_000_000, international=False, subscription=False) == 4_400_000
    assert dodo_fee_micros(0) == 0
    # N-187: an Indian subscription payment: 4% + 0.5% + 15 cents. ₹1,499 at ₹90 is $16.655556.
    assert inr_to_usd_micros(1_499_000_000) == 16_655_556
    assert dodo_india_fee_micros(16_655_556) == 899_500
    assert dodo_india_fee_micros(0) == 0


SYMBOL = {"USD": "$", "INR": "₹"}
PLAN_NAMES = {"developer": "Starter", "business": "Business", "enterprise": "Enterprise"}


def _amount(price: dict) -> str:
    major = Decimal(int(price["unit_amount_micros"])) / Decimal(1_000_000)
    return f"{SYMBOL[price['currency']]}{major:,.0f} a {price['interval']}"


def unit_economics_report() -> list[dict]:
    """Per published price: per seat per month in dollars, Dodo's fee, cost and margin (COSTS.md §5)."""
    rows = []
    for price in _seed().PLAN_PRICES:
        monthly, fee = monthly_price_usd(price), monthly_fee_usd(price)
        ceiling = cost_at_ceilings_usd(price["tier"])
        typical = ceiling * TYPICAL_SHARE
        rows.append({
            "plan": PLAN_NAMES[price["tier"]], "price": _amount(price), "monthly": monthly, "fee": fee,
            "cost_at_ceilings": ceiling,
            "margin_at_ceilings": (monthly - ceiling - fee) / monthly,
            "margin_typical": (monthly - typical - fee) / monthly,
        })
    return rows


def test_the_report_in_costs_md_is_current() -> None:
    """docs/hardening/COSTS.md §5 shows these figures; regenerate them when a price, limit or fee moves."""
    from pathlib import Path

    costs = (Path(__file__).resolve().parents[3] / "docs/hardening/COSTS.md").read_text(encoding="utf-8")
    for row in unit_economics_report():
        line = (f"| {row['plan']} | {row['price']} | ${row['monthly']:.2f} | ${row['fee']:.2f} | "
                f"${row['cost_at_ceilings']:.2f} | {row['margin_at_ceilings']:.0%} | {row['margin_typical']:.0%} |")
        assert line in costs, line
