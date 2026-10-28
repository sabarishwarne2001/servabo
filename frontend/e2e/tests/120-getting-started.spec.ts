/**
 * GETTING STARTED (Final session 1, 2C): a short path to the first money found.
 *
 * A trial customer of its own. The checklist is ticked by the server from real data, and a person only sees the steps they can do:
 *   1. the owner sees seven steps, the email-in address with a copy button, and a plain note where a feature is a preview;
 *   2. the sample invoice ticks "Add your documents" and, once the worker has read it, "See what Servabo read";
 *   3. inviting a teammate ticks "Invite a teammate" (the count is the real number of members);
 *   4. a contributor who is only a member sees three steps (documents, read, GST): no Helm, no recipe, no invite, no address;
 *   5. hiding the card leaves a link that brings it back.
 * Accessibility is scanned in both themes.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { addMember, newCustomer, signInAs, type Customer } from "../support/journey";

let owner: Customer;

const card = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Get started with Servabo" });

test.describe("Getting started", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);

  test.beforeAll(async () => {
    owner = await newCustomer("started", "Getting Started Ltd");
  });

  test("the owner sees seven steps, the email-in address and a plain note on each preview", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.ws(""));
    await expect(card(page)).toBeVisible({ timeout: 30_000 });
    await expect(card(page)).toContainText("0 of 7 done");
    const steps = card(page).getByRole("list", { name: "Getting started steps" }).getByRole("listitem");
    await expect(steps).toHaveCount(7);
    await expect(steps.nth(0)).toContainText("Add your documents");
    await expect(steps.nth(2)).toContainText("Import a GSTR-2B");
    await expect(steps.nth(3)).toContainText("TDS your customers withheld");
    await expect(steps.nth(4)).toContainText("Open Helm");
    await expect(steps.nth(5)).toContainText("Turn on one recipe");
    await expect(steps.nth(6)).toContainText("Invite a teammate");
    await expect(page.getByTestId("getting-started-address")).toContainText("@", { timeout: 20_000 });
    await expect(card(page).getByRole("button", { name: "Copy the email-in address" })).toBeVisible();
    // Each step leads to its own place.
    await expect(card(page).getByRole("link", { name: "Open GST Credit" })).toHaveAttribute("href", /\/gst$/);
    await expect(card(page).getByRole("link", { name: "Open TDS credit" })).toHaveAttribute("href", /\/trinetra$/);
    await expect(card(page).getByRole("link", { name: "Open Helm" })).toHaveAttribute("href", /\/helm$/);
    await expect(card(page).getByRole("link", { name: "Browse recipes" })).toHaveAttribute("href", /\/automation$/);
    await expect(card(page).getByRole("link", { name: "Go to members" })).toHaveAttribute("href", /\/members$/);
  });

  test("the sample invoice ticks the first two steps from real data", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.ws(""));
    await card(page).getByRole("button", { name: "Try a sample invoice" }).click();
    await expect(page.getByText(/Sample invoice added/)).toBeVisible({ timeout: 15_000 });
    await expect(card(page)).toContainText("1 of 7 done", { timeout: 30_000 });
    await expect(card(page)).toContainText("2 of 7 done", { timeout: 180_000 });
  });

  test("inviting a teammate ticks the invite step, and that member sees only the steps they can do", async ({ page }) => {
    const member = await addMember(owner, "started-member", "MEMBER", "CONTRIBUTOR");
    await signInAs(page, owner.email);
    await page.goto(owner.ws(""));
    await expect(card(page)).toContainText("3 of 7 done", { timeout: 30_000 });

    await signInAs(page, member.email);
    await page.goto(owner.ws(""));
    await expect(card(page)).toBeVisible({ timeout: 30_000 });
    const steps = card(page).getByRole("list", { name: "Getting started steps" }).getByRole("listitem");
    await expect(steps).toHaveCount(3);
    await expect(card(page)).not.toContainText("Open Helm");
    await expect(card(page)).not.toContainText("Invite a teammate");
    await expect(card(page)).not.toContainText("Turn on one recipe");
    await expect(page.getByTestId("getting-started-address")).toHaveCount(0);
  });

  test("hiding the card leaves a link that brings it back", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.ws(""));
    await card(page).getByRole("button", { name: "Hide getting started" }).click();
    await expect(card(page)).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("button", { name: /Show getting started/ })).toBeVisible({ timeout: 30_000 });
    await expect(card(page)).toHaveCount(0);
    await page.getByRole("button", { name: /Show getting started/ }).click();
    await expect(card(page)).toBeVisible();
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the card has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await signInAs(page, owner.email);
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(owner.ws(""));
      await expect(card(page)).toBeVisible({ timeout: 30_000 });
      await settle(page);
      const results = await new AxeBuilder({ page })
        .include('section[aria-labelledby="getting-started"]')
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.length}`), testInfo.title).toEqual([]);
    });
  }
});
