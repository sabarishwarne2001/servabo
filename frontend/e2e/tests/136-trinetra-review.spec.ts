/** Synthetic end-to-end review. The organization is enrolled in the pilot by the platform operator, as a launch would do it (Final 2T);
 *  the old TRINETRA_LIVE_ENABLED alias still opens it too. */
import AxeBuilder from "@axe-core/playwright";
import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";
import { enrol } from "../support/trinetra";
let customer: Customer;
let invoiceId: string;
let statementId: string;
let adviceId: string;
let accountingId: string;
test.describe("TRINETRA reviewed evidence", () => {
  test.setTimeout(240_000);
  test.beforeAll(async () => {
    customer = await newCustomer("trinetra", "Synthetic Trinetra Services Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "2");
    await enrol(customer.orgId);
    const documents = [
      {
        name: "TRINETRA-INVOICE.pdf",
        lines: [
          "INVOICE",
          "Vendor: Synthetic Trinetra Services Ltd",
          "Vendor PAN: ABCDE1234F",
          "Bill To: Synthetic Deductor Ltd",
          "Invoice Number: TRINETRA-001",
          "Invoice Date: 2026-03-01",
          "Currency: INR",
          "Total Amount Due: INR 118000.00",
        ],
      },
      {
        name: "TRINETRA-ADVICE.pdf",
        lines: [
          "SYNTHETIC CUSTOMER ADVICE",
          "Invoice: TRINETRA-001",
          "Deductor TAN: ABCD12345E",
          "Withheld amount: INR 2000.00",
        ],
      },
      {
        name: "TRINETRA-ACCOUNTING.pdf",
        lines: [
          "SYNTHETIC ACCOUNTING RECORD",
          "Invoice: TRINETRA-001",
          "Booked withholding: INR 2000.00",
        ],
      },
      {
        name: "TRINETRA-TRANSCRIPTION-SOURCE.pdf",
        lines: [
          "SYNTHETIC EVIDENCE - NOT AN OFFICIAL TAX STATEMENT",
          "Receiving PAN: ABCDE1234F",
          "Period: FY 2025-26 / AY 2026-27",
          "Deductor TAN: ABCD12345E",
          "Reviewed posting amount: INR 2000.00",
          "Source row: Synthetic row 1",
        ],
      },
    ];
    for (const doc of documents) {
      const form = new FormData();
      form.append(
        "file",
        new Blob([new Uint8Array(buildPdf([doc.lines]))], { type: "application/pdf" }),
        doc.name,
      );
      const sent = await api<{ id: string }>(
        customer.session,
        "POST",
        `/workspaces/${customer.wsId}/work-items`,
        form,
      );
      expect(sent.status, sent.text).toBe(201);
      if (doc.name === "TRINETRA-INVOICE.pdf") invoiceId = sent.body.id;
      else if (doc.name === "TRINETRA-ADVICE.pdf") adviceId = sent.body.id;
      else if (doc.name === "TRINETRA-ACCOUNTING.pdf") accountingId = sent.body.id;
      else statementId = sent.body.id;
      await expect
        .poll(
          async () =>
            (
              await api<{ status: string }>(
                customer.session,
                "GET",
                `/workspaces/${customer.wsId}/work-items/${sent.body.id}`,
              )
            ).body.status,
          { timeout: 180_000, intervals: [2000, 4000] },
        )
        .toBe("COMPLETED");
    }
    await expect
      .poll(
        async () => {
          const r = await api<{ extracted_entities: Record<string, unknown> | null }>(
            customer.session,
            "GET",
            `/workspaces/${customer.wsId}/work-items/${invoiceId}`,
          );
          return r.body.extracted_entities?.currency;
        },
        { timeout: 180_000, intervals: [2000, 4000] },
      )
      .toBe("INR");
  });
  test("profile to accountant review, worker, source comparison and export", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(`/${customer.orgSlug}/${customer.wsSlug}/trinetra`);
    await page.getByRole("button", { name: "Your workspace", exact: true }).click();
    await page.getByText("Add reviewed evidence", { exact: true }).click();
    await page
      .getByLabel("Legal entity name", { exact: true })
      .fill("Synthetic Trinetra Services Ltd");
    await page.getByLabel("Entity PAN", { exact: true }).fill("ABCDE1234F");
    await page.getByRole("button", { name: "Save reviewed evidence", exact: true }).click();
    await expect(page.getByText("Evidence saved.", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "Evidence task", exact: true }).selectOption("credit");
    await page
      .getByRole("combobox", { name: "Legal entity", exact: true })
      .selectOption({ label: "Synthetic Trinetra Services Ltd · ******234F" });
    await page
      .getByRole("combobox", { name: "Source document", exact: true })
      .selectOption(invoiceId);
    await page.getByLabel("Financial / tax year starting").fill("2025");
    await page.getByLabel("Customer", { exact: true }).fill("Synthetic Deductor Ltd");
    await page.getByLabel("Invoice reference", { exact: true }).fill("TRINETRA-001");
    await page.getByLabel("Deductor TAN", { exact: true }).fill("ABCD12345E");
    await page.getByLabel("Supported expected deduction (INR)").fill("2000");
    await page
      .getByLabel("Evidence and reason", { exact: true })
      .fill("Synthetic supported expectation reviewed manually; no rate inferred.");
    await page.getByRole("button", { name: "Save reviewed evidence", exact: true }).click();
    await expect(page.getByRole("button", { name: /Synthetic Deductor Ltd/ })).toBeVisible();
    await page
      .getByRole("combobox", { name: "Evidence task", exact: true })
      .selectOption("statement");
    await page
      .getByRole("combobox", { name: "Source document", exact: true })
      .selectOption(statementId);
    await page.getByLabel("Confirm source entity PAN").fill("ABCDE1234F");
    await page
      .getByLabel("Reviewed rows: TAN, amount in INR, source reference")
      .fill("ABCD12345E,2000,Synthetic row 1");
    await page.getByRole("checkbox", { name: /I checked the selected entity/ }).check();
    await page.getByRole("button", { name: "Preview transcription" }).click();
    await expect(page.getByText(/Scope preview:/)).toContainText("₹2,000.00");
    await page.getByRole("button", { name: "Import reviewed snapshot" }).click();
    await expect(page.getByText(/Scope preview:/)).toHaveCount(0);
    await page.getByRole("button", { name: /Synthetic Deductor Ltd/ }).click();
    const insight = page.getByRole("complementary", { name: "Case insight" });
    await insight.getByLabel(/Posting 1/).fill("2000");
    await insight
      .getByLabel("Reason and evidence", { exact: true })
      .fill("Confirmed synthetic posting against the original uploaded source.");
    await insight.getByRole("button", { name: "Record review", exact: true }).click();
    await expect(insight).toContainText("Revision 2");
    await insight
      .getByRole("combobox", { name: "Review decision", exact: true })
      .selectOption("CA_REVIEWED");
    await insight
      .getByLabel("Reason and evidence", { exact: true })
      .fill("Accountant reviewed synthetic evidence and the explicit allocation.");
    await insight.getByRole("button", { name: "Record review", exact: true }).click();
    await expect(insight).toContainText("Revision 3");
    await insight.getByText("Ownership and supporting evidence", { exact: true }).click();
    await insight
      .getByRole("combobox", { name: "Supporting document", exact: true })
      .selectOption(adviceId);
    await insight
      .getByRole("combobox", { name: "Evidence kind", exact: true })
      .selectOption("DEDUCTOR_ADVICE");
    await insight.getByLabel("Amount explicitly stated in evidence (INR)").fill("2000");
    await insight
      .getByLabel("Review reason", { exact: true })
      .fill("Reviewed the separate synthetic customer advice.");
    await insight.getByRole("button", { name: "Save review details" }).click();
    await expect(insight).toContainText("Revision 4");
    await insight.getByText("Ownership and supporting evidence", { exact: true }).click();
    await insight
      .getByRole("combobox", { name: "Supporting document", exact: true })
      .selectOption(accountingId);
    await insight
      .getByRole("combobox", { name: "Evidence kind", exact: true })
      .selectOption("ACCOUNTING_RECORD");
    await insight.getByLabel("Amount explicitly stated in evidence (INR)").fill("2000");
    await insight
      .getByLabel("Review reason", { exact: true })
      .fill("Compared accounting and customer advice; withholding agrees.");
    await insight.getByRole("checkbox", { name: /Confirm withholding for the receivable/ }).check();
    await insight.getByRole("button", { name: "Save review details" }).click();
    await expect(insight).toContainText("Revision 5");
    await expect(insight).toContainText("Reviewed withholding: ₹2,000.00");
    await page.getByRole("button", { name: "Reconcile current evidence", exact: true }).click();
    await expect(
      page.getByText("Reconciliation complete. The queue reflects current source evidence.", {
        exact: true,
      }),
    ).toBeVisible({ timeout: 60_000 });
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV", exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
    await page.getByRole("link", { name: "Compare source documents", exact: true }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Review credit evidence" }),
    ).toBeVisible();
    await expect(page.getByRole("region", { name: "Invoice source" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Active statement source" })).toBeVisible();
    await settle(page);
    const scan = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
    ).toEqual([]);
  });
});
