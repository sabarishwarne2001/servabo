"""GST Credit as an add-on for Developer customers (Session H).

Business and Enterprise include GST Credit through their plan (`capability.gst_credit`). A Developer organization
can buy it as the third add-on: $49 a month for the organization, one gateway subscription, recorded on the same
ledger as custom domains and warehouse sync. What it unlocks is exactly what the capability unlocks (the supplier
list, the invoice list with IMS recommendations, decisions, the export and the reminders). When it ends, the page
returns to the preview and every import, match and decision is kept.

    pytest tests/services/test_gst_addon.py -q
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import entitlements
from app.core.billing_errors import AddonRequiredError, CapabilityRequiredError
from app.core.config import settings
from app.models.gst import GstDecision, GstMatch, GstReturn
from app.models.organization import Organization
from app.models.organization_addon import ADDON_STATUS_ACTIVE, ADDON_STATUS_GRACE, ADDON_STATUS_LAPSED
from app.services.billing import addon_service, entitlement_service
from app.services.gst import gate, store
from tests.security.plans import put_on_plan
from tests.services.gst.helpers import statement
from tests.services.test_dodo_reconciliation import dodo  # noqa: F401 - the stand-in Dodo, as a fixture

GST = entitlements.GST_CREDIT_ADDON
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _context(tenant):
    return SimpleNamespace(organization_id=tenant.organization.id, user_id=tenant.owner.user.id)


def _purchase(db: Session, tenant, status: str, version: int, *, at=NOW, sub: str = "sub_gst_1"):
    addon_service.record_purchase_state(db, organization_id=tenant.organization.id, addon_key=GST, gateway="DODO",
                                        gateway_subscription_id=sub, gateway_status=status, state_version=version, now=at)
    return addon_service.reconcile_organization(db, organization_id=tenant.organization.id, now=at, only=GST)[0]


def _import(db: Session, tenant) -> None:
    store.import_file(db, workspace=tenant.workspace, user_id=tenant.owner.user.id, file_name="gstr2b.json",
                      data=statement())
    db.flush()


def _counts(db: Session, tenant) -> tuple[int, int]:
    return (db.execute(select(func.count()).select_from(GstReturn).where(GstReturn.workspace_id == tenant.workspace.id)).scalar_one(),
            db.execute(select(func.count()).select_from(GstMatch).where(GstMatch.workspace_id == tenant.workspace.id)).scalar_one())


# ------------------------------------------------------------------------------------------ the catalogue


def test_the_catalogue_and_the_vocabulary_agree_and_the_price_is_49_dollars() -> None:
    assert GST == "addon.gst_credit" and GST in entitlements.ADDON_KEYS
    assert set(entitlement_service.ADDON_CATALOG) == set(entitlements.ADDON_KEYS)
    offer = entitlement_service.offer_for(GST)
    assert (offer.display_name, offer.monthly_price_micros, offer.currency) == ("GST Credit", 49_000_000, "USD")
    assert offer.product_setting == "DODO_ADDON_PRODUCT_GST_CREDIT" and hasattr(settings, offer.product_setting)
    assert offer.sold_on_tiers == ("developer",)
    # The lapse text says what the customer keeps, in the words the notices use.
    assert "preview" in offer.halt_effect and "kept" in offer.halt_effect


def test_business_and_enterprise_include_it_through_the_plan_and_developer_does_not(db_session: Session, tenant) -> None:
    org = tenant.organization
    for plan, included in (("free", False), ("developer", False), ("business", True), ("enterprise", True)):
        put_on_plan(db_session, org, plan)
        access = entitlement_service.addon_access(db_session, organization_id=org.id, addon_key=GST)
        assert (access.state == entitlement_service.STATE_ACTIVE) is included, plan
        if included:
            assert access.source == "TIER"
    assert entitlement_service.tiers_including(db_session, GST) == ["Business", "Enterprise"]


# ------------------------------------------------------------------------------------------ the gate


def test_a_developer_organization_without_the_add_on_sees_the_preview(db_session: Session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "developer")
    _import(db_session, tenant)
    assert gate.full_access(db_session, tenant.workspace) is False
    with pytest.raises(AddonRequiredError) as refused:
        gate.require_full(db_session, tenant.workspace, _context(tenant), "gst.suppliers")
    details = refused.value.details
    assert details["addon_key"] == GST and details["addon_name"] == "GST Credit"
    assert "add-on" in str(refused.value) and "upgrade" in str(refused.value)  # both remedies are named
    # Having imported statements does not give an organization a grace period it never paid for.
    assert entitlement_service.addon_access(db_session, organization_id=tenant.organization.id, addon_key=GST).state == \
        entitlement_service.STATE_NOT_GRANTED
    assert addon_service.reconcile_organization(db_session, organization_id=tenant.organization.id, now=NOW,
                                                only=GST)[0]["status"] is None


def test_an_active_purchase_unlocks_everything_the_capability_unlocks(db_session: Session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "developer")
    assert _purchase(db_session, tenant, "active", 1)["status"] == ADDON_STATUS_ACTIVE
    assert gate.full_access(db_session, tenant.workspace) is True
    gate.require_full(db_session, tenant.workspace, _context(tenant), "gst.export")  # does not raise


def test_a_cancellation_gives_a_grace_period_then_the_preview_and_keeps_the_data(db_session: Session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "developer")
    _import(db_session, tenant)
    _purchase(db_session, tenant, "active", 1)
    decision = GstDecision(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id,
                           gstin="27AAACM1234F1Z5", supplier_gstin="27AABCS5555K1Z5", doc_key="INV1001",
                           kind="INVOICE", decision="NOT_OURS")
    db_session.add(decision)
    db_session.flush()
    kept = _counts(db_session, tenant)
    assert kept[0] >= 1 and kept[1] >= 1

    grace = _purchase(db_session, tenant, "cancelled", 2, at=NOW + timedelta(days=1))
    assert grace["status"] == ADDON_STATUS_GRACE  # the statements are what a lapse would affect
    assert gate.full_access(db_session, tenant.workspace) is True  # still full during grace

    later = NOW + timedelta(days=1) + entitlement_service.grace_period() + timedelta(minutes=1)
    lapsed = addon_service.reconcile_organization(db_session, organization_id=tenant.organization.id, now=later, only=GST)[0]
    assert lapsed["status"] == ADDON_STATUS_LAPSED
    row = entitlement_service.ledger_row(db_session, organization_id=tenant.organization.id, addon_key=GST)
    assert row.status == ADDON_STATUS_LAPSED
    assert gate.full_access(db_session, tenant.workspace) is False
    with pytest.raises(AddonRequiredError, match="has ended"):
        gate.require_full(db_session, tenant.workspace, _context(tenant), "gst.records")

    # Nothing was deleted: the imports, the matches and the decision are all still there.
    assert _counts(db_session, tenant) == kept
    assert db_session.get(GstDecision, decision.id) is not None

    # Buying it again brings everything back at once.
    _purchase(db_session, tenant, "active", 3, sub="sub_gst_2", at=later + timedelta(days=1))
    assert gate.full_access(db_session, tenant.workspace) is True


def test_business_is_full_without_any_add_on_row_and_free_is_the_preview(db_session: Session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "business")
    assert entitlement_service.ledger_row(db_session, organization_id=tenant.organization.id, addon_key=GST) is None
    assert gate.full_access(db_session, tenant.workspace) is True
    gate.require_full(db_session, tenant.workspace, _context(tenant), "gst.suppliers")

    put_on_plan(db_session, tenant.organization, "free")
    assert gate.full_access(db_session, tenant.workspace) is False
    with pytest.raises(CapabilityRequiredError):  # nothing to buy on the trial: choose a plan
        gate.require_full(db_session, tenant.workspace, _context(tenant), "gst.suppliers")


def test_the_sample_company_is_unchanged(db_session: Session, tenant) -> None:
    put_on_plan(db_session, tenant.organization, "developer")
    tenant.workspace.is_sample = True
    db_session.flush()
    assert gate.full_access(db_session, tenant.workspace) is True
    gate.require_full(db_session, tenant.workspace, _context(tenant), "gst.suppliers")


# ------------------------------------------------------------------------------------------ buying it


def test_a_developer_organization_can_check_out_through_the_stand_in(dodo, db_session: Session, tenant, monkeypatch) -> None:  # noqa: F811
    put_on_plan(db_session, tenant.organization, "developer")
    session = addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id, addon_key=GST)
    assert session.kind == "checkout" and session.url
    created = list(dodo.checkouts.values())[-1]  # what the stand-in was asked to sell
    assert created["product_id"] == settings.DODO_ADDON_PRODUCT_GST_CREDIT
    assert created["quantity"] == 1  # one per organization, not per seat
    assert created["metadata"]["addon_key"] == GST
    # With no addresses configured, the customer comes back to the organization's billing page (not a client's choice).
    slug = db_session.get(Organization, tenant.organization.id).slug
    assert created["return_url"] == f"{settings.FRONTEND_URL.rstrip('/')}/organizations/{slug}/billing?addon=success"


@pytest.mark.parametrize("plan", ["business", "enterprise"])
def test_checkout_is_refused_where_the_plan_already_includes_it(dodo, db_session: Session, tenant, plan) -> None:  # noqa: F811
    put_on_plan(db_session, tenant.organization, plan)
    with pytest.raises(addon_service.AddonAlreadyGrantedError, match="already included"):
        addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id, addon_key=GST)


def test_checkout_is_refused_on_the_trial_which_must_choose_a_plan_first(dodo, db_session: Session, tenant) -> None:  # noqa: F811
    put_on_plan(db_session, tenant.organization, "free")
    with pytest.raises(addon_service.AddonNotOfferedError, match="Developer"):
        addon_service.create_addon_checkout(db_session, organization_id=tenant.organization.id, addon_key=GST)
