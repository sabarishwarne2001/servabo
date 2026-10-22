/**
 * CONNECT YOUR BOOKS (Final session 1, 3C): Zoho Books with a sign-in, and Tally Prime guided.
 *
 * Zoho is stood in by tests/fakes/fake_zoho.py (start-stack.sh). Its consent screen approves at once and sends the browser back to the
 * API's callback; its token endpoint answers HTTP 200 {"error": "invalid_code"} for a revoked refresh token, as Zoho does. A Business
 * customer of its own, signed in as the owner:
 *   1. "Connect Zoho Books" (India by default) -> Zoho -> back on the page asking which Zoho organization -> chosen -> Connected;
 *   2. the saved sign-in is removed at Zoho -> "Check connection" says "Needs reconnecting" (no raw error) -> "Reconnect Zoho Books"
 *      -> Connected again, on the same connection and organization;
 *   3. "Disconnect" asks in the app's own dialog, revokes at Zoho and shows Disconnected;
 *   4. a contributor sees what is connected and no way to change it;
 *   5. Tally Prime: five answers make a download target, opened on its page;
 *   6. accessibility in both themes.
 * Stood in: Zoho. Nothing is sent to a real Zoho.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { ZOHO_ORIGIN } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";

let owner: Customer;
let contributor: { email: string };

const open = async (page: import("@playwright/test").Page): Promise<void> => {
  await page.goto(owner.ws("erp"));
  await page.getByRole("tab", { name: "Connect your books" }).click();
  await expect(page.getByTestId("connect-books")).toBeVisible({ timeout: 30_000 });
};

const state = (page: import("@playwright/test").Page) => page.getByTestId("zoho-state");

test.describe("Connect your books", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(300_000);
    owner = await newCustomer("books", "Books Traders Ltd");
    standIn("subscribe", owner.orgSlug, "--plan", "business", "--seats", "4");
    contributor = await addMember(owner, "books-contrib", "MEMBER", "CONTRIBUTOR");
  });

  test("Connect Zoho Books: sign in at Zoho, choose the organization, connected", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    await expect(page.getByTestId("zoho-not-configured")).toHaveCount(0);
    await expect(page.getByLabel("Zoho data centre")).toHaveValue("IN");
    await page.getByRole("button", { name: "Connect Zoho Books" }).click();
    // Zoho's consent screen (stood in) approves at once and the browser comes back to the page.
    await expect(page).toHaveURL(/zoho=choose/, { timeout: 30_000 });
    await expect(page.getByTestId("zoho-connection")).toBeVisible({ timeout: 30_000 });
    await expect(state(page)).toHaveText("Choose your Zoho organization");
    await page.getByLabel("Zoho organization").selectOption({ label: "Meridian Retail LLP" });
    await page.getByRole("button", { name: "Use this organization" }).click();
    await expect(state(page)).toHaveText("Connected", { timeout: 30_000 });
    await expect(page.getByTestId("zoho-connection")).toContainText("Meridian Retail LLP");
    await expect(page.getByTestId("zoho-connection")).toContainText("India");
    // The target exists on the Targets tab, with no credential to paste.
    await page.getByRole("tab", { name: "Targets" }).click();
    await expect(page.getByRole("link", { name: "Zoho Books" })).toBeVisible();
  });

  test("a sign-in removed at Zoho reads Reconnect Zoho Books, and reconnecting keeps the connection", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    await page.getByRole("button", { name: "Check connection" }).click();
    await expect(page.getByText("Zoho Books is connected.")).toBeVisible();
    const revoked = await fetch(`${ZOHO_ORIGIN}/__control/revoke`, { method: "POST" });
    expect(revoked.ok).toBe(true);
    await page.getByRole("button", { name: "Check connection" }).click();
    await expect(state(page)).toHaveText("Needs reconnecting", { timeout: 30_000 });
    await expect(page.getByRole("alert").filter({ hasText: "no longer accepts" })).toBeVisible();
    await expect(page.locator("main")).not.toContainText("invalid_code");
    await page.getByRole("button", { name: "Reconnect Zoho Books" }).click();
    await expect(page).toHaveURL(/zoho=(connected|choose)/, { timeout: 30_000 });
    await expect(state(page)).toHaveText("Connected", { timeout: 30_000 });
    await expect(page.getByTestId("zoho-connection")).toContainText("Meridian Retail LLP");
    await expect(page.getByTestId("zoho-connection")).toHaveCount(1);
  });

  test("a contributor sees what is connected and cannot change it", async ({ page }) => {
    await signInAs(page, contributor.email);
    await open(page);
    await expect(state(page)).toHaveText("Connected");
    await expect(page.getByRole("button", { name: "Connect Zoho Books" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Disconnect" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Set up Tally Prime" })).toHaveCount(0);
    await expect(page.getByText("A workspace admin connects Zoho Books.")).toBeVisible();
  });

  test("Tally Prime: five answers make a download target", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    await page.getByRole("button", { name: "Set up Tally Prime" }).click();
    const form = page.getByRole("form", { name: "Set up Tally Prime" });
    await form.getByLabel("Company, exactly as spelled in Tally Prime").fill("Books Traders Pvt Ltd");
    await form.getByLabel("Purchase ledger").fill("Packaging Purchases");
    await form.getByLabel("Input CGST ledger").fill("Input CGST 9%");
    await form.getByLabel("Input SGST ledger").fill("Input SGST 9%");
    await form.getByLabel("Input IGST ledger").fill("Input IGST 18%");
    await form.getByRole("button", { name: "Create the Tally target" }).click();
    await expect(page).toHaveURL(/\/erp\/targets\/[0-9a-f-]{36}/, { timeout: 30_000 });
    await expect(page.locator("main")).toContainText("Tally Prime", { timeout: 30_000 });
    await expect(page.locator("main")).toContainText("Books Traders Pvt Ltd");
  });

  test("Disconnect asks first, revokes at Zoho and shows Disconnected", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    await page.getByRole("button", { name: "Disconnect" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Disconnect Zoho Books?");
    await dialog.getByRole("button", { name: "Disconnect" }).click();
    await expect(state(page)).toHaveText("Disconnected", { timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Connect again" })).toBeVisible();
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the page has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      await open(page);
      await settle(page);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      expect(found, testInfo.title).toEqual([]);
    });
  }
});
