import React from "react";
import { useNavigate } from "react-router-dom";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { useAskPlanOwners } from "@/components/billing/AskPlanOwners";
import { PurchaseAction, formatAddonPrice } from "@/components/billing/AddOnLockCard";
import type { AddonAccess } from "@/types/entitlements";

/** "Business and Enterprise", "Developer, Business and Enterprise". */
export const joinPlanNames = (names: readonly string[]): string => {
  if (names.length === 0) {
    return "a higher plan";
  }
  if (names.length === 1) {
    return `the ${names[0]} plan`;
  }
  return `the ${names.slice(0, -1).join(", ")} and ${names[names.length - 1]} plans`;
};

export interface UpgradePlanDialogProps {
  readonly open: boolean;
  readonly featureName: string;
  readonly includedIn: readonly string[];
  /** OWNER or BILLING: can open the plan picker. */
  readonly canChangePlan: boolean;
  readonly billingPath: string;
  readonly onClose: () => void;
  /**
   * Final session 1 (1D, F-552): the add-on that also unlocks the feature, when one does and this organization can
   * still buy it (Developer and GST Credit). The dialog then names it with its price and, for an owner, offers its
   * checkout beside "View plans"; anyone else is told whom to ask.
   */
  readonly addon?: AddonAccess | null;
  readonly organizationId?: string;
}

/**
 * HM-S1:upgrade-dialog — what a locked sidebar row opens.
 *
 * A capability is bundled into a tier, so the remedy is a plan change and the
 * only action offered is the plan picker (for someone who can use it). The
 * plans named come from the server's published tiers, not from a copy here.
 */
export const UpgradePlanDialog: React.FC<UpgradePlanDialogProps> = ({
  open,
  featureName,
  includedIn,
  canChangePlan,
  billingPath,
  onClose,
  addon = null,
  organizationId,
}) => {
  const navigate = useNavigate();
  const plans = joinPlanNames(includedIn);
  const askOwners = useAskPlanOwners("upgrade");
  const offerAddon =
    addon !== null && organizationId !== undefined && (addon.state === "NOT_GRANTED" || addon.state === "LAPSED") && addon.purchasable;
  const addonPrice = offerAddon && addon ? formatAddonPrice(addon.monthly_price_micros, addon.currency) : "";
  const addonSentence =
    offerAddon && addon
      ? ` ${addon.sold_on.length > 0 ? `On ${addon.sold_on.join(" or ")}, ` : ""}you can also add ${addon.display_name} for ${addonPrice} a month for your organization.`
      : "";
  return (
    <ConfirmDialog
      open={open}
      title={`${featureName} isn't included in your plan`}
      message={
        canChangePlan
          ? `${featureName} is included on ${plans}. Upgrade to turn it on for your whole organization.${addonSentence}`
          : `${featureName} is included on ${plans}. ${askOwners}${addonSentence}`
      }
      confirmText={canChangePlan ? "View plans" : "Got it"}
      cancelText="Not now"
      tone="primary"
      initialFocus="confirm"
      hideCancel={!canChangePlan}
      onConfirm={() => {
        onClose();
        if (canChangePlan) {
          navigate(billingPath);
        }
      }}
      onCancel={onClose}
    >
      {offerAddon && addon && organizationId ? (
        <div className="mt-3" data-testid="upgrade-addon-offer">
          <PurchaseAction
            organizationId={organizationId}
            addon={addon}
            canPurchase={canChangePlan}
            label={`Add ${addon.display_name} — ${addonPrice} a month`}
          />
        </div>
      ) : null}
    </ConfirmDialog>
  );
};

export default UpgradePlanDialog;
