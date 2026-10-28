"""What Dodo Payments keeps from each payment (website and payments session, C12).

Dodo's published pricing (dodopayments.com/pricing, read 2026-10-16; recorded in
docs/billing/DODO.md): 4% + 40 US cents per payment, plus 1.5% when the card or account is
international, plus 0.5% on subscription payments. As merchant of record Dodo also collects and
remits the tax, which is added on top of the price and is not a cost to Servabo.

Servabo's subscriptions are international by default (an Indian sole proprietor selling to
customers mostly abroad), so the planning figure is the worst usual case: 6% + 40 cents.
Chargebacks cost a further $30 each (`DISPUTE_FEE_MICROS`).

Final session 2A (N-187): rupee prices are paid by Indian customers with Indian cards and UPI, a domestic payment
for an Indian merchant: 4% + 15 US cents, plus 0.5% on subscriptions (dodopayments.com/pricing, as quoted by search
extracts on 2026-10-23 and 2026-10-26; the page itself could not be opened from the build sandbox, so Final session
2B confirms it, and whether the 1.5% international surcharge is ever added). `dodo_india_fee_micros` takes the
amount in US dollars at the planning rate `INR_PER_USD_PLANNING` (₹90, conservative: the market rate on 2026-10-26
was about ₹88), because Dodo states the fixed part in cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

BASE_RATE = Decimal("0.04")
FIXED_FEE_MICROS = 400_000  # 40 US cents
INTERNATIONAL_RATE = Decimal("0.015")
SUBSCRIPTION_RATE = Decimal("0.005")
DISPUTE_FEE_MICROS = 30_000_000  # $30 per chargeback
INDIA_FIXED_FEE_MICROS = 150_000  # 15 US cents, on a domestic Indian payment
#: The fixed rupee-to-dollar rate every margin check uses (N-187); deliberately weaker than the market rate.
INR_PER_USD_PLANNING = Decimal(90)


def dodo_fee_micros(amount_micros: int, *, international: bool = True, subscription: bool = True) -> int:
    """Dodo's fee on one payment of `amount_micros` (USD), in micros."""
    if amount_micros <= 0:
        return 0
    rate = BASE_RATE + (INTERNATIONAL_RATE if international else 0) + (SUBSCRIPTION_RATE if subscription else 0)
    variable = (Decimal(amount_micros) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(variable) + FIXED_FEE_MICROS


def dodo_india_fee_micros(amount_micros: int, *, subscription: bool = True) -> int:
    """Dodo's fee on one domestic Indian payment of `amount_micros` (in USD at the planning rate), in micros."""
    if amount_micros <= 0:
        return 0
    rate = BASE_RATE + (SUBSCRIPTION_RATE if subscription else 0)
    variable = (Decimal(amount_micros) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(variable) + INDIA_FIXED_FEE_MICROS


def inr_to_usd_micros(inr_micros: int) -> int:
    """Rupee micros to dollar micros at the planning rate (rounded half up)."""
    return int((Decimal(inr_micros) / INR_PER_USD_PLANNING).quantize(Decimal(1), rounding=ROUND_HALF_UP))


__all__ = ["BASE_RATE", "DISPUTE_FEE_MICROS", "FIXED_FEE_MICROS", "INDIA_FIXED_FEE_MICROS", "INR_PER_USD_PLANNING",
           "INTERNATIONAL_RATE", "SUBSCRIPTION_RATE", "dodo_fee_micros", "dodo_india_fee_micros", "inr_to_usd_micros"]
