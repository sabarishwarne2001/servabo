/**
 * GST CREDIT AS AN ADD-ON (Session H, N-145): a Developer customer who will not pay for Business can still pay for
 * the list. $49 a month for the organization, bought through the gateway's checkout, recorded on the add-on ledger.
 *
 * A Developer customer of its own (the plan is bought through the stand-in Dodo, as every journey does) imports a
 * GSTR-2B and sees the figures but not the lists. Then:
 *   1. the GST page offers "Add GST Credit — $49 a month for your organization" beside "Business includes it, with Helm";
 *   2. a member (not an owner) sees whom to ask and no buy button;
 *   3. the owner buys it through the stand-in's checkout page and comes back to the billing page;
 *   4. the supplier list unlocks, and Billing -> Add-ons says "Active".
 * Accessibility is scanned in both themes, on the offer and on the unlocked page.
 *
 * Stood in: the gateway's hosted checkout page (the stand-in Dodo's), as in the plan journeys. The webhook that follows
 * the payment is Dodo's real shape, signed, and Servabo's worker reconciles it.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { test, expect, settle } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { DODO_ORIGIN, GATEWAY } from "../support/env";
import { gstin, gstr2b } from "../support/gst";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";

const BUYER = gstin("27", "AAACA1234F");
const SUPPLIER = gstin("27", "AABCS5555K");
const PERIOD = "2026-09";

let owner: Customer;
let member: { email: string };

const statement = (): string =>
  gstr2b(BUYER, PERIOD, [
    { gstin: SUPPLIER, name: "Sahyadri Packaging", docs: [{ number: "A-1001", date: "2026-09-05", taxable: 1000 }] },
  ]);

const upload = async (c: Customer, text: string) => {
  const form = new FormData();
  form.append("file", new Blob([text], { type: "application/json" }), "GSTR2B_092026.json");
  return api<{ results: Array<{ status: string; record_count: number }> }>(c.session, "POST", `/workspaces/${c.wsId}/gst/returns`, form);
};

const open = async (page: Page, c: Customer, tab = "suppliers"): Promise<void> => {
  await page.goto(`${c.ws("gst")}?tab=${tab}`);
  await expect(page.getByRole("heading", { level: 1, name: "GST credit" })).toBeVisible();
  await settle(page);
};

const addonState = async (c: Customer): Promise<string | undefined> => {
  const session = await apiLogin(c.email);
  const body = (await api<{ addons: Array<{ addon_key: string; state: string }> }>(session, "GET", `/organizations/${c.orgId}/entitlements`)).body;
  return body.addons.find((a) => a.addon_key === "addon.gst_credit")?.state;
};

test.describe("GST Credit as an add-on", () => {
  test.skip(GATEWAY !== "dodo", "the add-on is sold through the stand-in Dodo");
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    owner = await newCustomer("gstaddon", "GST Add-on Traders Ltd");
    standIn("dodo-catalogue", null);          // the plans and the add-on, as products at the stand-in Dodo
    standIn("subscribe", owner.orgSlug, "--plan", "developer", "--seats", "3");
    expect((await upload(owner, statement())).status).toBe(200);
    member = await addMember(owner, "gstaddon-member", "MEMBER", "CONTRIBUTOR");
  });

  test("the GST page shows the add-on offer, with what Business includes", async ({ page }) => {
    expect(await addonState(owner)).toBe("NOT_GRANTED");
    await signInAs(page, owner.email);
    await open(page, owner);
    const offer = page.getByTestId("gst-addon-offer");
    await expect(offer).toBeVisible();
    await expect(offer).toContainText("Add GST Credit — $49 a month for your organization");
    await expect(offer).toContainText("Business includes it, with Helm");
    await expect(page.getByTestId("gst-preview-lock")).toContainText("Business and Enterprise add");
    await expect(page.getByTestId("gst-figures")).toBeVisible();      // the figures stay open on every plan
    await expect(offer.getByRole("button", { name: /Add GST Credit/ })).toBeEnabled();
  });

  test("a member sees whom to ask and no buy button", async ({ page }) => {
    await signInAs(page, member.email);
    await open(page, owner);
    const offer = page.getByTestId("gst-addon-offer");
    await expect(offer).toBeVisible();
    await expect(offer.getByTestId("ask-plan-owners")).toContainText(/Ask .* to add it/);
    await expect(page.getByRole("button", { name: /Add GST Credit/ })).toHaveCount(0);
    const refused = await api(await apiLogin(member.email), "POST", `/organizations/${owner.orgId}/billing/addons/addon.gst_credit/checkout-session`, {});
    expect(refused.status).toBe(403);       // the server agrees: only an owner starts a checkout
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the offer has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      await open(page, owner);
      await expect(page.getByTestId("gst-addon-offer")).toBeVisible();
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
        testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${v.id} (${v.nodes.length})` });
      }
      expect(found, "the add-on offer with serious or critical accessibility violations").toEqual([]);
    });
  }

  test("the owner buys it through the checkout page and the supplier list unlocks", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page, owner);
    await page.getByTestId("gst-addon-offer").getByRole("button", { name: /Add GST Credit/ }).click();

    // The stand-in Dodo's checkout page: one GST Credit for the organization, $49 a month.
    await expect(page).toHaveURL(new RegExp(`^${DODO_ORIGIN.replace(/\./g, "\\.")}/checkout/`), { timeout: 20_000 });
    await expect(page.locator("body")).toContainText("GST Credit × 1: USD 49.00 per month");
    await page.getByRole("button", { name: "Pay", exact: true }).click();

    // Back on the billing page, which says the payment is being confirmed and then lists the add-on as Active.
    await expect(page).toHaveURL(new RegExp(`${owner.org("billing").replace(/\//g, "\\/")}\\?addon=success`), { timeout: 20_000 });
    await expect(page.getByTestId("addon-returned")).toBeVisible();
    await expect(page.getByTestId("addon-status-addon.gst_credit")).toHaveText("Active", { timeout: 60_000 });
    expect(await addonState(owner)).toBe("ACTIVE");

    // The lists are open now.
    await open(page, owner, "suppliers");
    await expect(page.getByTestId("gst-preview-lock")).toHaveCount(0);
    await expect(page.getByTestId("gst-supplier-row").first()).toBeVisible();
    await open(page, owner, "invoices");
    await expect(page.getByTestId("gst-line-row").first()).toBeVisible();
    const session = await apiLogin(owner.email);
    expect((await api(session, "GET", `/workspaces/${owner.wsId}/gst/records`)).status).toBe(200);
    expect((await api(session, "GET", `/workspaces/${owner.wsId}/gst/export.xlsx`)).status).toBe(200);
  });

  test("the member sees the lists too, and a second checkout is refused", async ({ page }) => {
    await signInAs(page, member.email);
    await open(page, owner, "suppliers");
    await expect(page.getByTestId("gst-preview-lock")).toHaveCount(0);
    await expect(page.getByTestId("gst-supplier-row").first()).toBeVisible();
    const again = await api(await apiLogin(owner.email), "POST", `/organizations/${owner.orgId}/billing/addons/addon.gst_credit/checkout-session`, {});
    expect(again.status).toBe(409);          // already active: nobody pays twice
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the unlocked page and the add-on list have no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      const found: string[] = [];
      for (const where of [`${owner.ws("gst")}?tab=suppliers`, owner.org("billing")]) {
        await page.goto(where);
        await settle(page);
        if (where.includes("billing")) await expect(page.getByTestId("billing-addons")).toBeVisible();
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        for (const v of results.violations) {
          if (v.impact === "serious" || v.impact === "critical") found.push(`${where} ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
          else testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${where}: ${v.id} (${v.nodes.length})` });
        }
      }
      expect(found, "serious or critical accessibility violations").toEqual([]);
    });
  }

  test("cancelling it returns the page to the preview and keeps the data", async ({ page }) => {
    // The gateway side: Dodo cancels the add-on subscription; the worker reconciles it.
    const before = (await api<{ summary?: unknown }>(await apiLogin(owner.email), "GET", `/workspaces/${owner.wsId}/gst/summary`)).body;
    standIn("cancel-addon", owner.orgSlug, "--addon", "addon.gst_credit");
    // A cancelled add-on with statements on file gets the usual fourteen days: the lists stay open, and Billing says when it ends.
    await expect.poll(() => addonState(owner), { timeout: 60_000 }).toBe("GRACE");
    await signInAs(page, owner.email);
    await page.goto(owner.org("billing"));
    await expect(page.getByTestId("addon-status-addon.gst_credit")).toContainText(/Ends on/, { timeout: 30_000 });
    await open(page, owner, "suppliers");
    await expect(page.getByTestId("gst-preview-lock")).toHaveCount(0);
    // Past the grace the page is the preview again, and every import is still there.
    standIn("addon-grace-ends", owner.orgSlug, "--addon", "addon.gst_credit");
    await expect.poll(() => addonState(owner), { timeout: 60_000 }).toBe("LAPSED");
    await open(page, owner, "suppliers");
    await expect(page.getByTestId("gst-addon-offer")).toBeVisible();
    await expect(page.getByTestId("gst-figures")).toBeVisible();
    const after = (await api<{ summary?: unknown }>(await apiLogin(owner.email), "GET", `/workspaces/${owner.wsId}/gst/summary`)).body;
    expect(JSON.stringify((after as { figures?: unknown }).figures)).toBe(JSON.stringify((before as { figures?: unknown }).figures));
  });
});
