/**
 * Final session 1 (3B): every locked surface is a sales moment, and this one test walks all of them.
 *
 * The surfaces are read from the code, so a new lock cannot be added without being walked:
 *   - every `capability:` of the sidebar's navigation (a locked row opens the upgrade dialog);
 *   - every `<PlanLockBanner capability={...}>` (an organization page whose writes the plan does not include);
 *   - every add-on the server sells (a lock card, and the dialog's own offer).
 * For each, with the server's answer faked from the plan list:
 *   - the dialog / banner names the plans that include it (never "a higher plan" when the server knows them);
 *   - an organization OWNER, the only role that can change the plan, is offered "View plans" (the upgrade),
 *     and everyone else (administrator, billing contact, member) is told whom to ask;
 *   - an add-on's action opens the checkout of THAT add-on, for the owner only.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CAPABILITY } from "@/constants/capabilities";
import type { AddonAccess, OrganizationEntitlements } from "@/types/entitlements";

const ROLE = { current: "OWNER" };
const checkout = vi.fn(async (_organizationId: string, _addonKey: string) => ({ url: "https://checkout.example/session", kind: "addon", expires_at: "" }));

vi.mock("@/hooks/useTenant", () => ({
  useTenant: () => ({
    state: {
      status: "ready",
      organization: { organization_id: "org-1", organization_slug: "acme", role: ROLE.current },
      organizationRole: ROLE.current,
    },
  }),
}));
vi.mock("@/routes/OrganizationGuard", () => ({ useOptionalResolvedOrganization: () => null }));
const ALLOWANCE = { canUpgrade: true };
vi.mock("@/services/api/billing", () => ({
  getBillingAccessSummary: async () => ({ plan_contacts: ["Ada Owner"] }),
  getPlanAllowance: async () => ({
    plan_name: "Developer", can_upgrade: ALLOWANCE.canUpgrade, max_file_mb: 25, max_pages_per_document: 100,
    meters: [{ key: "document.upload", used: 20, limit: 25, state: "NEAR", hard_stop: true, overage_policy: "REFUSE", resets_at: "2026-11-01T00:00:00Z" }],
  }),
}));
vi.mock("@/services/api/entitlements", async () => {
  const actual = await vi.importActual<typeof import("@/services/api/entitlements")>("@/services/api/entitlements");
  return { ...actual, getOrganizationEntitlements: async () => fixture(), createAddonCheckoutSession: (...args: [string, string]) => checkout(...args) };
});

import { PlanLockBanner } from "@/components/billing/PlanLockBanner";
import { AddOnLockCard } from "@/components/billing/AddOnLockCard";
import { PlanAllowance } from "@/components/billing/PlanAllowance";
import { useUpgradePrompt } from "@/hooks/useUpgradePrompt";

const ALL = Object.values(CAPABILITY);
const PLANS = ["Business", "Enterprise"];

const addon = (key: AddonAccess["addon_key"], name: string, price: number, soldOn: string[], includedIn: string[]): AddonAccess => ({
  addon_key: key, display_name: name, description: name, state: "NOT_GRANTED", source: null, grace_ends_at: null, can_create: false,
  can_maintain: false, live_resource_count: 0, halt_effect: "", monthly_price_micros: price * 1_000_000, currency: "USD",
  purchasable: true, included_in: includedIn, sold_on: soldOn,
});
const ADDONS = [
  addon("addon.gst_credit", "GST Credit", 49, ["Developer"], PLANS),
  addon("addon.custom_domain", "Custom domains", 99, [], ["Enterprise"]),
  addon("addon.warehouse_sync", "Warehouse sync", 300, [], ["Enterprise"]),
];

function fixture(): OrganizationEntitlements {
  return {
    organization_id: "org-1", as_of: "2026-10-22T00:00:00Z", addons: ADDONS, capabilities: [],
    capability_plans: Object.fromEntries(ALL.map((key) => [key, PLANS])),
  };
}

const sources = import.meta.glob("/src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const find = (re: RegExp, only?: RegExp): string[] => {
  const found = new Set<string>();
  for (const [file, text] of Object.entries(sources)) {
    if (only && !only.test(file)) {continue;}
    for (const match of text.matchAll(re)) {found.add(match[1] as string);}
  }
  return [...found].sort();
};
const NAV = find(/capability:\s*CAPABILITY\.(\w+)/g, /layout\/navigation\.ts$/);
const BANNERS = find(/<PlanLockBanner\s+capability=\{CAPABILITY\.(\w+)\}/g, /\/pages\//);
const keyOf = (name: string): string => (CAPABILITY as Record<string, string>)[name] as string;

const Harness: React.FC<{ capability: string; role: string }> = ({ capability, role }) => {
  const upgrade = useUpgradePrompt("org-1", "acme", role);
  return (
    <>
      <button type="button" onClick={() => upgrade.prompt(capability, "The feature", capability.startsWith("addon.") ? capability : undefined)}>
        open
      </button>
      {upgrade.dialog}
    </>
  );
};

const mount = (node: React.ReactElement) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  ROLE.current = "OWNER";
  checkout.mockClear();
});
afterEach(cleanup);

describe("the list of locked surfaces", () => {
  it("is read from the code and is not empty", () => {
    expect(NAV.length).toBeGreaterThanOrEqual(15);
    expect(BANNERS.length).toBeGreaterThanOrEqual(7);
    for (const name of [...NAV, ...BANNERS]) {expect(keyOf(name), `CAPABILITY.${name} must exist`).toBeTruthy();}
  });
});

const ROLES: ReadonlyArray<readonly [string, boolean]> = [
  ["OWNER", true],
  ["ADMIN", false],
  ["BILLING", false],
  ["MEMBER", false],
];

describe.each(ROLES)("the upgrade dialog, role %s", (role, canUpgrade) => {
  it.each(NAV)("%s: names the plans; the owner can open the plans, everyone else is told whom to ask", async (name) => {
    ROLE.current = role;
    mount(<Harness capability={keyOf(name)} role={role} />);
    fireEvent.click(screen.getByText("open"));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect(dialog.textContent).toContain("the Business and Enterprise plans"));     // the server's list arrives
    expect(dialog.textContent).not.toContain("a higher plan");
    if (canUpgrade) {
      expect(screen.getByRole("button", { name: "View plans" })).toBeTruthy();
      expect(dialog.textContent).toContain("Upgrade to turn it on");
    } else {
      expect(screen.queryByRole("button", { name: "View plans" })).toBeNull();
      expect(dialog.textContent).toContain("Ask Ada Owner to");
    }
  });
});

describe.each(ROLES)("the plan-lock banner, role %s", (role, canUpgrade) => {
  it.each(BANNERS)("%s: names the plans; the owner gets the link, everyone else is told whom to ask", async (name) => {
    ROLE.current = role;
    mount(<PlanLockBanner capability={keyOf(name) as never} feature="The feature" />);
    const banner = await screen.findByTestId("plan-lock-banner");
    await waitFor(() => expect(banner.textContent).toContain("the Business and Enterprise plans"));
    if (canUpgrade) {
      expect(screen.getByRole("link", { name: "View plans" }).getAttribute("href")).toBe("/organizations/acme/billing");
    } else {
      expect(screen.queryByRole("link", { name: "View plans" })).toBeNull();
      expect(banner.textContent).toContain("Ask Ada Owner to");
    }
  });
});

describe("add-ons", () => {
  it("GST Credit: the dialog on Developer offers the add-on at its catalogue price, and the owner's click opens THAT checkout", async () => {
    Object.defineProperty(window, "location", { value: { assign: vi.fn() }, writable: true });
    mount(<Harness capability="addon.gst_credit" role="OWNER" />);
    fireEvent.click(screen.getByText("open"));
    const offer = await screen.findByTestId("upgrade-addon-offer");
    expect(offer.textContent).toContain("Add GST Credit — $49 a month");
    fireEvent.click(screen.getByRole("button", { name: /Add GST Credit/ }));
    await waitFor(() => expect(checkout).toHaveBeenCalledWith("org-1", "addon.gst_credit"));
  });

  it.each(ADDONS)("$display_name: its lock card names the price and the plans that include it; only the owner can buy it", async (item) => {
    for (const [role, owner] of ROLES) {
      cleanup();
      ROLE.current = role;
      mount(<AddOnLockCard organizationId="org-1" addon={item} canPurchase={owner} />);
      const card = document.body.textContent ?? "";
      expect(card).toContain(`$${item.monthly_price_micros / 1_000_000}`);
      for (const plan of item.included_in) {expect(card).toContain(plan);}
      if (owner) {
        fireEvent.click(screen.getAllByRole("button")[0] as HTMLElement);
        await waitFor(() => expect(checkout).toHaveBeenLastCalledWith("org-1", item.addon_key));
      } else {
        expect(screen.queryAllByRole("button")).toHaveLength(0);
        await waitFor(() => expect(document.body.textContent).toContain("Ask Ada Owner to"));
      }
    }
  });
});

describe("the 80% banner", () => {
  it("offers the upgrade with one click to the plan picker when this person can change the plan, and nothing to click otherwise", async () => {
    ALLOWANCE.canUpgrade = true;
    mount(<PlanAllowance workspaceId="ws-1" meters={["document.upload"]} />);
    const link = await screen.findByTestId("allowance-upgrade");
    expect(link.getAttribute("href")).toBe("/organizations/acme/billing#plans");
    cleanup();
    ALLOWANCE.canUpgrade = false;
    mount(<PlanAllowance workspaceId="ws-1" meters={["document.upload"]} />);
    await screen.findByText(/80% of this month's documents used|\d+% of this month's documents used/);
    expect(screen.queryByTestId("allowance-upgrade")).toBeNull();
  });
});
