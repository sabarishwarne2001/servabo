"""ARCH-30 Tranche 2 (D-8) — add-on entitlement responses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AddonState = Literal["ACTIVE", "GRACE", "LAPSED", "NOT_GRANTED"]


class AddonPriceOption(BaseModel):
    """One price an add-on is sold at (Final session 2A, N-187)."""

    currency: Literal["USD", "INR"]
    interval: Literal["month", "year"]
    unit_amount: int = Field(description="Minor units (cents or paise).")
    purchasable: bool = Field(description="True when its gateway product is configured on this deployment.")


class AddonAccessResponse(BaseModel):
    addon_key: str
    display_name: str
    description: str
    state: AddonState
    source: Optional[Literal["TIER", "SUBSCRIPTION"]] = None
    grace_ends_at: Optional[datetime] = Field(
        default=None,
        description=(
            "End of full access during a downgrade grace. Provisional until the "
            "sweep stamps it, which happens within one sweep interval."
        ),
    )
    can_create: bool
    can_maintain: bool
    live_resource_count: int
    halt_effect: str
    monthly_price_micros: int = Field(description="The dollar monthly price; 0 when the add-on is not sold in dollars "
                                                  "monthly (custom domains are sold to nobody since N-187).")
    currency: str
    prices: list[AddonPriceOption] = Field(default_factory=list, description="N-187. Every price it is sold at.")
    purchasable: bool = Field(
        description="True when an owner can buy this add-on self-serve right now."
    )
    included_in: list[str] = Field(
        default_factory=list,
        description="Published plans that include this add-on.",
    )
    sold_on: list[str] = Field(
        default_factory=list,
        description=(
            "Plans that may buy this add-on, when it is sold on particular plans only (GST Credit: Starter). "
            "Empty: any plan that does not already include it."
        ),
    )


class OrganizationEntitlementsResponse(BaseModel):
    organization_id: uuid.UUID
    as_of: datetime
    default_currency: Literal["USD", "INR"] = Field(
        default="USD", description="N-187. The currency this organization sees prices in first (INR for India).")
    addons: list[AddonAccessResponse]
    # ARCH35-S1:capabilities-listed. `useCapabilityAccess` has always read this
    # field; until ARCH-35 it did not exist, so every capability-gated page
    # showed its lock card to entitled tenants too.
    capabilities: list[str] = Field(
        default_factory=list,
        description="Tier-bundled capability keys this organization holds.",
    )
    # HM-S1:capability-plans. Which plans on sale include each capability, so
    # the console's upgrade dialog names them without a second copy of the
    # packaging table.
    capability_plans: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Capability key -> display names of the published plans that include it.",
    )


__all__ = ["AddonAccessResponse", "AddonPriceOption", "AddonState", "OrganizationEntitlementsResponse"]