/**
 * THE VALUE RECEIPT (Session G): what Servabo found in the customer's own documents, in rupees, at the moments that
 * decide a purchase (the trial's last days, its end, the plan page) and every month after (the Overview).
 *
 * Set-up (a Free-plan customer of its own, on the one-week trial): four real invoice PDFs are uploaded and read by the
 * worker, then a GSTR-2B is imported (the same shape as spec 105):
 *   A-1001  reported exactly       -> claimable (180)
 *   B-2002  reported as B-2001     -> suggested (a person confirms; not claimable yet)
 *   C-3003  never reported         -> waiting for the supplier (700 x 18% = 126)
 *   D-4004  reported 100 higher    -> claimable at the books' figure (360)
 * so the receipt reads: 4 documents read, ₹126 of GST credit waiting on 1 supplier, ₹540 claimable now.
 *
 * Checked: the banner's headline in the last days; the receipt card in the "trial has ended" dialog with a working
 * link to the GST page; a member sees no figures anywhere (and the server refuses the member); the Overview's
 * "Found this month" card and the plan page's "Your trial so far" card; the PDF; axe in both themes.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { gstin, gstr2b } from "../support/gst";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

const BUYER = gstin("27", "AAACG1234F");
const S1 = gstin("27", "AABCS5555K");
const S2 = gstin("29", "AAGCD7777P");
const PERIOD = "2026-09";

const HEADLINE = "In your trial Servabo read 4 documents and found ₹126 of GST credit waiting on 1 supplier.";

let customer: Customer;
let memberEmail: string;

const invoiceLines = (vendor: string, vendorGstin: string, number: string, date: string, taxable: number): string[] => {
  const half = Math.round(taxable * 0.09 * 100) / 100;
  const total = (taxable + half * 2).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return [
    "TAX INVOICE", `Vendor: ${vendor}`, `Vendor GSTIN: ${vendorGstin}`, "Bill To: Receipt Traders Ltd", `Buyer GSTIN: ${BUYER}`,
    `Invoice Number: ${number}`, `Invoice Date: ${date}`, "Currency: INR", `Taxable value: ${taxable.toFixed(2)}`,
    `CGST: ${half.toFixed(2)}`, `SGST: ${half.toFixed(2)}`, `Total Amount Due: INR ${total}`,
  ];
};

const BOOKS: readonly (readonly [string, string, string, string, number])[] = [
  ["Sahyadri Packaging", S1, "A-1001", "2026-09-05", 1000],
  ["Sahyadri Packaging", S1, "B-2002", "2026-09-10", 500],
  ["Deccan Plastics", S2, "C-3003", "2026-09-12", 700],
  ["Sahyadri Packaging", S1, "D-4004", "2026-09-15", 2000],
];

const statement = (): string =>
  gstr2b(BUYER, PERIOD, [
    { gstin: S1, name: "Sahyadri Packaging", docs: [
      { number: "A-1001", date: "2026-09-05", taxable: 1000 },
      { number: "B-2001", date: "2026-09-10", taxable: 500 },
      { number: "D-4004", date: "2026-09-15", taxable: 2100 },
    ] },
  ]);

test.describe("The value receipt", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(540_000);
    customer = await newCustomer("receipt", "Receipt Traders Ltd");
    const member = await addMember(customer, "receipt-member", "MEMBER", "VIEWER");
    memberEmail = member.email;
    for (const [vendor, vendorGstin, number, date, taxable] of BOOKS) {
      const form = new FormData();
      form.append("file", new Blob([new Uint8Array(buildPdf([invoiceLines(vendor, vendorGstin, number, date, taxable)]))],
        { type: "application/pdf" }), `${number}.pdf`);
      const sent = await api(customer.session, "POST", `/workspaces/${customer.wsId}/work-items`, form);
      expect(sent.status, sent.text.slice(0, 300)).toBe(201);
    }
    const form = new FormData();
    form.append("file", new Blob([statement()], { type: "application/json" }), "GSTR2B_092026.json");
    const imported = await api(customer.session, "POST", `/workspaces/${customer.wsId}/gst/returns`, form);
    expect(imported.status, imported.text.slice(0, 300)).toBe(200);
    // The six figures are open on every plan (the lists are Business's): wait until the worker has read all four invoices.
    await expect.poll(async () => {
      const session = await apiLogin(customer.email);
      const summary = await api<{ figures?: Array<{ key: string; count: number }> }>(session, "GET", `/workspaces/${customer.wsId}/gst/summary`);
      const counts = Object.fromEntries((summary.body.figures ?? []).map((f) => [f.key, f.count]));
      return [counts.claimable_now, counts.waiting];
    }, { timeout: 420_000, intervals: [3_000, 5_000] }).toEqual([2, 1]);
    standIn("trial-ending", customer.orgSlug);       // two days left
  });

  test("the last days: the banner says what Servabo found, and the figures are the stored ones", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws());
    const banner = page.getByTestId("trial-banner");
    await expect(banner).toContainText("Your free trial ends in 2 days", { timeout: 15_000 });
    await expect(page.getByTestId("trial-banner-headline")).toHaveText(HEADLINE);
    await expect(banner.getByRole("link", { name: "Choose a plan" })).toBeVisible();

    const session = await apiLogin(customer.email);
    const receipt = await api<{ headline: string; work: { documents: number }; also_on_business: string[];
      found: Array<{ key: string; amount_text: string; count: number; source: string }> }>(
      session, "GET", `/organizations/${customer.orgId}/value-receipt?period=trial`);
    expect(receipt.status).toBe(200);
    expect(receipt.body.work.documents).toBe(4);
    expect(receipt.body.found.map((f) => [f.key, f.amount_text])).toEqual([["gst_waiting", "₹126"], ["gst_claimable", "₹540"]]);
    expect(receipt.body.found[0]?.source).toBe(`/${customer.orgSlug}/${customer.wsSlug}/gst`);
    expect(receipt.body.also_on_business).toEqual(["Payment risks", "Prices checked against purchase orders", "Helm's full planning", "GST's supplier list"]);
  });

  test("a member keeps today's banner, sees no figure, and the server refuses the member", async ({ page, problems }) => {
    problems.allowHttp(/\/value-receipt/, [403], "a member may not read the organization's receipt");
    await signInAs(page, memberEmail);
    await page.goto(customer.ws());
    await expect(page.getByTestId("trial-banner")).toContainText("Your free trial ends in 2 days", { timeout: 15_000 });
    await expect(page.getByTestId("trial-banner-headline")).toHaveCount(0);
    await expect(page.getByTestId("trial-banner")).not.toContainText("₹");
    const session = await apiLogin(memberEmail);
    const refused = await api(session, "GET", `/organizations/${customer.orgId}/value-receipt?period=trial`);
    expect(refused.status).toBe(403);
  });

  test("the plan page shows 'Your trial so far' above the plans", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    const card = page.getByTestId("billing-trial-receipt");
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card).toContainText("Your trial so far");
    await expect(card).toContainText(HEADLINE);
    await expect(card.getByTestId("value-receipt-amount-gst_claimable")).toHaveText("₹540");
    // above the plan cards
    const cardBox = await card.boundingBox();
    const plans = await page.getByRole("list", { name: /allowances/ }).first().boundingBox();
    expect(cardBox && plans && cardBox.y < plans.y).toBeTruthy();
  });

  test("the Overview shows 'Found this month' on every plan, with the evidence one click away", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws());
    const card = page.getByTestId("overview-found-month");
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card).toContainText("Found this month");
    await expect(card.getByTestId("value-receipt-amount-gst_waiting")).toHaveText("₹126");
    await expect(card.getByTestId("overview-found-month-work")).toContainText("4 documents read");
    await card.getByRole("link", { name: /See the evidence for GST credit waiting/ }).click();
    await expect(page).toHaveURL(new RegExp(`${customer.ws("gst")}$`));
    await expect(page.getByRole("heading", { level: 1, name: "GST credit" })).toBeVisible();
  });

  test("the Overview card is not shown to a member", async ({ page }) => {
    await signInAs(page, memberEmail);
    await page.goto(customer.ws());
    await expect(page.getByTestId("kpi-total")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("overview-found-month")).toHaveCount(0);
  });

  test("the receipt downloads as a one-page PDF with the same figures", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws());
    const card = page.getByTestId("overview-found-month");
    await expect(card).toBeVisible({ timeout: 15_000 });
    const download = page.waitForEvent("download");
    await card.getByRole("button", { name: "Download as PDF" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^servabo-value-receipt-.*\.pdf$/);
    const session = await apiLogin(customer.email);
    const pdf = await api(session, "GET", `/organizations/${customer.orgId}/value-receipt.pdf?period=trial`);
    expect(pdf.status).toBe(200);
  });

  test("the end: a dialog with the receipt card, and its link opens the evidence", async ({ page }) => {
    standIn("trial-ends", customer.orgSlug, "--backdate-days", "3");   // the work moves with the clock
    await signInAs(page, customer.email);
    await page.goto(customer.ws());
    const dialog = page.getByRole("alertdialog", { name: "Your free trial has ended" });
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog).toContainText("Nothing has been deleted");
    await expect(dialog.getByTestId("trial-ended-receipt-headline")).toHaveText(HEADLINE);
    await expect(dialog.getByTestId("value-receipt-amount-gst_waiting")).toHaveText("₹126");
    await expect(dialog.getByTestId("trial-ended-receipt-business")).toContainText("Business also checks: Payment risks");
    await expect(dialog.getByRole("button", { name: "Choose a plan" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Continue read-only" })).toBeVisible();

    await dialog.getByRole("link", { name: /See the evidence for GST credit waiting/ }).click();
    await expect(page).toHaveURL(new RegExp(`${customer.ws("gst")}$`));
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("heading", { level: 1, name: "GST credit" })).toBeVisible();
  });

  test("the end, as a member: today's dialog, no figures", async ({ page }) => {
    await signInAs(page, memberEmail);
    await page.goto(customer.ws());
    const dialog = page.getByRole("alertdialog", { name: "Your free trial has ended" });
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByTestId("trial-ended-receipt")).toHaveCount(0);
    await expect(dialog).not.toContainText("₹");
    await expect(dialog.getByRole("button", { name: "Continue read-only" })).toBeVisible();
  });

  test("the plan page after the end still shows the trial's receipt", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    await expect(page.getByTestId("billing-trial-receipt")).toContainText(HEADLINE, { timeout: 15_000 });
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, customer.email);
      const found: string[] = [];
      const scan = async (where: string): Promise<void> => {
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        for (const v of results.violations) {
          if (v.impact === "serious" || v.impact === "critical") found.push(`${where} ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
          else testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${where}: ${v.id} (${v.nodes.length})` });
        }
      };
      await page.goto(customer.ws());
      await expect(page.getByRole("alertdialog", { name: "Your free trial has ended" })).toBeVisible({ timeout: 15_000 });
      await scan("the ended dialog");
      await page.getByRole("button", { name: "Continue read-only" }).click();
      await expect(page.getByTestId("overview-found-month")).toBeVisible();
      await settle(page);
      await scan("the Overview");
      await page.goto(customer.org("billing"));
      await expect(page.getByTestId("billing-trial-receipt")).toBeVisible({ timeout: 15_000 });
      await scan("the plan page");
      expect(found, "the value receipt with serious or critical accessibility violations").toEqual([]);
    });
  }
});
