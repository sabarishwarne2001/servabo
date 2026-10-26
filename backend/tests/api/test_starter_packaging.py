"""Starter's packaging (Final session 2A, N-187).

* "Developer" is shown as **Starter** (the key stays `developer`).
* Custom domains are included in Business and Enterprise, not in Starter, and sold to nobody: a Starter organization is
  refused with the upgrade moment naming Business; the $199 add-on is retired.
* The Tally Prime import file is included in Starter (closes N-174), without ERP posting: Starter can set up Tally and
  download its file, and is refused any other ERP target with the upgrade moment naming Business.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.api import capability_gate
from app.core import entitlements
from app.core.billing_errors import CapabilityRequiredError
from app.services.billing import addon_service, entitlement_service
from tests.security.plans import _seed, put_on_plan


def _grants(plan: str) -> set[str]:
    return {row["limit_key"] for row in _seed().PLACEHOLDER_TIERS[plan]["entries"]}


def test_the_developer_key_is_shown_as_starter() -> None:
    assert _seed().PLACEHOLDER_TIERS["developer"]["display_name"] == "Starter"


def test_custom_domains_are_on_business_and_enterprise_only() -> None:
    assert entitlements.CUSTOM_DOMAIN_ADDON not in _grants("free")
    assert entitlements.CUSTOM_DOMAIN_ADDON not in _grants("developer")
    assert entitlements.CUSTOM_DOMAIN_ADDON in _grants("business")
    assert entitlements.CUSTOM_DOMAIN_ADDON in _grants("enterprise")


def test_the_custom_domain_add_on_is_sold_to_nobody() -> None:
    offer = entitlement_service.offer_for(entitlements.CUSTOM_DOMAIN_ADDON)
    assert offer.prices == () and not offer.sold
    assert not entitlement_service.purchasable(entitlements.CUSTOM_DOMAIN_ADDON)


def test_the_tally_file_is_on_starter_and_up_and_erp_posting_is_not() -> None:
    assert entitlements.TALLY_FILE_CAPABILITY not in _grants("free")
    for plan in ("developer", "business", "enterprise"):
        assert entitlements.TALLY_FILE_CAPABILITY in _grants(plan), plan
    assert entitlements.ERP_POSTING_CAPABILITY not in _grants("developer")


def test_a_starter_custom_domain_is_refused_naming_business(db_session: Session, tenant) -> None:
    for plan in ("free", "developer", "business", "enterprise"):
        put_on_plan(db_session, tenant.organization, plan)
    put_on_plan(db_session, tenant.organization, "developer")
    access = entitlement_service.addon_access(db_session, organization_id=tenant.organization.id,
                                              addon_key=entitlements.CUSTOM_DOMAIN_ADDON)
    assert access.state == entitlement_service.STATE_NOT_GRANTED
    assert entitlement_service.tiers_including(db_session, entitlements.CUSTOM_DOMAIN_ADDON) == ["Business", "Enterprise"]
    with pytest.raises(addon_service.AddonNotOfferedError) as raised:
        addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id,
                                            addon_key=entitlements.CUSTOM_DOMAIN_ADDON)
    assert "included in Business and Enterprise" in str(raised.value)


def test_free_has_no_tally_file(db_session: Session, tenant) -> None:
    for plan in ("free", "developer", "business", "enterprise"):
        put_on_plan(db_session, tenant.organization, plan)
    put_on_plan(db_session, tenant.organization, "free")
    with pytest.raises(CapabilityRequiredError):
        capability_gate.require_capability_for_organization(
            db_session, organization_id=tenant.organization.id, actor_id=None,
            capability_key=entitlements.TALLY_FILE_CAPABILITY, operation="test", audit=False)
