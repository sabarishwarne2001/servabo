import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { Link } from "react-router-dom";

import AskPlanOwners from "@/components/billing/AskPlanOwners";
import { PurchaseAction, addonMonthlyPrice, addonPriceLine } from "@/components/billing/AddOnLockCard";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, HINT, SURFACE } from "@/components/ui/primitives";
import { useAddonAccess } from "@/hooks/useAddonAccess";
import { organizationBillingPath } from "@/routes/tenantPaths";
import { getBillingAccessSummary } from "@/services/api/billing";
import { billingKeys } from "@/services/api/queryKeys";

/**
 * What a plan without GST Credit sees in place of a list: the numbers above are real, and this says plainly how to
 * get the list.
 *
 *   Developer          the add-on, for the people who can buy it (owners), beside "Business includes it, with Helm";
 *   the free trial     both ways, and "Choose a plan" (owners) or whom to ask (everyone else, as the trial banner does);
 *   anyone else        what Business adds, with the upgrade dialog the sidebar uses.
 *
 * Session H (N-145). A member never sees a buy button: the checkout is an owner's to start.
 */
export const PreviewLock: React.FC<{
  readonly title: string;
  readonly teaser: string;
  readonly onUpgrade: () => void;
  readonly organizationId: string;
  readonly organizationSlug: string;
  readonly isOwner: boolean;
}> = ({ title, teaser, onUpgrade, organizationId, organizationSlug, isOwner }) => {
  const { access, currency } = useAddonAccess(organizationId, "addon.gst_credit");
  const summary = useQuery({
    queryKey: billingKeys.accessSummary(organizationId),
    queryFn: () => getBillingAccessSummary(organizationId),
    enabled: Boolean(organizationId),
    staleTime: 60_000,
    retry: false,
  });
  const notBought = access !== null && (access.state === "NOT_GRANTED" || access.state === "LAPSED");
  const onTrial = summary.data?.trial?.state === "ACTIVE" || (summary.data?.trial?.state === "ENDED" && !summary.data.trial.lapsed);
  const buyHere = notBought && access.purchasable;
  const sellsOn = access?.sold_on.join(" or ") ?? "";
  const price = access ? addonPriceLine(access, currency) : "";

  return (
    <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="gst-lock-title" data-testid="gst-preview-lock">
      <div className="flex items-center gap-2">
        <Lock className="h-4 w-4 text-muted-foreground" aria-hidden />
        <h2 id="gst-lock-title" className="text-[15px] font-semibold text-foreground">
          {title}
        </h2>
      </div>
      <p className="text-sm text-muted-foreground">{teaser}</p>
      <p className={HINT}>
        Your figures above are real and stay open on every plan. Business and Enterprise add the supplier list, the invoice
        list with the books beside GSTR-2B, recommendations for the GST portal&apos;s Invoice Management System, the Excel
        export and supplier reminders.
      </p>

      {buyHere && access ? (
        <div className="space-y-3" data-testid="gst-addon-offer">
          <p className="text-sm text-foreground">
            <span className="font-semibold">
              Add {access.display_name} — {price} for your organization.
            </span>{" "}
            It unlocks those lists on your {sellsOn} plan. Business includes it, with Helm.
          </p>
          <div className="flex flex-wrap items-start gap-3">
            <PurchaseAction
              organizationId={organizationId}
              addon={access}
              canPurchase={isOwner}
              label={`Add ${access.display_name} — ${addonMonthlyPrice(access, currency)} a month for your organization`}
              currency={currency}
            />
            <button type="button" className={BUTTON_SECONDARY} onClick={onUpgrade}>
              See what Business adds
            </button>
          </div>
        </div>
      ) : onTrial && access ? (
        <div className="space-y-3" data-testid="gst-trial-offer">
          <p className="text-sm text-foreground">
            Two ways to get it: {sellsOn} with the {access.display_name} add-on ({price} a month for your organization), or
            Business, which includes it, with Helm.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            {isOwner ? (
              <Link to={organizationBillingPath(organizationSlug)} className={BUTTON_PRIMARY}>
                Choose a plan
              </Link>
            ) : (
              <p className={HINT}>
                <AskPlanOwners toDo="choose a plan" organizationId={organizationId} />
              </p>
            )}
            <button type="button" className={BUTTON_SECONDARY} onClick={onUpgrade}>
              See what Business adds
            </button>
          </div>
        </div>
      ) : (
        <button type="button" className={BUTTON_SECONDARY} onClick={onUpgrade}>
          See what Business adds
        </button>
      )}
    </section>
  );
};

export default PreviewLock;
