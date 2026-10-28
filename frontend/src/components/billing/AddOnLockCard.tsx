import React from "react";
import { useMutation } from "@tanstack/react-query";
import { Clock, Loader2, Lock } from "lucide-react";

import { createAddonCheckoutSession } from "@/services/api/entitlements";
import { BUTTON_PRIMARY, HINT, SECTION_TITLE, SURFACE } from "@/components/ui/primitives";
import type { AddonAccess, AddonPriceOption } from "@/types/entitlements";
import { formatTimestampDate, numberFormat } from "@/utils/displayTime";
import AskPlanOwners from "@/components/billing/AskPlanOwners";

/**
 * ARCH-30 Tranche 2 (D-8, D-6) — what an organization sees in place of an
 * add-on it does not have, and the notice it sees while one is winding down.
 *
 * Copy rules: say what the add-on does, what it costs, and what the reader can
 * do about it. A non-owner is told who can act rather than shown a button that
 * would answer 403.
 */

export const formatAddonPrice = (micros: number, currency: string): string =>
  numberFormat({
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(micros / 1_000_000);

/**
 * Final session 2A (N-187). The add-on's prices in the currency the organization sees first (rupees for an Indian
 * organization), else in dollars; monthly first.
 */
export const addonPricesIn = (addon: AddonAccess, currency: "USD" | "INR" = "USD"): AddonPriceOption[] => {
  const all = [...(addon.prices ?? [])];
  const pick = all.some((p) => p.currency === currency) ? currency : "USD";
  return all.filter((p) => p.currency === pick).sort((a, b) => (a.interval === "month" ? -1 : 1) - (b.interval === "month" ? -1 : 1));
};

/** The monthly price in the organization's currency ("₹1,499"), else the dollar monthly price. */
export const addonMonthlyPrice = (addon: AddonAccess, currency: "USD" | "INR" = "USD"): string => {
  const monthly = addonPricesIn(addon, currency).find((p) => p.interval === "month");
  return monthly ? formatAddonPrice(monthly.unit_amount * 10_000, monthly.currency) : formatAddonPrice(addon.monthly_price_micros, addon.currency);
};

/** "₹1,499 a month or ₹14,990 a year"; the dollar monthly price when the server sent no price list. */
export const addonPriceLine = (addon: AddonAccess, currency: "USD" | "INR" = "USD"): string => {
  const prices = addonPricesIn(addon, currency);
  if (prices.length === 0) {
    return `${formatAddonPrice(addon.monthly_price_micros, addon.currency)} a month`;
  }
  return prices.map((p) => `${formatAddonPrice(p.unit_amount * 10_000, p.currency)} a ${p.interval}`).join(" or ");
};

const formatDay = (iso: string | null): string | null =>
  iso ? formatTimestampDate(iso) : null;

const includedPhrase = (addon: AddonAccess): string =>
  addon.included_in.length > 0
    ? `It's included with ${addon.included_in.join(" and ")}.`
    : "";

export interface PurchaseProps {
  readonly organizationId: string;
  readonly addon: AddonAccess;
  readonly canPurchase: boolean;
  readonly label: string;
  /** N-187: the currency to buy in (the organization's default); a yearly button appears when it is sold yearly. */
  readonly currency?: "USD" | "INR";
}

export const PurchaseAction: React.FC<PurchaseProps> = ({
  organizationId,
  addon,
  canPurchase,
  label,
  currency,
}) => {
  const prices = addonPricesIn(addon, currency ?? "USD").filter((p) => p.purchasable);
  const buyIn = prices[0]?.currency;
  const yearly = prices.find((p) => p.interval === "year");
  const checkout = useMutation({
    mutationFn: (interval: "month" | "year") =>
      createAddonCheckoutSession(organizationId, addon.addon_key, { ...(buyIn ? { currency: buyIn } : {}), interval }),
    onSuccess: (session) => {
      window.location.assign(session.url);
    },
  });

  if (!canPurchase) {
    return <p className={HINT}><AskPlanOwners toDo="add it" /></p>;
  }

  if (!addon.purchasable) {
    return (
      <p className={HINT}>
        Self-serve purchase isn't available for this add-on yet. Contact sales to add it.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        className={BUTTON_PRIMARY}
        disabled={checkout.isPending}
        onClick={() => checkout.mutate("month")}
      >
        {checkout.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        {label}
      </button>
      {yearly ? (
        <button
          type="button"
          className="block text-xs font-semibold text-primary underline"
          disabled={checkout.isPending}
          onClick={() => checkout.mutate("year")}
        >
          Or pay yearly: {formatAddonPrice(yearly.unit_amount * 10_000, yearly.currency)} a year
        </button>
      ) : null}
      {checkout.isError ? (
        <p role="alert" className="text-xs text-destructive">
          Couldn't start checkout. Try again, or contact support if it keeps failing.
        </p>
      ) : null}
    </div>
  );
};

export interface AddOnLockCardProps {
  readonly organizationId: string;
  readonly addon: AddonAccess;
  readonly canPurchase: boolean;
}

export const AddOnLockCard: React.FC<AddOnLockCardProps> = ({
  organizationId,
  addon,
  canPurchase,
}) => {
  const price = formatAddonPrice(addon.monthly_price_micros, addon.currency);

  if (addon.prices !== undefined && addon.prices.length === 0 && addon.included_in.length > 0) {
    // N-187: an add-on that is only included in plans (custom domains: Business and Enterprise) is an upgrade.
    return (
      <section className={`${SURFACE} p-6`} aria-labelledby={`lock-${addon.addon_key}`}>
        <div className="flex items-start gap-4">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            <Lock className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0 flex-1 space-y-2">
            <h2 id={`lock-${addon.addon_key}`} className={SECTION_TITLE}>
              {addon.display_name} come with {addon.included_in.join(" and ")}
            </h2>
            <p className="max-w-prose text-sm text-muted-foreground">{addon.description}</p>
            <p className="text-sm text-foreground">Upgrade to {addon.included_in[0]} to use them. {canPurchase ? "" : ""}</p>
            {canPurchase ? null : <p className={HINT}><AskPlanOwners toDo="upgrade the plan" /></p>}
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className={`${SURFACE} p-6`} aria-labelledby={`lock-${addon.addon_key}`}>
      <div className="flex items-start gap-4">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Lock className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <h2 id={`lock-${addon.addon_key}`} className={SECTION_TITLE}>
              {addon.display_name} is an add-on
            </h2>
            <p className="mt-1 max-w-prose text-sm text-muted-foreground">
              {addon.description}
            </p>
          </div>
          <p className="text-sm text-foreground">
            Add it to your current plan for{" "}
            <span className="font-semibold">{price} a month</span>. {includedPhrase(addon)}
          </p>
          <PurchaseAction
            organizationId={organizationId}
            addon={addon}
            canPurchase={canPurchase}
            label={`Add ${addon.display_name.toLowerCase()} for ${price}/month`}
          />
        </div>
      </div>
    </section>
  );
};

export interface AddOnGraceNoticeProps {
  readonly organizationId: string;
  readonly addon: AddonAccess;
  readonly canPurchase: boolean;
}

/**
 * Rendered above existing resources while an add-on is in GRACE, or after it
 * LAPSED with resources still on file. Never rendered for ACTIVE.
 */
export const AddOnGraceNotice: React.FC<AddOnGraceNoticeProps> = ({
  organizationId,
  addon,
  canPurchase,
}) => {
  if (addon.state === "ACTIVE") {
    return null;
  }

  const until = formatDay(addon.grace_ends_at);
  const lapsed = addon.state === "LAPSED" || addon.state === "NOT_GRANTED";
  const name = addon.display_name.toLowerCase();

  return (
    <div
      role="status"
      className="mt-4 flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3"
    >
      <Clock className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
      <div className="min-w-0 flex-1 space-y-2 text-sm">
        {lapsed ? (
          <p className="text-foreground">
            {addon.display_name} has ended, so {addon.halt_effect}. Nothing was deleted,
            and you can still remove what's here.
          </p>
        ) : (
          <p className="text-foreground">
            {addon.display_name} is no longer part of your plan. What you already have
            keeps working{until ? ` until ${until}` : " for 14 days"}; after that,{" "}
            {addon.halt_effect}. New ones can't be added in the meantime.
          </p>
        )}
        <PurchaseAction
          organizationId={organizationId}
          addon={addon}
          canPurchase={canPurchase}
          label={lapsed ? `Restore ${name}` : `Keep ${name}`}
        />
      </div>
    </div>
  );
};

export default AddOnLockCard;
