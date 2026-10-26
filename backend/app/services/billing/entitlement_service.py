"""ARCH-30 Tranche 2 (D-8) — may this organization use an add-on, answered once.

THE DEFECT THIS CLOSES
======================

`custom_domains.py` and `warehouse_sync.py` checked a ROLE and nothing else.
A Free organization's owner could claim `ai.acme.com`, have it verified,
receive a certificate, and register a Snowflake destination with a nightly
push — the two add-ons then priced at $199 and $300 a month, delivered for nothing,
because the only question either router asked was "is this person the owner".

THE TWO GRANT SOURCES
=====================

    TIER          the organization's resolved quota tier carries a
                  `quota_tier_entries` row keyed by the add-on. Enterprise v3
                  bundles both. Presence is the grant, exactly as
                  `llm.platform_key` works.
    SUBSCRIPTION  the add-on was bought as its own gateway subscription and
                  the ledger's `purchase_status` says it is paid for.

Both are read here and nowhere else. `addon_service` writes the ledger;
`app.api.addon_gate` refuses requests; the entitlements endpoint renders lock
cards. All three ask `addon_access`, so the console cannot show an unlocked
card over an endpoint that answers 402.

WHY THE RESOLVER NEVER WRITES
=============================

It runs on request paths guarded by role dependencies that may be read-only.
Grace windows are STAMPED by the sweep and by the gateway reconciler. When the
resolver sees a grant disappear before either has run, it answers GRACE with a
provisional end date rather than LAPSED: the failure mode of a 15-minute sweep
lag must be fourteen days and fifteen minutes of access, never an outage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import entitlements
from app.core.config import settings
from app.models.custom_domain import DOMAIN_STATUS_REVOKED, CustomDomain
from app.models.organization_addon import (
    ADDON_STATUS_ACTIVE,
    ADDON_STATUS_GRACE,
    ADDON_STATUS_LAPSED,
    GRANTED_BY_SUBSCRIPTION,
    GRANTED_BY_TIER,
    PURCHASE_ACTIVE,
    PURCHASE_ON_HOLD,
    OrganizationAddon,
)
from app.models.warehouse_sync import WarehouseDestination

STATE_ACTIVE = "ACTIVE"
STATE_GRACE = "GRACE"
STATE_LAPSED = "LAPSED"
STATE_NOT_GRANTED = "NOT_GRANTED"


@dataclass(frozen=True)
class AddonPrice:
    """One way an add-on is sold: a currency, an interval and the gateway product that charges it (N-187)."""

    currency: str
    interval: str  # "month" | "year"
    amount_micros: int
    #: `settings` attribute holding the gateway product id. An attribute NAME,
    #: not a value: product ids differ between test and live mode.
    product_setting: str

    def product_id(self) -> Optional[str]:
        return getattr(settings, self.product_setting, None) or None


@dataclass(frozen=True)
class AddonOffer:
    """What an add-on is, what it costs, and what losing it does."""

    key: str
    display_name: str
    description: str
    #: Every price it is sold at (Final session 2A, N-187). Empty: sold to nobody, only included in plans
    #: (custom domains since N-187).
    prices: tuple[AddonPrice, ...]
    #: Plain words for what happens when grace ends. Rendered in notifications
    #: and in the console, so it must be true of `addon_service.halt_resources`.
    halt_effect: str
    resource_noun: str
    #: Plan keys (`quota_tier.key`) whose organizations may buy this add-on. Empty: any plan that does not already
    #: bundle it. GST Credit is sold to Starter (`developer`) only: Free chooses a plan first, Business and Enterprise
    #: include it.
    sold_on_tiers: tuple[str, ...] = ()

    def price(self, currency: str = "USD", interval: str = "month") -> Optional[AddonPrice]:
        return next((p for p in self.prices if (p.currency, p.interval) == (currency, interval)), None)

    @property
    def monthly_price_micros(self) -> int:
        """The dollar monthly price (0 when it is not sold in dollars monthly)."""
        price = self.price("USD", "month")
        return price.amount_micros if price is not None else 0

    @property
    def currency(self) -> str:
        return "USD"

    @property
    def product_setting(self) -> Optional[str]:
        """The dollar monthly product's setting name (the one every add-on had before N-187)."""
        price = self.price("USD", "month")
        return price.product_setting if price is not None else None

    @property
    def sold(self) -> bool:
        return bool(self.prices)

    def price_for_product(self, product_id: Optional[str]) -> Optional[AddonPrice]:
        """The price a gateway product id charges, among this add-on's configured products."""
        if not product_id:
            return None
        return next((p for p in self.prices if p.product_id() == product_id), None)


ADDON_CATALOG: dict[str, AddonOffer] = {
    # Final session 2A (N-187): included in Business and Enterprise, sold to nobody. The $199 add-on and its gateway
    # product were retired: it was bundled into every paid plan, so nobody could ever buy it. The entry stays because
    # the custom-domain routes, the grace sweep and the ledger read the add-on's key and words.
    entitlements.CUSTOM_DOMAIN_ADDON: AddonOffer(
        key=entitlements.CUSTOM_DOMAIN_ADDON,
        display_name="Custom domains",
        description=(
            "Serve Servabo on your own hostname, with TLS certificates issued "
            "and renewed for you and branding shown before sign-in."
        ),
        prices=(),
        halt_effect=(
            "verified hostnames are taken offline. You keep the claim, so no "
            "other organization can take the name"
        ),
        resource_noun="custom domain",
    ),
    entitlements.WAREHOUSE_SYNC_ADDON: AddonOffer(
        key=entitlements.WAREHOUSE_SYNC_ADDON,
        display_name="Warehouse sync",
        description=(
            "Scheduled exports of usage, documents, assistant and automation "
            "activity into Snowflake, BigQuery, S3 or your own warehouse."
        ),
        # N-187: sold in dollars only (not in rupees).
        prices=(AddonPrice("USD", "month", 300_000_000, "DODO_ADDON_PRODUCT_WAREHOUSE_SYNC"),),
        halt_effect=(
            "scheduled exports are paused. Destinations and run history are "
            "kept"
        ),
        resource_noun="warehouse destination",
    ),
    entitlements.GST_CREDIT_ADDON: AddonOffer(
        key=entitlements.GST_CREDIT_ADDON,
        display_name="GST Credit",
        description=(
            "The full GST Credit list for your GSTR-2B: every supplier and invoice with the Invoice Management "
            "System (IMS) recommendation, your decisions, the Excel export and reminders to suppliers."
        ),
        # N-145, N-187: per organization; yearly is ten months.
        prices=(
            AddonPrice("USD", "month", 49_000_000, "DODO_ADDON_PRODUCT_GST_CREDIT"),
            AddonPrice("USD", "year", 490_000_000, "DODO_ADDON_PRODUCT_GST_CREDIT_YEARLY"),
            AddonPrice("INR", "month", 1_499_000_000, "DODO_ADDON_PRODUCT_GST_CREDIT_INR"),
            AddonPrice("INR", "year", 14_990_000_000, "DODO_ADDON_PRODUCT_GST_CREDIT_YEARLY_INR"),
        ),
        halt_effect=(
            "the full GST Credit lists return to the preview. Your imports, matches and decisions are kept, "
            "and everything comes back at once when you add it again"
        ),
        resource_noun="GSTR-2B import",
        sold_on_tiers=("developer",),
    ),
}


def _assert_catalogued() -> None:
    """Refuse to import if the catalog and the entitlement vocabulary drift."""
    registered = set(entitlements.ADDON_KEYS)
    catalogued = set(ADDON_CATALOG)
    if registered != catalogued:
        raise RuntimeError(
            "Add-on catalog and entitlement registry disagree: "
            f"registered={sorted(registered)} catalogued={sorted(catalogued)}."
        )


_assert_catalogued()


@dataclass(frozen=True)
class AddonAccess:
    addon_key: str
    state: str
    source: Optional[str]
    grace_ends_at: Optional[datetime]
    live_resource_count: int

    @property
    def can_create(self) -> bool:
        """New resources: a new hostname, a new destination, a new schedule."""
        return self.state == STATE_ACTIVE

    @property
    def can_maintain(self) -> bool:
        """Keeping existing resources working during a downgrade grace."""
        return self.state in (STATE_ACTIVE, STATE_GRACE)


class UnknownAddonError(ValueError):
    """An add-on key that is not in the catalog."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def grace_period() -> timedelta:
    return timedelta(days=int(getattr(settings, "BILLING_ADDON_GRACE_DAYS", 14)))


def on_hold_grace_period() -> timedelta:
    return timedelta(days=int(getattr(settings, "BILLING_ON_HOLD_GRACE_DAYS", 13)))


def offer_for(addon_key: str) -> AddonOffer:
    try:
        return ADDON_CATALOG[addon_key]
    except KeyError as exc:
        raise UnknownAddonError(f"{addon_key!r} is not a known add-on.") from exc


def ledger_row(
    db: Session,
    *,
    organization_id: uuid.UUID,
    addon_key: str,
    for_update: bool = False,
) -> Optional[OrganizationAddon]:
    stmt = select(OrganizationAddon).where(
        OrganizationAddon.organization_id == organization_id,
        OrganizationAddon.addon_key == addon_key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def tier_grants(db: Session, *, organization_id: uuid.UUID, addon_key: str) -> bool:
    from app.services import quota_service  # local: quota_service is heavy

    tier = quota_service.resolve_tier(db, organization_id=organization_id)
    if tier is None:
        return False
    return any(entry.limit_key == addon_key for entry in tier.entries)


def purchase_grants(row: Optional[OrganizationAddon], *, now: datetime) -> bool:
    if row is None:
        return False
    if row.purchase_status == PURCHASE_ACTIVE:
        return True
    return bool(
        row.purchase_status == PURCHASE_ON_HOLD
        and row.purchase_grace_ends_at is not None
        and row.purchase_grace_ends_at > now
    )


def grant_source(
    db: Session,
    *,
    organization_id: uuid.UUID,
    addon_key: str,
    row: Optional[OrganizationAddon],
    now: datetime,
) -> Optional[str]:
    """TIER before SUBSCRIPTION: a bundled grant survives a cancelled purchase."""
    if tier_grants(db, organization_id=organization_id, addon_key=addon_key):
        return GRANTED_BY_TIER
    if purchase_grants(row, now=now):
        return GRANTED_BY_SUBSCRIPTION
    return None


def live_resource_count(
    db: Session, *, organization_id: uuid.UUID, addon_key: str
) -> int:
    """Resources a lapse would affect. Zero means a lapse breaks nothing."""
    if addon_key == entitlements.CUSTOM_DOMAIN_ADDON:
        stmt = select(func.count()).select_from(CustomDomain).where(
            CustomDomain.organization_id == organization_id,
            CustomDomain.status != DOMAIN_STATUS_REVOKED,
        )
    elif addon_key == entitlements.WAREHOUSE_SYNC_ADDON:
        stmt = select(func.count()).select_from(WarehouseDestination).where(
            WarehouseDestination.organization_id == organization_id,
        )
    elif addon_key == entitlements.GST_CREDIT_ADDON:
        return _gst_statements_at_stake(db, organization_id=organization_id)
    else:
        raise UnknownAddonError(f"{addon_key!r} is not a known add-on.")
    return int(db.execute(stmt).scalar_one() or 0)


def _gst_statements_at_stake(db: Session, *, organization_id: uuid.UUID) -> int:
    """Imported GSTR-2B statements an ended GST Credit add-on would put back behind the preview.

    Nothing is switched off or deleted when it ends, so this only decides whether a cancellation is announced and
    given the usual grace period. It counts only for an organization that actually bought the add-on: one that never
    did has imported statements too (importing is part of the preview), and "resources that predate gating" must
    not hand it fourteen days of the full list."""
    from app.models.gst import GstReturn
    from app.services.gst import vocabulary as gst_vocabulary

    bought = db.execute(
        select(OrganizationAddon.id).where(
            OrganizationAddon.organization_id == organization_id,
            OrganizationAddon.addon_key == entitlements.GST_CREDIT_ADDON,
            OrganizationAddon.gateway_subscription_id.is_not(None),
        )
    ).first()
    if bought is None:
        return 0
    return int(db.execute(
        select(func.count()).select_from(GstReturn).where(
            GstReturn.organization_id == organization_id, GstReturn.status == gst_vocabulary.RETURN_ACTIVE)
    ).scalar_one() or 0)


def addon_access(
    db: Session,
    *,
    organization_id: uuid.UUID,
    addon_key: str,
    now: Optional[datetime] = None,
) -> AddonAccess:
    offer_for(addon_key)
    moment = now or utcnow()
    row = ledger_row(db, organization_id=organization_id, addon_key=addon_key)
    source = grant_source(
        db, organization_id=organization_id, addon_key=addon_key, row=row, now=moment
    )
    resources = live_resource_count(
        db, organization_id=organization_id, addon_key=addon_key
    )

    if source is not None:
        return AddonAccess(addon_key, STATE_ACTIVE, source, None, resources)

    if row is not None:
        if (
            row.status == ADDON_STATUS_GRACE
            and row.grace_ends_at is not None
            and row.grace_ends_at > moment
        ):
            return AddonAccess(addon_key, STATE_GRACE, None, row.grace_ends_at, resources)
        if row.status == ADDON_STATUS_ACTIVE:
            # The grant vanished since the sweep last looked. Provisional grace,
            # never an outage caused by sweep latency.
            return AddonAccess(
                addon_key, STATE_GRACE, None, moment + grace_period(), resources
            )
        if row.status == ADDON_STATUS_LAPSED:
            return AddonAccess(addon_key, STATE_LAPSED, None, None, resources)
        # GRACE whose window has passed and has not been swept yet.
        return AddonAccess(addon_key, STATE_LAPSED, None, row.grace_ends_at, resources)

    if resources > 0:
        # Resources that predate gating. Same fourteen days as a downgrade.
        return AddonAccess(addon_key, STATE_GRACE, None, moment + grace_period(), resources)

    return AddonAccess(addon_key, STATE_NOT_GRANTED, None, None, 0)


def purchasable(addon_key: str, *, currency: Optional[str] = None, interval: Optional[str] = None) -> bool:
    """Self-serve purchase needs a Merchant-of-Record gateway and a product id (for this currency and interval, when
    given; any configured price otherwise)."""
    from app.services.billing.payment_gateway import active_gateway_name

    if active_gateway_name() != "DODO":
        return False
    offer = offer_for(addon_key)
    return any(price.product_id() for price in offer.prices
               if currency in (None, price.currency) and interval in (None, price.interval))


def offered_prices(addon_key: str) -> list[AddonPrice]:
    """The prices of this add-on whose gateway product is configured, in the catalogue's order."""
    return [price for price in offer_for(addon_key).prices if price.product_id()]


def addon_for_product(product_id: Optional[str]) -> Optional[tuple[str, AddonPrice]]:
    """A gateway product id -> (add-on key, the price it charges), across every configured add-on price."""
    for key, offer in ADDON_CATALOG.items():
        price = offer.price_for_product(product_id)
        if price is not None:
            return key, price
    return None


def sold_on(db: Session, addon_key: str) -> list[str]:
    """Display names of the plans that may buy this add-on ([] means any plan that does not bundle it)."""
    from app.services import quota_service

    keys = offer_for(addon_key).sold_on_tiers
    published = {tier.key: tier.display_name for tier in quota_service.list_published_tiers(db, at=utcnow())}
    return [published.get(key, key.title()) for key in keys]


def offered_on_plan(db: Session, *, organization_id: uuid.UUID, addon_key: str) -> bool:
    """Whether this organization's plan is one the add-on is sold on (every plan, when the offer names none)."""
    from app.services import quota_service

    offer = offer_for(addon_key)
    if not offer.sold:
        return False  # N-187: included in plans only (custom domains), never sold
    keys = offer.sold_on_tiers
    if not keys:
        return True
    tier = quota_service.resolve_tier(db, organization_id=organization_id)
    return tier is not None and tier.key in keys


def tiers_including(db: Session, addon_key: str) -> list[str]:
    """Display names of published tiers in force that bundle this add-on."""
    from app.services import quota_service

    names: list[str] = []
    for tier in quota_service.list_published_tiers(db, at=utcnow()):
        if any(entry.limit_key == addon_key for entry in tier.entries):
            if tier.display_name not in names:
                names.append(tier.display_name)
    return names


__all__ = [
    "ADDON_CATALOG",
    "AddonAccess",
    "AddonOffer",
    "AddonPrice",
    "addon_for_product",
    "offered_prices",
    "STATE_ACTIVE",
    "STATE_GRACE",
    "STATE_LAPSED",
    "STATE_NOT_GRANTED",
    "UnknownAddonError",
    "addon_access",
    "grace_period",
    "grant_source",
    "ledger_row",
    "live_resource_count",
    "offer_for",
    "offered_on_plan",
    "on_hold_grace_period",
    "purchasable",
    "purchase_grants",
    "sold_on",
    "tier_grants",
    "tiers_including",
    "utcnow",
]
