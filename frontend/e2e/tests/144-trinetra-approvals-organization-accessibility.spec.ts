/**
 * TRINETRA on Enterprise (Final session 2T, Phase 8): the approval chain in the browser, the organization view per legal entity, and
 * accessibility on every screen: axe in light and dark, keyboard reach, and no sideways scroll at 390 px. Synthetic data only.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { signInAs } from "../support/journey";
import {
  bookInvoice, createCase, createProfile, ENTITY, importStatement, liveCustomer, TAN, templateFile, type LiveCustomer,
} from "../support/trinetra";

let customer: LiveCustomer;
let caseId: string;

const TABS = ["Cases", "Statements", "Suggestions", "Reversals", "Approvals", "Closures"] as const;

async function expectNoSeriousViolations(page: Page, label: string) {
  const scan = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  const serious = scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${label}: ${v.id} ${v.nodes[0]?.target}`)).toEqual([]);
}

async function expectNoSidewaysScroll(page: Page, label: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label} scrolls sideways`).toBeLessThanOrEqual(1);
}

test.describe("TRINETRA Enterprise", () => {
  test.setTimeout(300_000);
  test.beforeAll(async () => {
    customer = await liveCustomer("tr-ent", "enterprise", { people: true });
    const profile = await createProfile(customer);
    const invoice = await bookInvoice(customer, "TRE-1");
    caseId = (await createCase(customer, profile, invoice, "TRE-1")).id;
    const snapshot = await importStatement(
      customer, profile, templateFile([`${TAN},2000.00,row-1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27`]),
    );
    const url = `/workspaces/${customer.wsId}/trinetra`;
    const policy = await api(customer.session, "PUT", `/organizations/${customer.orgId}/trinetra/policy`, {
      threshold: "1000", actions: ["CA_REVIEWED"], approver_role: "OWNER",
    });
    expect(policy.status, policy.text).toBe(200);
    // The workspace administrator allocates the posting and asks to close the case; the policy makes it wait for the owner.
    const admin = customer.admin!.session;
    const allocated = await api<{ revision: number }>(admin, "POST", `${url}/credits/${caseId}/decisions`, {
      revision: 1, action: "ALLOCATE", reason: "The statement row is this invoice's withholding.",
      allocations: [{ snapshot_id: snapshot, line_id: "0", amount: "2000" }],
    });
    expect(allocated.status, allocated.text).toBe(200);
    const asked = await api(admin, "POST", `${url}/credits/${caseId}/decisions`, {
      revision: allocated.body.revision, action: "CA_REVIEWED", reason: "The accountant reviewed the posting.",
    });
    expect(asked.status, asked.text).toBe(202);
  });

  test("someone who is not the named role cannot approve it, and the server says so", async () => {
    const url = `/workspaces/${customer.wsId}/trinetra`;
    const listed = await api<{ items: Array<{ id: string; status: string }> }>(customer.session, "GET", `${url}/approvals`);
    expect(listed.status).toBe(200);
    for (const item of listed.body.items.filter((i) => i.status === "PENDING")) {
      const own = await api(customer.admin!.session, "POST", `${url}/approvals/${item.id}/approve`, { reason: "Approving as the person who asked." });
      expect([403, 409]).toContain(own.status);
    }
    expect(listed.body.items.filter((i) => i.status === "PENDING")).toHaveLength(1);
    {
    }
  });

  test("a closure above the threshold waits; the owner approves it with a reason and it is recorded", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("trinetra?tab=approvals"));
    const policy = page.getByTestId("trinetra-policy-summary");
    await expect(policy).toContainText("needs an organization");
    const waiting = page.getByTestId("trinetra-approval");
    await expect(waiting).toHaveCount(1);
    await expect(waiting).toContainText("Waiting for approval");
    await expect(waiting).toContainText("₹2,000.00");
    await waiting.getByRole("button", { name: "Approve", exact: true }).click();
    await waiting.getByLabel("Why you approve").fill("Read the advice and the statement row; they agree.");
    await waiting.getByRole("button", { name: "Approve this closure" }).click();
    await expect(page.getByTestId("trinetra-approval").first()).toHaveAttribute("data-status", "APPROVED");
    await expect(page.getByTestId("trinetra-approval").first()).toContainText("Approved");
  });

  test("the organization view shows each legal entity once, across workspaces", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("trinetra"));
    await expect(page.getByRole("heading", { level: 1, name: "Credit assurance across workspaces" })).toBeVisible();
    await expect(page.getByTestId("trinetra-org-totals")).toBeVisible();
    const entities = page.getByTestId("trinetra-org-entities");
    await expect(entities).toContainText(ENTITY);
    await expect(entities.getByRole("heading", { level: 3, name: ENTITY })).toHaveCount(1);
    await expect(page.getByTestId("trinetra-org-totals")).not.toContainText(TAN);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`every screen passes axe and keeps the keyboard · ${scheme}`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, customer.email);
      await page.goto(customer.ws("trinetra"));
      await expect(page.getByRole("tab", { name: "Cases" })).toBeVisible();
      for (const name of TABS) {
        await page.getByRole("tab", { name }).click();
        await settle(page);
        await expect(page.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
        await expectNoSeriousViolations(page, `${name} ${scheme}`);
      }
      await page.getByRole("tab", { name: "Cases" }).click();
      await page.getByRole("button", { name: /TRE-1/ }).click();
      await settle(page);
      await expectNoSeriousViolations(page, `case insight ${scheme}`);
      await page.goto(customer.org("trinetra"));
      await settle(page);
      await expectNoSeriousViolations(page, `organization view ${scheme}`);
      await page.goto(customer.ws(`trinetra?case=${caseId}`));
      await expect(page.getByRole("heading", { level: 1, name: "Review credit evidence" })).toBeVisible();
      await settle(page);
      await expectNoSeriousViolations(page, `case review ${scheme}`);
      // Keyboard: the tabs are reached and changed with the arrow keys.
      await page.goto(customer.ws("trinetra"));
      await page.getByRole("tab", { name: "Cases" }).focus();
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Enter");
      await expect(page.getByRole("tab", { name: "Statements" })).toBeFocused();
    });
  }

  test("nothing scrolls sideways at 390 px on any screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signInAs(page, customer.email);
    await page.goto(customer.ws("trinetra"));
    await expect(page.getByRole("tab", { name: "Cases" })).toBeVisible();
    for (const name of TABS) {
      await page.getByRole("tab", { name }).click();
      await settle(page);
      await expectNoSidewaysScroll(page, name);
    }
    await page.getByRole("tab", { name: "Cases" }).click();
    await page.getByRole("button", { name: /TRE-1/ }).click();
    await settle(page);
    await expectNoSidewaysScroll(page, "case insight");
    await page.goto(customer.org("trinetra"));
    await settle(page);
    await expectNoSidewaysScroll(page, "organization view");
    await page.goto(customer.ws(`trinetra?case=${caseId}`));
    await settle(page);
    await expectNoSidewaysScroll(page, "case review");
  });
});
