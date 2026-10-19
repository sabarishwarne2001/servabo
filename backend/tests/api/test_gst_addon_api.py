"""GST Credit as an add-on through the API: the price the page shows, who may start the checkout, and the plans
that are refused (Session H). The rules themselves are proven in tests/services/test_gst_addon.py."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import entitlements
from app.services.billing import entitlement_service
from tests.security.plans import put_on_plan
from tests.services.test_dodo_reconciliation import dodo  # noqa: F401 - the stand-in Dodo, as a fixture

GST = entitlements.GST_CREDIT_ADDON


def test_the_api_shows_the_catalogue_price_and_only_an_owner_can_start_a_checkout(client, db_session: Session, tenant, dodo) -> None:  # noqa: F811
    put_on_plan(db_session, tenant.organization, "developer")
    db_session.commit()
    base = f"/api/v1/organizations/{tenant.organization.id}"
    body = client.get(f"{base}/entitlements", headers=tenant.owner.headers).json()
    assert "addons" in body, body
    gst = next(a for a in body["addons"] if a["addon_key"] == GST)
    assert gst["monthly_price_micros"] == entitlement_service.offer_for(GST).monthly_price_micros == 49_000_000
    assert (gst["currency"], gst["state"], gst["purchasable"], gst["sold_on"]) == ("USD", "NOT_GRANTED", True, ["Developer"])

    url = f"{base}/billing/addons/{GST}/checkout-session"
    assert client.post(url, headers=tenant.contributor.headers).status_code == 403
    started = client.post(url, headers=tenant.owner.headers)
    assert started.status_code == 201, started.text
    assert started.json()["url"]

    put_on_plan(db_session, tenant.organization, "business")
    db_session.commit()
    refused = client.post(url, headers=tenant.owner.headers)
    assert refused.status_code == 409 and "already included" in refused.json()["detail"]
    after = client.get(f"{base}/entitlements", headers=tenant.owner.headers).json()
    assert next(a for a in after["addons"] if a["addon_key"] == GST)["state"] == "ACTIVE"
