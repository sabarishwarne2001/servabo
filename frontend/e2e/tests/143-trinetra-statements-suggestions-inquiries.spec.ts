/**
 * TRINETRA's working screens in a real browser (Final session 2T, Phase 8): importing a statement (the Servabo template, then an AIS
 * file whose columns must be chosen), suggestions from a filled template that a person accepts, and the inquiry draft that is never
 * sent by anything but a person. Synthetic files only (backend/tests/fixtures/trinetra); the official Form 26AS / 168 readers stay
 * unverified until a real file is read in Final 2B, and this spec shows them labelled that way.
 */
import { test, expect } from "../support/fixtures";
import { signInAs } from "../support/journey";
import {
  bookInvoice, createCase, createProfile, ENTITY, fixture, liveCustomer, PAN, TAN, templateFile, type LiveCustomer,
} from "../support/trinetra";

let customer: LiveCustomer;
let profileId: string;
let firstCase: string;

test.describe("TRINETRA working screens", () => {
  test.setTimeout(300_000);
  test.beforeAll(async () => {
    customer = await liveCustomer("tr-work", "business");
    profileId = await createProfile(customer);
    const invoice = await bookInvoice(customer, "TRW-1");
    firstCase = (await createCase(customer, profileId, invoice, "TRW-1")).id;
  });

  async function openStatements(page: import("@playwright/test").Page) {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("trinetra?tab=statements"));
    const form = page.getByTestId("trinetra-import");
    await expect(form).toBeVisible();
    await form.getByLabel("Legal entity").selectOption({ label: `${ENTITY} · ******234F` });
    await form.getByLabel("Confirm the entity's PAN").fill(PAN);
    return form;
  }

  test("a statement typed into the Servabo template is previewed, then imported, and the cases are compared again", async ({ page }) => {
    const form = await openStatements(page);
    await form.getByLabel(/The file \(CSV/).setInputFiles(
      templateFile([`${TAN},2000.00,row-1,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27`]),
    );
    await form.getByRole("button", { name: "Preview what the file says" }).click();
    const preview = page.getByTestId("trinetra-import-preview");
    await expect(preview).toContainText("Rows read");
    await expect(preview).toContainText("₹2,000.00");
    await expect(preview).toContainText("******345E");              // the TAN is masked on screen
    await expect(preview).not.toContainText(TAN);
    await expect(preview.getByRole("button", { name: "Import this statement" })).toBeDisabled();
    await preview.getByRole("checkbox", { name: /I checked the legal entity/ }).check();
    await preview.getByRole("button", { name: "Import this statement" }).click();
    await expect(page.getByTestId("trinetra-import-done")).toBeVisible();
  });

  test("an AIS file with two possible tax columns asks which one means what, and never shows a row it could not read", async ({ page, problems }) => {
    problems.allowHttp(/\/trinetra\/statement-files\/preview/, [422], "the ambiguous columns are refused, with the headings, until the person chooses");
    const form = await openStatements(page);
    const ais = fixture("ais_tds_sample.csv");
    const ambiguous = Buffer.from(
      ais.buffer.toString("utf8").replace("Tax Deducted", "Tax Deducted at Source,TDS Amount").replace(/,F\n/g, ",F,0\n"),
    );
    await form.getByLabel(/The file \(CSV/).setInputFiles({ name: "ais.csv", mimeType: "text/csv", buffer: ambiguous });
    await form.getByRole("button", { name: "Preview what the file says" }).click();
    const mapping = page.getByTestId("trinetra-import-mapping");
    await expect(mapping).toContainText("Which column means what");
    await expect(page.getByTestId("trinetra-import-error")).not.toContainText(TAN);
    await mapping.getByLabel("Column for Tax amount (used for matching)").selectOption({ label: "Tax Deducted at Source" });
    await mapping.getByLabel("Column for Deductor name (and TAN)").selectOption({ label: "Information Source" });
    await mapping.getByRole("button", { name: "Preview again with this mapping" }).click();
    const preview = page.getByTestId("trinetra-import-preview");
    await expect(preview).toContainText("Rows read");
    await expect(preview).toContainText("₹4,250.00");
    await expect(preview).not.toContainText(TAN);
    await expect(page.getByTestId("trinetra-import-notice")).toBeVisible();
  });

  test("the official statement formats are offered as unverified, never as a trusted reader", async ({ page, problems }) => {
    problems.allowHttp(/\/trinetra\/statement-files\/preview/, [409, 422], "an unverified or unrecognised official file is refused in words");
    const form = await openStatements(page);
    const readers = await form.getByLabel("How to read it").locator("option").allTextContents();
    const official = readers.filter((label) => /26AS|168/.test(label));
    expect(official.length).toBeGreaterThan(0);
    for (const label of official) expect(label).toContain("(unverified)");
    await form.getByLabel(/The file \(CSV/).setInputFiles(fixture("form26as_sample.txt"));
    await form.getByRole("button", { name: "Preview what the file says" }).click();
    // Whatever the reader makes of the file, the screen says it is unverified and nothing is saved without the person's confirmation.
    await expect(page.getByTestId("trinetra-import-error").or(page.getByTestId("trinetra-import-notice"))).toBeVisible();
    const notice = page.getByTestId("trinetra-import-notice");
    if (await notice.count()) {
      await expect(notice).toContainText("Unverified reader");
      await expect(page.getByRole("button", { name: "Import this statement" })).toBeDisabled();
    }
    await expect(page.getByTestId("trinetra-import-preview").or(page.getByTestId("trinetra-import-error"))).not.toContainText(TAN);
  });

  test("a filled template becomes suggestions; nothing is a case until a person accepts it with a reason", async ({ page }) => {
    const second = await bookInvoice(customer, "TRW-2");
    expect(second).toBeTruthy();
    await signInAs(page, customer.email);
    await page.goto(customer.ws("trinetra?tab=suggestions"));
    const sources = page.getByTestId("trinetra-sources");
    await sources.getByLabel("Legal entity").selectOption({ label: `${ENTITY} · ******234F` });
    await sources.getByText("Fill in an expected-TDS template").click();
    const rows = ["Invoice reference,Customer TAN,Expected TDS (INR),Section text (optional)", `TRW-2,${TAN},2000,194C as my records print it`];
    await sources.getByLabel("The filled template").setInputFiles({ name: "expected.csv", mimeType: "text/csv", buffer: Buffer.from(rows.join("\n") + "\n") });
    await sources.getByRole("button", { name: "Check each row against your invoices" }).click();
    const check = sources.getByRole("region", { name: "Template check" });
    await expect(check).toContainText("1 of 1 rows match exactly one invoice.");
    await check.getByRole("button", { name: "Add as suggestions" }).click();
    const suggestion = page.getByTestId("trinetra-suggestion").first();
    await expect(suggestion).toContainText("TRW-2");
    await expect(suggestion).toContainText("To confirm");
    // Accepting needs the reviewer's own reason.
    await suggestion.getByRole("button", { name: "Accept as a case" }).click();
    await suggestion.getByLabel(/Why you accept this/).fill("Checked the customer's advice against the invoice.");
    await suggestion.getByRole("button", { name: "Accept", exact: true }).click();
    await expect(page.getByTestId("trinetra-suggestion")).toHaveCount(0);   // an accepted suggestion leaves the to-confirm list
    await page.goto(customer.ws("trinetra"));
    await expect(page.getByRole("button", { name: /TRW-2/ })).toBeVisible();
  });

  test("an inquiry is a draft a person approves and presses Send on; without a confirmed contact it goes nowhere", async ({ page, problems }) => {
    problems.allowHttp(/\/trinetra\/inquiries\//, [409, 422], "approving needs a confirmed contact in Helm");
    await signInAs(page, customer.email);
    await page.goto(customer.ws("trinetra"));
    await page.getByRole("button", { name: /TRW-1/ }).click();
    const panel = page.getByTestId("trinetra-inquiries");
    await expect(panel).toContainText("A draft is only ever sent by a person pressing Send.");
    await expect(panel.getByTestId("trinetra-allowance")).toContainText("0 of");
    await panel.getByRole("button", { name: "Prepare a draft" }).click();
    const inquiry = page.getByTestId("trinetra-inquiry").first();
    await expect(inquiry).toBeVisible();
    await expect(inquiry.getByRole("button", { name: "Press Send" })).toHaveCount(0);   // a draft cannot be sent
    await inquiry.getByRole("button", { name: "Approve the draft" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "no confirmed email contact" })).toBeVisible();
    await expect(panel.getByTestId("trinetra-allowance")).toContainText("0 of");        // nothing went out
    expect(firstCase).toBeTruthy();
  });
});
