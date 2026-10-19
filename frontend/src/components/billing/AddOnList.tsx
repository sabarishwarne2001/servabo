import React from "react";
import { useQuery } from "@tanstack/react-query";

import AskPlanOwners from "@/components/billing/AskPlanOwners";
import { PurchaseAction, formatAddonPrice } from "@/components/billing/AddOnLockCard";
import { HINT, SECTION_TITLE, SURFACE } from "@/components/ui/primitives";
import { getOrganizationEntitlements } from "@/services/api/entitlements";
import { entitlementKeys } from "@/services/api/queryKeys";
import type { AddonAccess } from "@/types/entitlements";
import { formatTimestampDate } from "@/utils/displayTime";

/** What the list says about one add-on: Not added, Active, Ends on …, or Included in your plan. */
export const addonStatusText = (addon: AddonAccess): string => {
  if (addon.state === "ACTIVE") {
    return addon.source === "TIER" ? "Included in your plan" : "Active";
  }
  if (addon.state === "GRACE") {
    return addon.grace_ends_at ? `Ends on ${formatTimestampDate(addon.grace_ends_at)}` : "Ending soon";
  }
  return "Not added";
};

/**
 * Session H. Every add-on an organization can have, with its state and price, on the billing page. An owner can add
 * one that is for sale on the current plan; everyone else is told whom to ask.
 */
export const AddOnList: React.FC<{ readonly organizationId: string; readonly isOwner: boolean }> = ({
  organizationId,
  isOwner,
}) => {
  const { data } = useQuery({
    queryKey: entitlementKeys.all(organizationId),
    queryFn: () => getOrganizationEntitlements(organizationId),
    enabled: Boolean(organizationId),
    staleTime: 60_000,
  });
  if (!data || data.addons.length === 0) {
    return null;
  }
  return (
    <section className={`${SURFACE} space-y-4 p-6`} aria-labelledby="addons-title" data-testid="billing-addons">
      <div>
        <h2 id="addons-title" className={SECTION_TITLE}>
          Add-ons
        </h2>
        <p className={`${HINT} mt-1`}>Extras you can add to your plan. Each is one price for the whole organization.</p>
      </div>
      <ul className="divide-y divide-border">
        {data.addons.map((addon) => {
          const buyable = addon.purchasable && (addon.state === "NOT_GRANTED" || addon.state === "LAPSED");
          return (
            <li
              key={addon.addon_key}
              className="flex flex-wrap items-start justify-between gap-3 py-3 first:pt-0 last:pb-0"
              data-testid={`addon-row-${addon.addon_key}`}
            >
              <div className="min-w-0 max-w-prose space-y-1">
                <p className="text-sm font-medium text-foreground">{addon.display_name}</p>
                <p className={HINT}>{addon.description}</p>
                {addon.state !== "ACTIVE" ? (
                  <p className={HINT}>{formatAddonPrice(addon.monthly_price_micros, addon.currency)} a month</p>
                ) : null}
              </div>
              <div className="space-y-2 text-right">
                <p className="text-sm text-foreground" data-testid={`addon-status-${addon.addon_key}`}>
                  {addonStatusText(addon)}
                </p>
                {buyable ? (
                  <PurchaseAction
                    organizationId={organizationId}
                    addon={addon}
                    canPurchase={isOwner}
                    label={`Add ${addon.display_name}`}
                  />
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
      {!isOwner ? (
        <p className={HINT}>
          <AskPlanOwners toDo="add an add-on" organizationId={organizationId} />
        </p>
      ) : null}
    </section>
  );
};

export default AddOnList;
