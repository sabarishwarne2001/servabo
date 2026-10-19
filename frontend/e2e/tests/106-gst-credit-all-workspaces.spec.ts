/**
 * GST CREDIT ACROSS EVERY WORKSPACE (Enterprise): Organization -> "GST credit, all workspaces".
 *
 * One reconciliation per GSTIN. A GSTR-2B is imported in "Main"; the purchase invoices are booked in two workspaces:
 *   A-1001  in Main, reported                       -> Matched
 *   B-2002  in Branch, reported                     -> Matched (Main alone would call it "not in your books")
 *   C-3003  in Branch, never reported               -> Waiting for supplier
 *   X-9     reported, never received                -> Not in your books
 * Also: the plan (a Business customer sees the lock), roles (members are refused), and accessibility in both themes.
 * The invoices are real PDFs read by the worker with the model stand-in, like spec 105.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { runId } from "../support/env";
import { gstin, gstr2b } from "../support/gst";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

const BUYER = gstin("27", "AAACG1234F");
const S1 = gstin("27", "AABCS5555K");
const S2 = gstin("29", "AAGCD7777P");
const S3 = gstin("27", "AABFR8841M");

let customer: Customer;
let branchId: string;
let memberEmail: string;

const invoiceLines = (vendor: string, vendorGstin: string, number: string, date: string, taxable: number): string[] => {
  const half = Math.round(taxable * 0.09 * 100) / 100;
  const total = (taxable + half * 2).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return [
    "TAX INVOICE", `Vendor: ${vendor}`, `Vendor GSTIN: ${vendorGstin}`, "Bill To: Allworkspaces Traders Ltd", `Buyer GSTIN: ${BUYER}`,
    `Invoice Number: ${number}`, `Invoice Date: ${date}`, "Currency: INR", `Taxable value: ${taxable.toFixed(2)}`,
    `CGST: ${half.toFixed(2)}`, `SGST: ${half.toFixed(2)}`, `Total Amount Due: INR ${total}`,
  ];
};

const bookIn = async (workspaceId: string, vendor: string, vendorGstin: string, number: string, date: string, taxable: number): Promise<void> => {
  const form = new FormData();
  form.append("file", new Blob([new Uint8Array(buildPdf([invoiceLines(vendor, vendorGstin, number, date, taxable)]))],
    { type: "application/pdf" }), `${number}.pdf`);
  const sent = await api(customer.session, "POST", `/workspaces/${workspaceId}/work-items`, form);
  expect(sent.status, sent.text.slice(0, 300)).toBe(201);
};

const statement = (): string =>
  gstr2b(BUYER, "2026-09", [
    { gstin: S1, name: "Sahyadri Packaging", docs: [
      { number: "A-1001", date: "2026-09-05", taxable: 1000 },
      { number: "B-2002", date: "2026-09-10", taxable: 500 },
    ] },
    { gstin: S3, name: "Rajput Hardware Stores", docs: [{ number: "X-9", date: "2026-09-18", taxable: 300 }] },
  ]);

const open = async (page: import("@playwright/test").Page, tab = ""): Promise<void> => {
  await page.goto(`${customer.org("gst")}${tab ? `?tab=${tab}` : ""}`);
  await expect(page.getByRole("heading", { level: 1, name: "GST credit, all workspaces" })).toBeVisible();
  await settle(page);
};

const figureValue = (page: import("@playwright/test").Page, key: string) => page.getByTestId(`gst-figure-${key}-value`);

test.describe("GST Credit across every workspace", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(540_000);
    customer = await newCustomer("gstall", "Allworkspaces Traders Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "4");
    const branch = await api<{ id: string }>(customer.session, "POST", `/organizations/${customer.orgId}/workspaces`, { workspace_name: `Branch ${runId()}` });
    expect(branch.status, branch.text).toBe(201);
    branchId = branch.body.id;
    memberEmail = (await addMember(customer, "gst-all-member", "MEMBER", "VIEWER")).email;
    await bookIn(customer.wsId, "Sahyadri Packaging", S1, "A-1001", "2026-09-05", 1000);
    await bookIn(branchId, "Sahyadri Packaging", S1, "B-2002", "2026-09-10", 500);
    await bookIn(branchId, "Deccan Plastics", S2, "C-3003", "2026-09-12", 700);
    const form = new FormData();
    form.append("file", new Blob([statement()], { type: "application/json" }), "GSTR2B_092026.json");
    const imported = await api(customer.session, "POST", `/workspaces/${customer.wsId}/gst/returns`, form);
    expect(imported.status, imported.text).toBe(200);
  });

  test("the books of both workspaces are matched with the one return", async ({ page }) => {
    await signInAs(page, customer.email);
    await expect.poll(async () => {
      const session = await apiLogin(customer.email);
      const rows = await api<{ items: Array<{ number: string; status: string }> }>(session, "GET", `/organizations/${customer.orgId}/gst/records?limit=100`);
      return Object.fromEntries((rows.body.items ?? []).map((row) => [row.number, row.status]));
    }, { timeout: 420_000, intervals: [3_000, 5_000] }).toMatchObject({
      "A-1001": "MATCHED", "B-2002": "MATCHED", "C-3003": "WAITING_FOR_SUPPLIER", "X-9": "NOT_IN_BOOKS",
    });

    await open(page);
    await expect(page.getByTestId("gst-figures")).toBeVisible();
    await expect(figureValue(page, "claimable_now")).toHaveText("₹270.00");   // A-1001 (180) + B-2002 (90)
    await expect(figureValue(page, "waiting")).toHaveText("₹126.00");          // C-3003
    await expect(figureValue(page, "not_in_books")).toHaveText("1");
    await expect(page.getByTestId("gst-org-scope")).toContainText("Last import");
    await expect(page.getByTestId("gst-org-workspace-row")).toHaveCount(2);
    await expect(page.getByTestId("gst-org-workspaces")).toContainText("Main");
    await expect(page.getByTestId("gst-org-workspaces")).toContainText("Branch");

    await open(page, "invoices");
    await expect(page.getByTestId("gst-org-line-row")).toHaveCount(4);
    await expect(page.getByTestId("gst-org-line-row").filter({ hasText: "B-2002" })).toContainText("Branch");
    await page.getByRole("button", { name: "Waiting for supplier" }).click();
    await expect(page.getByTestId("gst-org-line-row")).toHaveCount(1);
    await expect(page.getByTestId("gst-org-line-row").first()).toContainText("C-3003");

    await open(page, "suppliers");
    await expect(page.getByTestId("gst-org-supplier-row").first()).toContainText("Deccan Plastics");
    await expect(page.getByText("Section 16(2)(aa)").first()).toBeVisible();
  });

  test("the sidebar offers the page to an owner", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("audit"));
    await settle(page);
    await expect(page.getByRole("link", { name: "GST credit, all workspaces" })).toBeVisible();
  });

  test("a member of the organization is refused", async ({ page, problems }) => {
    problems.allowHttp(/\/organizations\/[^/]+\/gst\//, [403], "a member may not read the organization's GST credit");
    const session = await apiLogin(memberEmail);
    expect((await api(session, "GET", `/organizations/${customer.orgId}/gst/summary`)).status).toBe(403);
    await signInAs(page, memberEmail);
    await page.goto(customer.org("gst"));
    await settle(page);
    await expect(page.getByTestId("gst-figures")).toHaveCount(0);
  });

  test("on a Business plan the page says it is part of Enterprise and the API asks for an upgrade", async ({ page, problems }) => {
    problems.allowHttp(/\/organizations\/[^/]+\/gst\//, [402], "the plan has no GST credit across workspaces");
    const small = await newCustomer("gstallbiz", "Business Plan Traders Ltd");
    standIn("subscribe", small.orgSlug, "--plan", "business", "--seats", "2");
    const session = await apiLogin(small.email);
    expect((await api(session, "GET", `/organizations/${small.orgId}/gst/summary`)).status).toBe(402);
    await signInAs(page, small.email);
    await page.goto(small.org("gst"));
    await expect(page.getByTestId("gst-org-lock")).toContainText("Enterprise");
    await page.getByRole("button", { name: "See what Enterprise adds" }).click();
    await expect(page.getByRole("alertdialog")).toContainText(/Enterprise/);
    await page.keyboard.press("Escape");
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, customer.email);
      const found: string[] = [];
      for (const tab of ["workspaces", "suppliers", "invoices"]) {
        await open(page, tab);
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        for (const v of results.violations) {
          if (v.impact === "serious" || v.impact === "critical") found.push(`${tab} ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
          else testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${tab}: ${v.id} (${v.nodes.length})` });
        }
      }
      expect(found, "GST credit, all workspaces, with serious or critical accessibility violations").toEqual([]);
    });
  }
});
