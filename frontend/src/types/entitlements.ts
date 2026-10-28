/**
 * ARCH-30 Tranche 2 (D-8) — add-on entitlements.
 *
 * Mirrors `app/schemas/entitlements.py`. Every boolean the console acts on —
 * `can_create`, `can_maintain`, `purchasable` — is computed by the backend and
 * sent. The console never re-derives them from `state`, so a button can never
 * be enabled over an endpoint that answers 402.
 */

export type AddonKey = "addon.custom_domain" | "addon.warehouse_sync" | "addon.gst_credit";

export type AddonState = "ACTIVE" | "GRACE" | "LAPSED" | "NOT_GRANTED";

/** Final session 2A (N-187): one price an add-on is sold at. `unit_amount` is in cents or paise. */
export interface AddonPriceOption {
  readonly currency: "USD" | "INR";
  readonly interval: "month" | "year";
  readonly unit_amount: number;
  readonly purchasable: boolean;
}

export interface AddonAccess {
  readonly addon_key: AddonKey;
  readonly display_name: string;
  readonly description: string;
  readonly state: AddonState;
  readonly source: "TIER" | "SUBSCRIPTION" | null;
  readonly grace_ends_at: string | null;
  readonly can_create: boolean;
  readonly can_maintain: boolean;
  readonly live_resource_count: number;
  readonly halt_effect: string;
  readonly monthly_price_micros: number;
  readonly currency: string;
  readonly purchasable: boolean;
  readonly included_in: readonly string[];
  /** Session H: plans that may buy it when it is sold on particular plans only (GST Credit: Starter). */
  readonly sold_on: readonly string[];
  /** N-187: every price it is sold at (empty: included in plans only, never sold, as custom domains). */
  readonly prices?: readonly AddonPriceOption[];
}

export interface OrganizationEntitlements {
  readonly organization_id: string;
  readonly as_of: string;
  readonly addons: readonly AddonAccess[];
  /** N-187: the currency this organization sees prices in first (INR for an Indian organization). */
  readonly default_currency?: "USD" | "INR";
  /** ARCH35-S3:capabilities-typed. Tier-bundled capability keys held. */
  readonly capabilities: readonly string[];
  /** HM-S1: capability key -> display names of the published plans that include it. */
  readonly capability_plans?: Readonly<Record<string, readonly string[]>>;
}

/** The structured 402 body from `app/api/addon_gate.py`. */
export interface AddonRequiredDetail {
  readonly code: "ADDON_REQUIRED";
  readonly addon_key: AddonKey;
  readonly addon_name: string;
  readonly state: AddonState;
  readonly grace_ends_at: string | null;
  readonly message: string;
}
