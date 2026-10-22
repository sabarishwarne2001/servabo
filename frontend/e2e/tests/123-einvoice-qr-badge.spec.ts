/**
 * WHERE AN E-INVOICE VALUE CAME FROM (Final session 1, 3D, N-140).
 *
 * A document that carried an e-invoice QR code shows, beside each field the code supplied or checked, "From the e-invoice QR code";
 * above the fields the IRN with a copy button; and one line for the signature in one of three states:
 *   signature not checked     (no NIC key configured: the code is a second opinion)
 *   signature checked         (the key is configured and verifies: the code's values are used)
 *   signature does not match  (a key is configured and fails, in the warning colour: the page's reading is kept)
 * Where the page and the code disagree both values are shown and the one used is named.
 *
 * The browser cannot draw a QR code for the OCR worker to read, so the stand-in (`e2e_stand_in.py einvoice-qr`) leaves on an
 * already-read document exactly what the workers leave: a real signed token run through the real merge, in the chosen state.
 * Accessibility is scanned in both themes for all three states.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { documents, newCustomer, signInAs, standIn, uploadViaApi, type Customer } from "../support/journey";

let customer: Customer;
let documentId = "";

const SIGNATURES = [
  ["not_checked", "signature not checked"],
  ["checked", "signature checked"],
  ["does_not_match", "signature does not match"],
] as const;

const open = async (page: import("@playwright/test").Page): Promise<void> => {
  await page.goto(customer.ws(`work-items/${documentId}`));
  await expect(page.getByTestId("einvoice-qr-strip")).toBeVisible({ timeout: 30_000 });
  await settle(page);
};

test.describe("E-invoice QR code badge", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(300_000);
    customer = await newCustomer("einvqr", "QR Traders Ltd");
    documentId = await uploadViaApi(customer, "qr");
    // The document has to be finished before the workers' result is put on it, or the worker would write over it.
    await expect.poll(async () => (await documents(customer)).find((d) => d.id === documentId)?.status, { timeout: 200_000 }).toMatch(/COMPLETED|FAILED/);
  });

  for (const [state, words] of SIGNATURES) {
    test(`${words}: the fields, the IRN and the signature line`, async ({ page, context }) => {
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      standIn("einvoice-qr", null, "--document", documentId, "--signature", state);
      await signInAs(page, customer.email);
      await open(page);
      const strip = page.getByTestId("einvoice-signature");
      await expect(strip).toHaveText(words);
      await expect(strip).toHaveAttribute("data-state", state);
      await expect(page.getByTestId("einvoice-irn")).toHaveText("9f1c".repeat(16));
      await page.getByRole("button", { name: "Copy the IRN" }).click();
      await expect(page.getByText("IRN copied.")).toBeVisible();
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("9f1c".repeat(16));
      // The fields the code supplied or checked wear the badge; the total differs between the page and the code.
      await expect(page.locator('[data-field="irn"]').getByTestId("qr-field-badge")).toHaveText("From the e-invoice QR code");
      await expect(page.locator('[data-field="vendor_gstin"]').getByTestId("qr-field-badge")).toBeVisible();
      const total = page.locator('[data-field="total_amount"]');
      await expect(total.getByTestId("qr-conflict")).toContainText("118000.00");
      await expect(total.getByTestId("qr-conflict")).toContainText("99999.00");
      if (state === "checked") {
        await expect(total.getByTestId("qr-conflict")).toContainText("The code’s value is used.");
        await expect(total).toContainText("118000.00");
      } else {
        await expect(total.getByTestId("qr-conflict")).toContainText("The page’s reading is kept");
        await expect(total).toContainText("99999.00");
      }
    });
  }

  for (const scheme of ["light", "dark"] as const) {
    test(`all three signature states have no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, customer.email);
      for (const [state] of SIGNATURES) {
        standIn("einvoice-qr", null, "--document", documentId, "--signature", state);
        await open(page);
        await page.reload();
        await expect(page.getByTestId("einvoice-signature")).toHaveAttribute("data-state", state, { timeout: 30_000 });
        await settle(page);
        const results = await new AxeBuilder({ page }).include('[data-testid="einvoice-qr-strip"]').include("[data-field]")
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        const found = results.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => `${state} ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
        expect(found, testInfo.title).toEqual([]);
      }
    });
  }
});
