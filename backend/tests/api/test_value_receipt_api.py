"""GET /organizations/{org}/value-receipt (Session G): who may read it, what it returns, how long it is kept.

Real routes, Postgres and Redis. The figures themselves are proven in tests/services/test_value_receipt.py; here a
single planted GST credit and a few usage events prove the wiring.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.organization import OrganizationRole
from app.models.usage_event import UsageEvent
from app.services import value_receipt as vr
from tests.conftest import _make_user, _seat
from tests.security.plans import put_on_plan
from tests.services.test_value_receipt import _gst_book, _usage

API = "/api/v1"
M = 1_000_000


def url(tenant, query: str = "") -> str:
    return f"{API}/organizations/{tenant.organization.id}/value-receipt{query}"


@pytest.fixture()
def world(db_session, tenant):
    org = tenant.organization
    put_on_plan(db_session, org, "business")   # publishes the tiers the receipt compares
    put_on_plan(db_session, org, "free")
    org.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=2)
    vr.forget(org.id)
    for _ in range(3):
        _usage(db_session, org.id, tenant.workspace.id, "document.upload", 1, datetime.now(timezone.utc) - timedelta(hours=3))
    _gst_book(db_session, tenant, tenant.workspace, "W-1", 1000, "WAITING_FOR_SUPPLIER")
    billing = _make_user(db_session, f"billing-{uuid.uuid4().hex[:6]}@acme.com")
    _seat(db_session, org, billing, OrganizationRole.BILLING)
    db_session.commit()
    yield tenant, billing
    vr.forget(org.id)


def test_owners_admins_and_billing_read_it(client, world):
    tenant, billing = world
    for who in (tenant.owner, tenant.org_admin, billing):
        response = client.get(url(tenant), headers=who.headers)
        assert response.status_code == 200, who.user.email
        body = response.json()
        assert body["period"] == "trial" and body["work"]["documents"] == 3
        assert [f["key"] for f in body["found"]] == ["gst_waiting"]
        assert body["found"][0]["amount_text"] == "₹180"
        assert body["headline"] == "In your trial Servabo read 3 documents and found ₹180 of GST credit waiting on 1 supplier."
        assert body["also_on_business"] == ["Payment risks", "Prices checked against purchase orders",
                                            "Helm's full planning", "GST's supplier list"]


def test_members_strangers_and_visitors_do_not(client, world):
    tenant, _billing = world
    for who in (tenant.contributor, tenant.viewer, tenant.ws_admin):      # organization members
        assert client.get(url(tenant), headers=who.headers).status_code == 403, who.user.email
    assert client.get(url(tenant), headers=tenant.non_member.headers).status_code in (403, 404)
    assert client.get(url(tenant), headers=tenant.other_org_member.headers).status_code in (403, 404)
    assert client.get(url(tenant)).status_code in (401, 403)


def test_the_month_is_asked_for_by_name_and_an_unknown_period_is_refused(client, world):
    tenant, _billing = world
    month = client.get(url(tenant, "?period=month"), headers=tenant.owner.headers)
    assert month.status_code == 200 and month.json()["period"] == "month"
    assert month.json()["headline"].startswith("This month Servabo")
    assert client.get(url(tenant, "?period=year"), headers=tenant.owner.headers).status_code == 422


def test_it_is_kept_for_ten_minutes_per_organization_and_period(client, db_session, world):
    tenant, _billing = world
    assert vr.CACHE_SECONDS == 600
    first = client.get(url(tenant), headers=tenant.owner.headers).json()
    _usage(db_session, tenant.organization.id, tenant.workspace.id, "document.upload", 10, datetime.now(timezone.utc))
    db_session.commit()
    assert client.get(url(tenant), headers=tenant.owner.headers).json() == first            # kept
    month = client.get(url(tenant, "?period=month"), headers=tenant.owner.headers).json()
    assert month["work"]["documents"] == 13                                                  # another key, fresh
    vr.forget(tenant.organization.id)
    assert client.get(url(tenant), headers=tenant.owner.headers).json()["work"]["documents"] == 13


def test_the_kept_copy_expires_in_redis(client, world):
    from app.core.redis_client import get_redis_client

    tenant, _billing = world
    client.get(url(tenant), headers=tenant.owner.headers)
    redis = get_redis_client()
    if redis is None:
        pytest.skip("no Redis in this environment")
    ttl = redis.ttl(vr._cache_key(tenant.organization.id, "trial"))
    assert 0 < ttl <= 600


def test_another_organizations_owner_cannot_read_ours(client, world):
    tenant, _billing = world
    other_url = f"{API}/organizations/{tenant.organization.id}/value-receipt"
    assert client.get(other_url, headers=tenant.other_org_member.headers).status_code in (403, 404)
