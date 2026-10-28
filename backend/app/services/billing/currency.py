"""Which currency an organization sees first, and what Servabo knows of its Indian tax identity (Final session 2A, N-187).

    default_currency(db, organization_id)   "INR" or "USD"
    billing_country(db, organization_id)    "IN" when Servabo knows the organization buys from India, else None
    known_gstin(db, organization_id)        the organization's own GSTIN when Servabo knows it, else None

Rule 7 of N-187: an organization whose billing country is India sees rupees by default; when no billing country is known,
an organization whose oldest workspace is in India's time zone sees rupees; everyone else sees dollars. Anyone can switch
on the billing page; this only picks the first view.

Servabo stores no billing address of its own (Dodo, the merchant of record, holds it), so "billing country is India" is
read from what Servabo does hold (N-192): a GSTIN as the billing account's tax id, or a past checkout in rupees
(`checkout_selections`, which only Indian checkouts can produce). An organization already paying in dollars keeps
dollars. The usage price book's currency (`billing_accounts.currency`, F7) is a different thing and is not touched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.workspace import Workspace

INR = "INR"
USD = "USD"
INDIA = "IN"
#: The IANA names of India's time zone (Asia/Calcutta is the old alias).
INDIA_ZONES = frozenset({"Asia/Kolkata", "Asia/Calcutta"})
#: Indian card and UPI e-mandates (RBI): an automatic payment above ₹15,000 needs the customer's approval each time, and
#: Dodo registers a mandate for the larger of this floor and the first charge (docs.dodopayments.com,
#: features/payment-methods/india, read through search extracts on 2026-10-26). In paise.
MANDATE_FLOOR_PAISE = 1_500_000
#: GST Dodo adds on top of a rupee price, as merchant of record (percent).
GST_RATE_PERCENT = 18


def with_gst_paise(amount_paise: int) -> int:
    return (int(amount_paise) * (100 + GST_RATE_PERCENT) + 50) // 100


def above_mandate_floor(amount_paise: int) -> bool:
    """Whether a rupee charge (before GST) is above the mandate floor once GST is added."""
    return with_gst_paise(amount_paise) > MANDATE_FLOOR_PAISE


def _account(db: Session, organization_id: uuid.UUID):
    from app.services.billing import account_service

    return account_service.get_for_organization(db, organization_id=organization_id)


def _gstin(value: Optional[str]) -> Optional[str]:
    from app.services.gst.parse import gstin_ok

    if value and gstin_ok(value):
        return value.strip().upper()
    return None


def _last_checkout_currency(db: Session, organization_id: uuid.UUID) -> Optional[str]:
    row = db.execute(text("SELECT currency FROM checkout_selections WHERE organization_id = :o "
                          "ORDER BY created_at DESC LIMIT 1"), {"o": organization_id}).first()
    return str(row[0]) if row else None


def billing_country(db: Session, organization_id: uuid.UUID) -> Optional[str]:
    account = _account(db, organization_id)
    if account is not None and _gstin(account.tax_id):
        return INDIA
    if _last_checkout_currency(db, organization_id) == INR:
        return INDIA
    return None


def _oldest_workspace_zone(db: Session, organization_id: uuid.UUID) -> Optional[str]:
    return db.execute(
        select(Workspace.timezone)
        .where(Workspace.organization_id == organization_id, Workspace.is_sample.is_(False))
        .order_by(Workspace.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def default_currency(db: Session, organization_id: uuid.UUID) -> str:
    if billing_country(db, organization_id) == INDIA:
        return INR
    if _last_checkout_currency(db, organization_id) == USD:
        return USD
    return INR if _oldest_workspace_zone(db, organization_id) in INDIA_ZONES else USD


@dataclass(frozen=True)
class IndianBuyer:
    """A checkout in rupees (N-187 rule 8): the gateway is told the buyer is in India, in rupees, and must give a tax id
    (pre-filled with the organization's GSTIN when Servabo knows it), so UPI and RuPay are offered and the invoice can
    carry the buyer's GSTIN."""

    gstin: Optional[str] = None


def indian_buyer(db: Session, organization_id: uuid.UUID, currency: Optional[str]) -> Optional[IndianBuyer]:
    """The Indian checkout details for a checkout in `currency`; None for any other currency."""
    if currency != INR:
        return None
    return IndianBuyer(gstin=known_gstin(db, organization_id))


def billed_product_id(subscription) -> Optional[str]:
    """The product the gateway bills this subscription on now (Dodo is asked; it is the truth after any change)."""
    from app.services.billing.payment_gateway import get_payment_gateway

    if not subscription.gateway_subscription_id:
        return None
    snapshot = get_payment_gateway(subscription.gateway).fetch_subscription(subscription.gateway_subscription_id)
    return getattr(snapshot, "product_id", None) or None


def price_for_plan(db: Session, subscription, tier_key: str):
    """The price of plan `tier_key` in the currency and interval this subscription is billed in (F-627).

    A plan is sold in dollars and rupees, monthly and yearly, each its own gateway product. A plan change must keep the
    customer's currency and interval; before Final session 2A it always sent the plan's dollar monthly product. Raises
    LookupError when the plan is not sold that way here (its product is not configured)."""
    from app.services.revops import price_books

    current = price_books.price_of_product(db, billed_product_id(subscription))
    interval, currency = (current.interval, current.currency) if current is not None else ("month", USD)
    price = price_books.resolve_price(db, tier_key=tier_key, interval=interval, currency=currency)
    if price is None or not price.gateway_price_id:
        raise LookupError(f"The {tier_key} plan is not sold billed {interval}ly in {currency} here.")
    return price


def known_gstin(db: Session, organization_id: uuid.UUID) -> Optional[str]:
    """The billing account's tax id when it is a GSTIN, else the GSTIN of the organization's latest GSTR-2B import."""
    account = _account(db, organization_id)
    if account is not None and _gstin(account.tax_id):
        return _gstin(account.tax_id)
    row = db.execute(text(
        "SELECT r.gstin FROM gst_returns r JOIN workspaces w ON w.id = r.workspace_id "
        "WHERE w.organization_id = :o AND NOT w.is_sample ORDER BY r.created_at DESC LIMIT 1"),
        {"o": organization_id}).first()
    return _gstin(row[0]) if row else None


__all__ = ["GST_RATE_PERCENT", "INDIA", "INDIA_ZONES", "INR", "MANDATE_FLOOR_PAISE", "USD", "IndianBuyer",
           "above_mandate_floor", "billed_product_id", "price_for_plan", "with_gst_paise", "billing_country", "default_currency", "indian_buyer",
           "known_gstin"]
