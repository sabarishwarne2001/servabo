"""Final session 1 (3B): every locked feature is a sales moment, and this one test walks all of them on the server's side.

The browser half (the dialog, the banner, the roles) is `frontend/src/components/billing/upgradeMoments.test.tsx`. This half is what
the server must say for those screens to be right:

  * every capability has a display name, is carried by at least one published plan (a lock that no plan unlocks leads nowhere),
    and its 402 names exactly the plans that carry it, from the published tiers;
  * every add-on has a catalogue price and a product, is either sold on some plan or included in one, is offered on exactly the
    plans it is sold on, and its checkout sells THAT add-on's product (never another's);
  * a plan that already includes it, or that does not sell it, is refused a checkout in words that name the remedy.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.api import capability_gate
from app.core import entitlements
from app.core.billing_errors import CapabilityRequiredError
from app.core.config import settings
from app.services.billing import addon_service, entitlement_service
from tests.security.plans import put_on_plan
from tests.services.test_dodo_reconciliation import dodo  # noqa: F401 - the stand-in Dodo, as a fixture

PLANS = ("free", "developer", "business", "enterprise")


def _publish_all(db: Session, tenant) -> None:
    for plan in PLANS:
        put_on_plan(db, tenant.organization, plan)
    db.flush()


def _carrying(db: Session, key: str) -> list[str]:
    return capability_gate.plans_including(db)[key]


def test_every_capability_has_a_name_and_a_plan_that_unlocks_it(db_session: Session, tenant) -> None:
    _publish_all(db_session, tenant)
    no_name = [k for k in entitlements.CAPABILITY_KEYS if k not in capability_gate._DISPLAY_NAMES]  # noqa: SLF001
    assert not no_name, f"capabilities that would show their key to a customer: {no_name}"
    orphans = [k for k in entitlements.CAPABILITY_KEYS if not _carrying(db_session, k)]
    assert not orphans, f"capabilities no published plan carries (a lock that leads nowhere): {orphans}"


@pytest.mark.parametrize("key", entitlements.CAPABILITY_KEYS)
def test_the_refusal_for_a_capability_names_the_plans_that_carry_it(db_session: Session, tenant, key: str) -> None:
    _publish_all(db_session, tenant)
    carrying = _carrying(db_session, key)
    lacking = [p for p in PLANS if not any(p == name.lower() for name in carrying)]
    if not lacking:
        pytest.skip("every published plan carries it")
    put_on_plan(db_session, tenant.organization, lacking[0])
    with pytest.raises(CapabilityRequiredError) as raised:
        capability_gate.require_capability_for_organization(
            db_session, organization_id=tenant.organization.id, actor_id=None, capability_key=key, operation="walk", audit=False)
    error = raised.value
    assert error.details["included_in"] == carrying
    assert error.details["capability_name"] != key and error.details["remedy"] == "PLAN_UPGRADE"
    for name in carrying:
        assert name in str(error), f"{key}: the refusal does not name {name}: {error}"
    assert "higher plans" not in str(error)


@pytest.mark.parametrize("key", entitlements.ADDON_KEYS)
def test_every_addon_has_a_price_a_product_and_a_way_to_get_it(db_session: Session, tenant, key: str) -> None:
    _publish_all(db_session, tenant)
    offer = entitlement_service.offer_for(key)
    assert offer.monthly_price_micros > 0 and offer.currency == "USD" and offer.display_name
    assert hasattr(settings, offer.product_setting), f"{key}: {offer.product_setting} is not a setting"
    sold_on = entitlement_service.sold_on(db_session, key)
    included = entitlement_service.tiers_including(db_session, key)
    assert sold_on is not None
    on_sale_somewhere = [p for p in PLANS if _offered(db_session, tenant, key, p)]
    assert on_sale_somewhere or included, f"{key}: not sold on any plan and included in none: a lock that leads nowhere"
    if offer.sold_on_tiers:
        assert set(on_sale_somewhere) == set(offer.sold_on_tiers), (key, on_sale_somewhere, offer.sold_on_tiers)


def _offered(db: Session, tenant, key: str, plan: str) -> bool:
    put_on_plan(db, tenant.organization, plan)
    return entitlement_service.offered_on_plan(db, organization_id=tenant.organization.id, addon_key=key)


@pytest.mark.parametrize("key", entitlements.ADDON_KEYS)
def test_the_checkout_sells_that_addons_product_and_nothing_else(dodo, db_session: Session, tenant, key: str) -> None:  # noqa: F811
    _publish_all(db_session, tenant)
    offer = entitlement_service.offer_for(key)
    plan = next((p for p in PLANS if _offered(db_session, tenant, key, p) and not _included(db_session, key, p)), None)
    if plan is None:
        pytest.skip("not for sale on any plan that lacks it")
    put_on_plan(db_session, tenant.organization, plan)
    session = addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id, addon_key=key)
    assert session.kind == "checkout" and session.url
    created = list(dodo.checkouts.values())[-1]
    assert created["product_id"] == getattr(settings, offer.product_setting)
    assert created["metadata"]["addon_key"] == key


def _included(db: Session, key: str, plan: str) -> bool:
    return any(plan == name.lower() for name in entitlement_service.tiers_including(db, key))


@pytest.mark.parametrize("key", entitlements.ADDON_KEYS)
def test_a_plan_that_includes_the_addon_is_not_sold_it_again(dodo, db_session: Session, tenant, key: str) -> None:  # noqa: F811
    _publish_all(db_session, tenant)
    for plan in PLANS:
        if not _included(db_session, key, plan):
            continue
        put_on_plan(db_session, tenant.organization, plan)
        with pytest.raises(addon_service.AddonAlreadyGrantedError, match="already included"):
            addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id, addon_key=key)


def test_a_plan_the_addon_is_not_sold_on_is_told_which_plan_sells_it(dodo, db_session: Session, tenant) -> None:  # noqa: F811
    _publish_all(db_session, tenant)
    put_on_plan(db_session, tenant.organization, "free")
    with pytest.raises(addon_service.AddonNotOfferedError, match="Developer"):
        addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id, addon_key=entitlements.GST_CREDIT_ADDON)
