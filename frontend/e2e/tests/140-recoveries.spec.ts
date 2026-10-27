/**
 * RECOVERIES (Final session 2A, N-191): one money issue walked from Found to Verified on the sample company, and the
 * page's accessibility in both themes.
 *
 * The sample company (Meridian Wholesale) plants an unpaid GST invoice past 150 days (Pune Office Supplies): under the
 * GST 180-day rule its credit is reversed unless the supplier is paid in time, so Recoveries lists a payment deadline.
 * The walk: Found → a person takes it (Being fixed) → the payment is recorded in Helm (a person's mark, the evidence)
 * → "Check now" → Verified, with the reason. A click on Recoveries never verifies anything.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { newCustomer, signInAs, standIn, type Customer } from "../support/journey";

let customer: Customer;
let sampleWsId = "";
let bookId = "";

interface Issue {
  id: string;
  kind: string;
  state: string;
  title: string;
  work_item_id: string | null;
  details: Record<string, unknown>;
}

const SAMPLE_SLUG = "sample-meridian";
const page_ = (c: Customer): string => `/${c.orgSlug}/${SAMPLE_SLUG}/recoveries`;

const issues = async (): Promise<Issue[]> =>
  (await api<{ items: Issue[] }>(customer.session, "GET", `/workspaces/${sampleWsId}/recoveries`)).body.items;

test.describe("Recoveries", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    customer = await newCustomer("recoveries", "Recoveries Traders Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "3");
    const base = `/organizations/${customer.orgId}/helm`;
    const built = await api(customer.session, "POST", `${base}/sample`);
    expect(built.status, built.text.slice(0, 300)).toBe(202);
    await expect
      .poll(async () => {
        const overview = await api<{ sample: { book_id: string | null; workspace_id: string | null; building: boolean } }>(
          customer.session, "GET", base);
        bookId = overview.body.sample?.book_id ?? "";
        sampleWsId = overview.body.sample?.workspace_id ?? "";
        return Boolean(bookId) && Boolean(sampleWsId) && !overview.body.sample.building;
      }, { timeout: 300_000, intervals: [3_000, 5_000] })
      .toBe(true);
  });

  test("an issue walks from found to verified, on evidence", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(page_(customer));
    await expect(page.getByRole("heading", { level: 1, name: "Recoveries" })).toBeVisible();
    await settle(page);

    const deadline = (await issues()).find((i) => i.kind === "PAYMENT_DEADLINE" && i.details.rule === "GST_180" && i.state === "FOUND");
    expect(deadline, "the sample's unpaid GST invoice is a payment deadline").toBeTruthy();
    const found = page.getByTestId("recoveries-column-FOUND");
    await expect(found.getByText(deadline!.title)).toBeVisible();
    await expect(page.getByTestId("recoveries-found")).not.toContainText("—");

    // A person takes it: Being fixed. Nothing is verified by that.
    await found.getByText(deadline!.title).click();
    const detail = page.getByTestId("recovery-detail");
    await expect(detail.getByRole("heading", { name: deadline!.title })).toBeVisible();
    await expect(detail).toContainText("GST 180-day rule");
    await detail.getByTestId("recovery-owner").selectOption({ label: customer.email });
    await expect(page.getByTestId("recoveries-column-BEING_FIXED").getByText(deadline!.title)).toBeVisible();
    await expect(page.getByTestId("recoveries-column-VERIFIED").getByText(deadline!.title)).toHaveCount(0);

    // The next step opens Helm's plan; the payment is recorded there (a person's mark, with its date).
    await expect(detail.getByRole("link", { name: "Plan the payment in Helm (a person approves)" }))
      .toHaveAttribute("href", `/${customer.orgSlug}/helm/plan`);
    const today = new Date().toISOString().slice(0, 10);
    const paid = await api(customer.session, "POST",
      `/organizations/${customer.orgId}/helm/books/${bookId}/invoices/${deadline!.work_item_id}/paid`, { paid_on: today });
    expect(paid.status, paid.text.slice(0, 300)).toBe(200);

    // "Check now" reads the evidence: Verified, with the reason in plain words.
    await expect
      .poll(async () => {
        await page.getByTestId("recoveries-check").click();
        await settle(page);
        return page.getByTestId("recoveries-column-VERIFIED").getByText(deadline!.title).count();
      }, { timeout: 120_000, intervals: [3_000, 5_000] })
      .toBe(1);
    await page.getByTestId("recoveries-column-VERIFIED").getByText(deadline!.title).click();
    await expect(page.getByTestId("recovery-reason")).toContainText(`Paid on ${today}, on time`);
    await expect(page.getByTestId("recovery-detail")).toContainText("Verified by evidence, with no money of its own to count");
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`no serious or critical violation, ${scheme} theme`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, customer.email);
      await page.goto(page_(customer));
      await expect(page.getByTestId("recoveries-board")).toBeVisible();
      await page.getByTestId("recovery-card").first().click();
      await expect(page.getByTestId("recovery-detail")).toBeVisible();
      await page.getByRole("button", { name: /closed without money/ }).click();
      await settle(page);
      const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include("main").analyze();
      expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
        JSON.stringify(axe.violations, null, 2)).toEqual([]);
    });
  }
});
