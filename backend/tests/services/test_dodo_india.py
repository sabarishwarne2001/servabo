"""Rupee and yearly subscriptions on Dodo (Final session 2A, N-187).

A plan is sold in dollars and rupees, monthly and yearly; each is its own Dodo product. A seat change or a plan change
must keep the customer on the product family they bought (currency and interval). Before, both always sent the plan's
dollar monthly product (`quota_tiers.gateway_price_id`), so a rupee or yearly subscriber who added a seat would have
been moved to dollar monthly billing (F-627).

A checkout in rupees is an Indian business purchase: Dodo is told the currency, the country and that a tax id is
required, pre-filled with the organization's GSTIN when Servabo knows it (N-187 rule 8).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.security import create_access_token
from app.services.billing import currency as currency_service
from tests.services.test_dodo_reconciliation import (  # noqa: F401 - fixtures
    BUSINESS_PRICE,
    DEVELOPER_PRICE,
    deliver,
    dodo,
    org,
    row,
    subscribe,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import seed_quota_tiers as seed  # noqa: E402

BUSINESS_INR, DEVELOPER_INR = 499_900, 149_900  # paise
INR_PRODUCTS = {
    "GATEWAY_PRICE_ID_DEVELOPER": "pdt_developer",
    "GATEWAY_PRICE_ID_BUSINESS": "pdt_business",
    "GATEWAY_PRICE_ID_DEVELOPER_INR": "pdt_developer_inr",
    "GATEWAY_PRICE_ID_BUSINESS_INR": "pdt_business_inr",
    "GATEWAY_PRICE_ID_BUSINESS_YEARLY": "pdt_business_year",
}


@pytest.fixture()
def rupees(dodo, db, org):
    """The rupee products at the stand-in Dodo and the books that sell them, as the seed publishes them."""
    dodo.add_product(name="Starter (INR)", price=DEVELOPER_INR, currency="INR", product_id="pdt_developer_inr")
    dodo.add_product(name="Business (INR)", price=BUSINESS_INR, currency="INR", product_id="pdt_business_inr")
    dodo.add_product(name="Business (yearly)", price=BUSINESS_PRICE * 10, interval="Year",
                     product_id="pdt_business_year")
    books = seed.publish_price_books(db, environ=INR_PRODUCTS)
    assert set(books) == {"USD", "INR"}
    db.flush()
    return dodo


def _owner(org) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=org['owner'].id)}"}


def _seat_writes(dodo, sub_id: str) -> list[dict]:
    return [body for method, path, body in dodo.calls
            if method == "POST" and path == f"/subscriptions/{sub_id}/change-plan"]


def test_a_seat_change_keeps_a_rupee_subscriber_on_the_rupee_product(rupees, client, db, org) -> None:
    sub_id = subscribe(rupees, client, db, org, product="pdt_business_inr", seats=2)
    assert row(db, sub_id).quota_tier_key == "business"
    response = client.put(f"/api/v1/organizations/{org['organization'].id}/billing/seats",
                          json={"seats": 3}, headers=_owner(org))
    assert response.status_code == 200, response.text
    [write] = _seat_writes(rupees, sub_id)
    assert write["product_id"] == "pdt_business_inr", "a seat change must not move a rupee subscriber to dollars"
    assert write["quantity"] == 3


def test_a_seat_change_keeps_a_yearly_subscriber_on_the_yearly_product(rupees, client, db, org) -> None:
    sub_id = subscribe(rupees, client, db, org, product="pdt_business_year", seats=1)
    response = client.put(f"/api/v1/organizations/{org['organization'].id}/billing/seats",
                          json={"seats": 2}, headers=_owner(org))
    assert response.status_code == 200, response.text
    [write] = _seat_writes(rupees, sub_id)
    assert write["product_id"] == "pdt_business_year"


def test_an_upgrade_in_rupees_moves_to_the_higher_plans_rupee_product(rupees, client, db, org) -> None:
    sub_id = subscribe(rupees, client, db, org, product="pdt_developer_inr", seats=1)
    rupees.clock = lambda: datetime.now(timezone.utc) + timedelta(days=15)
    url = f"/api/v1/organizations/{org['organization'].id}/billing/plan-change"
    preview = client.post(f"{url}/preview", json={"quota_tier_key": "business", "seats": 1}, headers=_owner(org))
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    assert shown["currency"] == "INR"
    applied = client.post(url, json={"quota_tier_key": "business", "seats": 1,
                                     "expected_amount_micros": shown["amount_now_micros"]}, headers=_owner(org))
    assert applied.status_code == 200, applied.text
    [change] = _seat_writes(rupees, sub_id)
    assert change["product_id"] == "pdt_business_inr"
    deliver(rupees, client, db)
    assert row(db, sub_id).quota_tier_key == "business"


def test_a_rupee_checkout_is_an_indian_business_purchase(rupees, client, db, org) -> None:
    from app.models.billing_account import BillingAccount

    db.add(BillingAccount(organization_id=org["organization"].id, gateway="DODO", billing_email=org["owner"].email,
                          tax_id="27aapfu0939f1zv"))
    db.flush()
    response = client.post(f"/api/v1/organizations/{org['organization'].id}/billing/checkout-session",
                           json={"quota_tier_key": "business", "seats": 2, "interval": "month", "currency": "INR"},
                           headers=_owner(org))
    assert response.status_code == 201, response.text
    [body] = [b for method, path, b in rupees.calls if method == "POST" and path == "/checkouts"]
    assert body["product_cart"] == [{"product_id": "pdt_business_inr", "quantity": 2}]
    assert body["billing_currency"] == "INR"
    assert body["billing_address"] == {"country": "IN"}
    assert body["feature_flags"]["require_tax_id"] is True and body["feature_flags"]["allow_tax_id"] is True
    assert body["tax_id"] == "27AAPFU0939F1ZV"
    assert "mandate_min_amount_inr_paise" not in body, "N-192: Dodo's default ₹15,000 floor"


def test_a_dollar_checkout_says_nothing_about_india(rupees, client, db, org) -> None:
    response = client.post(f"/api/v1/organizations/{org['organization'].id}/billing/checkout-session",
                           json={"quota_tier_key": "business", "seats": 1, "interval": "month", "currency": "USD"},
                           headers=_owner(org))
    assert response.status_code == 201, response.text
    [body] = [b for method, path, b in rupees.calls if method == "POST" and path == "/checkouts"]
    assert "billing_currency" not in body and "tax_id" not in body and "feature_flags" not in body


def test_an_indian_organization_sees_rupees_first(db, org) -> None:
    from app.models.workspace import Workspace, WorkspaceStatus

    organization = org["organization"]
    assert currency_service.default_currency(db, organization.id) == "USD"
    db.add(Workspace(organization_id=organization.id, workspace_name="Pune", slug=f"pune-{organization.slug}",
                     status=WorkspaceStatus.ACTIVE, timezone="Asia/Kolkata"))
    db.flush()
    assert currency_service.default_currency(db, organization.id) == "INR"


def test_the_mandate_floor_counts_gst() -> None:
    # ₹12,711 before GST is ₹14,999 with it: inside the floor. ₹12,712 is ₹15,000.16: above it.
    assert not currency_service.above_mandate_floor(1_271_100)
    assert currency_service.above_mandate_floor(1_271_200)
    # Three Business users a month (₹14,997, ₹17,696 with GST) are above it; two Starter users are not.
    assert currency_service.above_mandate_floor(3 * BUSINESS_INR)
    assert not currency_service.above_mandate_floor(2 * DEVELOPER_INR)
