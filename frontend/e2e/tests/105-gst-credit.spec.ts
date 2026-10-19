/**
 * GST CREDIT (Documents -> GST credit): import a GSTR-2B and read the six figures, confirm a suggested match and mark
 * a record "not ours", export to Excel, the Developer-plan preview (figures open, lists locked, the upgrade dialog),
 * viewers, other workspaces, and accessibility in both themes.
 *
 * Set-up (a Business-plan customer of its own): four real invoice PDFs are uploaded and read by the worker (the model
 * stand-in reads "Vendor GSTIN", "Buyer GSTIN", "Taxable value", "CGST", "SGST"), then a GSTR-2B is imported:
 *   A-1001  reported exactly                  -> Matched
 *   B-2002  reported as B-2001                -> Suggested (a person confirms)
 *   C-3003  never reported                    -> Waiting for supplier
 *   D-4004  reported 100 higher               -> Differences
 *   X-9     reported, never received          -> Not in your books
 * The file format is invented to match the documented shape; it is unverified against a real portal download.
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
const S3 = gstin("27", "AABFR8841M");
const PERIOD = "2026-09";

let customer: Customer;
let viewerEmail: string;

const invoiceLines = (vendor: string, vendorGstin: string, number: string, date: string, taxable: number): string[] => {
  const half = Math.round(taxable * 0.09 * 100) / 100;
  const total = (taxable + half * 2).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return [
    "TAX INVOICE", `Vendor: ${vendor}`, `Vendor GSTIN: ${vendorGstin}`, "Bill To: GST Credit Traders Ltd", `Buyer GSTIN: ${BUYER}`,
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
    { gstin: S3, name: "Rajput Hardware Stores", docs: [{ number: "X-9", date: "2026-09-18", taxable: 300 }] },
  ]);

const upload = async (c: Customer, text: string, name = "GSTR2B_092026.json") => {
  const form = new FormData();
  form.append("file", new Blob([text], { type: "application/json" }), name);
  return api<{ results: Array<{ status: string; record_count: number }> }>(c.session, "POST", `/workspaces/${c.wsId}/gst/returns`, form);
};

const open = async (page: import("@playwright/test").Page, c: Customer, tab = ""): Promise<void> => {
  await page.goto(`${c.ws("gst")}${tab ? `?tab=${tab}` : ""}`);
  await expect(page.getByRole("heading", { level: 1, name: "GST credit" })).toBeVisible();
  await settle(page);
};

const figureValue = (page: import("@playwright/test").Page, key: string) => page.getByTestId(`gst-figure-${key}-value`);

test.describe("GST Credit", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(540_000);
    customer = await newCustomer("gstcredit", "GST Credit Traders Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "4");
    const viewer = await addMember(customer, "gst-viewer", "MEMBER", "VIEWER");
    viewerEmail = viewer.email;
    for (const [vendor, vendorGstin, number, date, taxable] of BOOKS) {
      const form = new FormData();
      form.append("file", new Blob([new Uint8Array(buildPdf([invoiceLines(vendor, vendorGstin, number, date, taxable)]))],
        { type: "application/pdf" }), `${number}.pdf`);
      const sent = await api(customer.session, "POST", `/workspaces/${customer.wsId}/work-items`, form);
      expect(sent.status, sent.text.slice(0, 300)).toBe(201);
    }
  });

  test("the empty page explains how to download GSTR-2B, then an import shows the six figures", async ({ page }) => {
    await signInAs(page, customer.email);
    await open(page, customer);
    const empty = page.getByTestId("gst-empty");
    await expect(empty).toContainText("Returns Dashboard");
    await expect(empty).toContainText("not tax advice");
    await expect(page.getByRole("button", { name: "Explore with the sample company" })).toBeVisible();

    await page.getByTestId("gst-import-input").setInputFiles({
      name: "GSTR2B_092026.json", mimeType: "application/json", buffer: Buffer.from(statement()),
    });
    const result = page.getByTestId("gst-import-result");
    await expect(result).toContainText("September 2026");
    await expect(result).toContainText("4 records");

    // The worker has read the four invoices (or reads them now): the recompute settles the figures.
    await expect.poll(async () => {
      const session = await apiLogin(customer.email);
      const rows = await api<{ items: Array<{ number: string; status: string }> }>(session, "GET", `/workspaces/${customer.wsId}/gst/records?limit=100`);
      return Object.fromEntries(rows.body.items.map((row) => [row.number, row.status]));
    }, { timeout: 420_000, intervals: [3_000, 5_000] }).toMatchObject({
      "A-1001": "MATCHED", "B-2001": "SUGGESTED", "D-4004": "MATCHED_WITH_DIFFERENCES", "C-3003": "WAITING_FOR_SUPPLIER", "X-9": "NOT_IN_BOOKS",
    });

    await page.reload();
    await settle(page);
    await expect(page.getByTestId("gst-figures")).toBeVisible();
    await expect(figureValue(page, "claimable_now")).toHaveText("₹540.00");   // A-1001 (180) + D-4004 at the books' figure (360)
    await expect(figureValue(page, "waiting")).toHaveText("₹126.00");          // C-3003
    await expect(page.getByTestId("gst-figure-waiting-count")).toContainText("1 invoice · 1 supplier");
    await expect(figureValue(page, "differences")).toHaveText("₹18.00");       // 100 of taxable at 18%
    await expect(figureValue(page, "not_in_books")).toHaveText("1");
    await expect(figureValue(page, "not_eligible")).toHaveText("₹0.00");
    await expect(figureValue(page, "at_risk_180")).toHaveText("₹0.00");
    for (const law of ["Section 16(2)(aa)", "Second proviso to Section 16(2)", "Section 16(4)"]) {
      await expect(page.getByRole("link", { name: new RegExp(law.replace(/[()]/g, "\\$&")) }).first()).toBeVisible();
    }
    await expect(page.getByTestId("gst-scope")).toContainText("Last import");
  });

  test("importing the exact same file again changes nothing, and a bad file is refused in words", async ({ page, problems }) => {
    problems.allowHttp(/\/gst\/returns/, [422], "a file that is not JSON is refused in words");
    await signInAs(page, customer.email);
    await open(page, customer);
    await page.getByTestId("gst-import-input").setInputFiles({ name: "again.json", mimeType: "application/json", buffer: Buffer.from(statement()) });
    await expect(page.getByTestId("gst-import-result")).toContainText("already imported");
    await page.getByTestId("gst-import-input").setInputFiles({ name: "bad.json", mimeType: "application/json", buffer: Buffer.from("{ nope") });
    await expect(page.getByTestId("gst-import-error")).toContainText("not a readable JSON file");
  });

  test("Invoices: confirm a suggested match; mark a record not ours", async ({ page }) => {
    await signInAs(page, customer.email);
    await open(page, customer, "invoices");
    const row = (number: string) => page.getByTestId("gst-line-row").filter({ hasText: number });

    await expect(row("B-2001")).toContainText("Suggested");
    await row("B-2001").getByRole("button", { name: "B-2001" }).click();
    const drawer = page.getByTestId("gst-drawer");
    await expect(drawer).toContainText("Your books");
    await expect(drawer).toContainText("GSTR-2B");
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);

    await row("B-2001").getByRole("button", { name: "B-2001" }).click();
    await page.getByRole("button", { name: "Confirm this match" }).click();
    await expect(page.getByText("Decision saved.").first()).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(row("B-2001")).toContainText("Matched");

    // The difference is shown side by side, highlighted.
    await row("D-4004").getByRole("button", { name: "D-4004" }).click();
    await expect(page.getByTestId("gst-drawer").locator("tr[data-different='true']").first()).toContainText("Taxable value");
    await expect(page.getByTestId("gst-ims")).toContainText("Keep pending");
    await page.keyboard.press("Escape");

    await row("X-9").getByRole("button", { name: "X-9" }).click();
    await expect(page.getByTestId("gst-ims")).toContainText("Keep pending");
    await page.getByRole("button", { name: "Not ours", exact: true }).click();
    await expect(page.getByText("Decision saved.").first()).toBeVisible();
    await expect(page.getByTestId("gst-ims")).toContainText("Reject");
    await page.keyboard.press("Escape");

    await page.reload();
    await settle(page);
    await expect(row("B-2001")).toContainText("Matched");
    const session = await apiLogin(customer.email);
    const lines = await api<{ items: Array<{ number: string; decision: string | null; ims_action: string | null }> }>(
      session, "GET", `/workspaces/${customer.wsId}/gst/records?limit=100`);
    const x9 = lines.body.items.find((line) => line.number === "X-9");
    expect([x9?.decision, x9?.ims_action]).toEqual(["NOT_OURS", "REJECT"]);

    await open(page, customer);
    await expect(figureValue(page, "not_in_books")).toHaveText("0");
    await expect(figureValue(page, "claimable_now")).toHaveText("₹630.00");   // 540 + B-2001's 90, now confirmed
  });

  test("Suppliers: who has not reported, with a drafted reminder that sends nothing", async ({ page }) => {
    await signInAs(page, customer.email);
    await open(page, customer, "suppliers");
    const rows = page.getByTestId("gst-supplier-row");
    await expect(rows.first()).toContainText("Deccan Plastics");
    await expect(rows.first()).toContainText("₹126.00");
    await rows.first().getByRole("button", { name: "Draft a reminder" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("C-3003");
    await expect(dialog).toContainText("No email contact is known");
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toHaveCount(0);
  });

  test("IMS actions list what to do on the portal, with the reason", async ({ page }) => {
    await signInAs(page, customer.email);
    await open(page, customer, "ims");
    await expect(page.getByTestId("gst-ims-tab")).toContainText("not tax advice");
    await page.getByRole("button", { name: /^Reject \(/ }).click();
    await expect(page.getByTestId("gst-ims-row")).toContainText("X-9");
    await expect(page.getByTestId("gst-ims-row")).toContainText("not ours");
    await page.getByRole("button", { name: /^Accept \(/ }).click();
    await expect(page.getByTestId("gst-ims-row").first()).toContainText("Matches your books");
  });

  test("Export to Excel downloads a workbook", async ({ page }) => {
    await signInAs(page, customer.email);
    await open(page, customer);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export to Excel" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^gst-credit-.*\.xlsx$/);
    const path = await file.path();
    const bytes = (await import("node:fs")).readFileSync(path);
    expect(bytes.subarray(0, 2).toString()).toBe("PK");   // an xlsx is a zip
    expect(bytes.length).toBeGreaterThan(2_000);
  });

  test("a viewer reads everything but cannot import, decide or export", async ({ page }) => {
    await signInAs(page, viewerEmail);
    await open(page, customer);
    await expect(page.getByTestId("gst-figures")).toBeVisible();
    await expect(page.getByRole("button", { name: "Export to Excel" })).toBeDisabled();
    await expect(page.getByTestId("gst-import-input")).toBeDisabled();
    await open(page, customer, "invoices");
    await page.getByTestId("gst-line-row").first().getByRole("button").first().click();
    await expect(page.getByRole("button", { name: "Not ours", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Confirm this match" })).toHaveCount(0);
    const session = await apiLogin(viewerEmail);
    expect((await upload({ ...customer, session }, statement(), "viewer.json")).status).toBe(403);
    const refused = await api(session, "GET", `/workspaces/${customer.wsId}/gst/export.xlsx`);
    expect(refused.status).toBe(403);
  });

  test("on a Developer plan the figures are open, the lists are locked and the upgrade dialog opens", async ({ page }) => {
    const small = await newCustomer("gstdev", "GST Starter Traders Ltd");
    standIn("subscribe", small.orgSlug, "--plan", "developer", "--seats", "1");
    expect((await upload(small, statement())).status).toBe(200);
    await signInAs(page, small.email);
    await open(page, small);
    await expect(page.getByTestId("gst-figures")).toBeVisible();
    await expect(figureValue(page, "not_in_books")).toHaveText("4");   // nothing of theirs is read yet: 4 reported records are unseen
    for (const tab of ["suppliers", "invoices", "ims"]) {
      await page.goto(`${small.ws("gst")}?tab=${tab}`);
      await expect(page.getByTestId("gst-preview-lock")).toContainText("Business and Enterprise add");
    }
    await page.getByRole("button", { name: "See what Business adds" }).click();
    await expect(page.getByRole("alertdialog")).toContainText(/Business/);
    await page.keyboard.press("Escape");
    const session = await apiLogin(small.email);
    expect((await api(session, "GET", `/workspaces/${small.wsId}/gst/records`)).status).toBe(402);
    expect((await api(session, "GET", `/workspaces/${small.wsId}/gst/export.xlsx`)).status).toBe(402);
    const body = (await api<{ access: { preview: boolean } }>(session, "GET", `/workspaces/${small.wsId}/gst/summary`)).body;
    expect(body.access.preview).toBe(true);
  });

  test("another customer cannot see this workspace's data", async ({ page, problems }) => {
    problems.allowHttp(/\/api\/v1\//, [403, 404], "the workspace is not theirs");
    const other = await newCustomer("gstother", "Somebody Else Ltd");
    const session = await apiLogin(other.email);
    for (const tail of ["summary", "records", "suppliers", "returns", "export.xlsx"]) {
      const response = await api(session, "GET", `/workspaces/${customer.wsId}/gst/${tail}`);
      expect([403, 404], `${tail}: ${response.text.slice(0, 120)}`).toContain(response.status);
    }
    expect([403, 404]).toContain((await upload({ ...customer, session }, statement(), "intruder.json")).status);
    await signInAs(page, other.email);
    await page.goto(customer.ws("gst"));
    await settle(page);
    await expect(page.getByTestId("gst-figures")).toHaveCount(0);
    const own = await api<{ gstins: string[] }>(session, "GET", `/workspaces/${other.wsId}/gst/summary`);
    expect(own.body.gstins).toEqual([]);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, customer.email);
      const found: string[] = [];
      for (const tab of ["suppliers", "invoices", "ims"]) {
        await open(page, customer, tab);
        if (tab === "invoices") {
          await page.getByTestId("gst-line-row").first().getByRole("button").first().click();
          await expect(page.getByTestId("gst-drawer")).toBeVisible();
        }
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        for (const v of results.violations) {
          if (v.impact === "serious" || v.impact === "critical") found.push(`${tab} ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
          else testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${tab}: ${v.id} (${v.nodes.length})` });
        }
      }
      expect(found, "GST credit with serious or critical accessibility violations").toEqual([]);
    });
  }
});
