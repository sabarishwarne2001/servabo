/**
 * The price list, read from src/data/pricing.json (written by backend/scripts/export_public_pricing.py
 * from the same plan table the app sells). Nothing here types a price or an allowance: it only
 * gives the data words, and the build FAILS when the data names a plan, a feature or an allowance
 * this file has no words for, so a new plan can never reach the site unlabelled.
 */
import data from "../data/pricing.json";

export type Interval = "month" | "year";

interface RawPrice {
  interval: string;
  currency: string;
  unit_amount: number;
}
interface RawAllowance {
  key: string;
  limit_quantity: number | null;
  period: string;
  overage_policy: string | null;
}
interface RawPlan {
  key: string;
  display_name: string;
  is_priced: boolean;
  per_seat: boolean;
  prices: RawPrice[];
  allowances: RawAllowance[];
  features: string[];
  helm: {
    edition: "full" | "preview";
    active_mandates: number | null;
    backtest_months: number | null;
    custom_conditions: boolean;
    approval_chains: boolean;
    all_workspaces: boolean;
    api_and_webhooks: boolean;
  };
}

/** What each plan is for, in one line. */
export const PLAN_LABELS: Record<string, { name: string; for: string }> = {
  free: { name: "Free trial", for: "Try Servabo on your own documents for two weeks, long enough for one monthly GSTR-2B. No card needed." },
  // The key stays `developer`; customers see "Starter" (N-187).
  developer: { name: "Starter", for: "For a small accounts team: invoices read for you, the Tally Prime file, automations and the API." },
  business: { name: "Business", for: "For finance and operations teams: matching, Helm, obligations and ERP posting." },
  enterprise: { name: "Enterprise", for: "For organizations that need single sign-on, approval chains and every control." },
};

/** Allowances, as a customer plans by them. */
export const ALLOWANCE_LABELS: Record<string, { label: string; unit: string }> = {
  "document.upload": { label: "Documents", unit: "documents" },
  "ocr.page": { label: "Pages read (OCR)", unit: "pages" },
  "assistant.message": { label: "Assistant questions", unit: "questions" },
  "limit.seats": { label: "People", unit: "seats" },
  "limit.workspaces": { label: "Workspaces", unit: "workspaces" },
  "limit.file_size_mb": { label: "Largest file", unit: "MB" },
  "limit.pages_per_document": { label: "Pages per document", unit: "pages" },
  "storage.gb_month": { label: "Storage", unit: "GB" },
  "llm.platform_key": { label: "AI included, no provider key needed", unit: "" },
};

/** Features (capabilities and add-ons), as the job they do. */
export const FEATURE_LABELS: Record<string, string> = {
  "capability.trinetra_all_workspaces": "TRINETRA across all your workspaces and legal entities",
  "capability.trinetra": "TRINETRA: check that your customers' TDS reached your tax statement",
  "capability.developer_api": "Developer API keys",
  "capability.outgoing_webhooks": "Outgoing webhooks",
  "capability.custom_branding": "Your logo, colours and name",
  "capability.automations": "Automations and marketplace workflows",
  "capability.tally_file": "The Tally Prime import file",
  "addon.custom_domain": "Your own domain",
  "capability.reconciliation": "Three-way matching of invoices, POs and receipts",
  "capability.anomaly_radar": "Duplicate and anomaly radar",
  "capability.custom_email": "Mail from your own address",
  "addon.warehouse_sync": "Analytics warehouse sync",
  "capability.extraction_memory": "Extraction memory (learns from corrections)",
  "capability.entity_graph": "One record per supplier, customer and person",
  "capability.case_intelligence": "Case files and splitting scanned bundles",
  "capability.table_intelligence": "Tables across pages, checked and exported",
  "capability.batch_dispatch": "Batch operations and verified export packages",
  "capability.helm": "Helm: the promise ledger, mandates and the payment plan",
  "capability.truthmesh": "TruthMesh: conflicts across documents",
  "capability.obligations": "Obligations, deadlines and calendar feeds",
  "capability.erp_posting": "Posting to your ERP, exactly once",
  "capability.byok": "Bring your own AI key",
  "capability.calibrated_autonomy": "Calibrated autonomy",
  "capability.redaction": "Redaction of personal data",
  "capability.semantic_assertions": "Clause checks on contracts",
  "capability.universal_corroborator": "Compare documents clause by clause",
  "capability.collaborative_review": "Live review together",
  "capability.enterprise_identity": "SAML single sign-on and SCIM",
  "capability.process_intelligence": "Process intelligence and the exception agent",
  "capability.egress_lockdown": "Egress lockdown",
  "capability.helm_custom": "Helm custom conditions",
  "capability.helm_approval_chains": "Helm approval chains",
  "capability.helm_all_workspaces": "Helm across every workspace",
  "capability.helm_api": "Helm through the API and webhooks",
  "capability.gst_credit": "GST credit: purchase invoices matched with GSTR-2B",
  "capability.gst_credit_all_workspaces": "GST credit across every workspace",
  "capability.recoveries": "Recoveries: money issues with an owner, closed only on evidence",
  "capability.priority_slo": "Priority 99.9% service objective",
};

interface RawAddon {
  key: string;
  name: string;
  prices: RawPrice[];
  per: string;
  included_in: string[];
  sold_on: string[];
}

/** What each add-on does, in one plain sentence. The price, the plans and the name come from the data. */
export const ADDON_WORDS: Record<string, string> = {
  "addon.custom_domain": "Serve Servabo on your own hostname, with the certificate looked after for you.",
  "addon.warehouse_sync": "Scheduled exports of usage, documents and activity into Snowflake, BigQuery or S3.",
  "addon.gst_credit":
    "The full GST Credit list on Starter: every supplier and invoice beside GSTR-2B, IMS recommendations, your decisions, the Excel export and supplier reminders.",
};

/** Order on plan cards and in the comparison table: the order the plans add them. */
export const FEATURE_ORDER: readonly string[] = Object.keys(FEATURE_LABELS);

export const PLAN_ORDER: readonly string[] = ["free", "developer", "business", "enterprise"];

function fail(message: string): never {
  throw new Error(`website/src/data/pricing.json: ${message}. Add its words in website/src/lib/pricing.ts.`);
}

const raw = data as unknown as {
  trial: { days: number };
  billing: { usage_billing: boolean };
  plans: RawPlan[];
  addons: RawAddon[];
};

for (const plan of raw.plans) {
  if (!PLAN_LABELS[plan.key]) fail(`plan "${plan.key}" has no label`);
  for (const a of plan.allowances) if (!ALLOWANCE_LABELS[a.key]) fail(`allowance "${a.key}" has no label`);
  for (const f of plan.features) if (!FEATURE_LABELS[f]) fail(`feature "${f}" has no label`);
  if (!plan.prices.some((p) => p.interval === "month")) fail(`plan "${plan.key}" has no monthly price`);
}

/**
 * Final session 2A (N-187): every price in rupees (India, the default here) and in dollars, in minor units (paise or
 * cents); null where the plan is not sold that way (Enterprise yearly is by agreement).
 */
export type Currency = "INR" | "USD";
export const CURRENCIES: readonly Currency[] = ["INR", "USD"];
export interface Amounts {
  INR: number | null;
  USD: number | null;
}

const amounts = (prices: RawPrice[], interval: Interval): Amounts => ({
  INR: prices.find((p) => p.interval === interval && p.currency === "INR")?.unit_amount ?? null,
  USD: prices.find((p) => p.interval === interval && p.currency === "USD")?.unit_amount ?? null,
});

export interface Plan {
  key: string;
  name: string;
  for: string;
  perSeat: boolean;
  /** Dollar cents a month (0 for Free); kept for "is it paid" checks. Prices to show are `month` and `year`. */
  monthly: number;
  yearly: number | null;
  month: Amounts;
  year: Amounts;
  features: string[];
  allowances: RawAllowance[];
  helm: RawPlan["helm"];
  rank: number;
}

export const PLANS: Plan[] = raw.plans
  .map((plan) => {
    const usd = (interval: Interval) =>
      plan.prices.find((p) => p.interval === interval && p.currency === "USD")?.unit_amount ?? null;
    const labels = PLAN_LABELS[plan.key]!;
    return {
      key: plan.key,
      name: labels.name,
      for: labels.for,
      perSeat: plan.per_seat,
      monthly: usd("month") ?? 0,
      yearly: usd("year"),
      month: amounts(plan.prices, "month"),
      year: amounts(plan.prices, "year"),
      features: FEATURE_ORDER.filter((f) => plan.features.includes(f)),
      allowances: plan.allowances,
      helm: plan.helm,
      rank: PLAN_ORDER.indexOf(plan.key),
    };
  })
  .sort((a, b) => a.rank - b.rank);

for (const a of raw.addons) if (!ADDON_WORDS[a.key]) fail(`add-on "${a.key}" has no words`);

export interface Addon {
  key: string;
  name: string;
  words: string;
  /** For the whole organization (N-187: rupees and dollars, monthly and yearly; none when it is only included). */
  month: Amounts;
  year: Amounts;
  sold: boolean;
  includedIn: Plan[];
  soldOn: Plan[];
}

const plansByKey = (keys: string[]): Plan[] =>
  keys.map((k) => PLANS.find((p) => p.key === k) ?? fail(`add-on names the unknown plan "${k}"`));

export const ADDONS: Addon[] = raw.addons.map((a) => ({
  key: a.key,
  name: a.name,
  words: ADDON_WORDS[a.key]!,
  month: amounts(a.prices, "month"),
  year: amounts(a.prices, "year"),
  sold: a.prices.length > 0,
  includedIn: plansByKey(a.included_in),
  soldOn: plansByKey(a.sold_on),
}));

export function addon(key: string): Addon {
  return ADDONS.find((a) => a.key === key) ?? fail(`no add-on "${key}"`);
}

export const TRIAL_DAYS = raw.trial.days;
/** False on Dodo Payments today: a "bill overage" limit is published as a hard monthly limit. */
export const USAGE_BILLING = raw.billing.usage_billing;
export const HAS_YEARLY = PLANS.some((p) => p.yearly !== null);

export function plan(key: string): Plan {
  const found = PLANS.find((p) => p.key === key);
  if (!found) fail(`no plan "${key}"`);
  return found;
}

/** The lowest plan that includes a feature (null: every plan). */
export function lowestPlanWith(feature: string | null): Plan | null {
  if (feature === null) return null;
  if (!FEATURE_LABELS[feature]) fail(`feature "${feature}" has no label`);
  return PLANS.find((p) => p.features.includes(feature)) ?? fail(`no plan includes "${feature}"`);
}

/** "₹1,499" (Indian digit grouping: ₹1,49,990) or "$49". */
export function money(minor: number, currency: Currency): string {
  const whole = minor / 100;
  if (currency === "INR") {
    return `₹${whole.toLocaleString("en-IN", { maximumFractionDigits: whole % 1 === 0 ? 0 : 2 })}`;
  }
  return dollars(minor);
}

export function dollars(cents: number): string {
  const whole = cents / 100;
  return `$${whole.toLocaleString("en-US", { maximumFractionDigits: whole % 1 === 0 ? 0 : 2 })}`;
}

const NUMBER = new Intl.NumberFormat("en-US");

/** "5,000 pages a month per seat", "Unlimited", "Hard monthly limit" — the allowance in words. */
export function allowanceText(plan: Plan, a: RawAllowance): { value: string; note: string } {
  const label = ALLOWANCE_LABELS[a.key]!;
  if (a.key === "llm.platform_key") return { value: "Included", note: "" };
  if (a.key === "limit.seats") {
    return plan.perSeat
      ? { value: "Buy the seats you need", note: "" }
      : { value: `${a.limit_quantity ?? "Unlimited"} people`, note: "" };
  }
  if (a.limit_quantity === null) {
    return { value: a.key === "assistant.message" ? "Fair use" : "Unlimited", note: "" };
  }
  const isStatic = a.key.startsWith("limit.");
  const qty =
    a.key === "storage.gb_month" && a.limit_quantity < 1
      ? `${Math.round(a.limit_quantity * 1024)} MB`
      : `${NUMBER.format(a.limit_quantity)}${label.unit ? ` ${label.unit}` : ""}`;
  const per = isStatic ? "" : plan.perSeat ? " a month per seat" : " a month";
  return { value: `${qty}${per}`, note: overageNote(a) };
}

export function overageNote(a: RawAllowance): string {
  if (a.key.startsWith("limit.") || a.limit_quantity === null) return "";
  switch (a.overage_policy) {
    case "REFUSE":
      return "hard monthly limit — add seats or upgrade for more";
    case "ALLOW_AND_WARN":
      return "soft limit — work continues and your usage page shows it";
    case "ALLOW_AND_BILL":
      return "then billed per unit at the rate on your billing page";
    default:
      return "";
  }
}
