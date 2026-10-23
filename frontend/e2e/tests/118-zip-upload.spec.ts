/**
 * ZIP UPLOAD (Final session 1, 2A): a customer with a backlog drops one archive on day one.
 *
 * A trial customer of its own drops a REAL zip on the documents tray: three invoice PDFs, a `.DS_Store` the computer
 * added, a GSTR-2B JSON and a stray notes.txt. Then:
 *   1. the tray shows one parent row for the zip, with its progress, then the plain summary
 *      "3 documents added, 2 skipped: ..." (the `.DS_Store` is never mentioned);
 *   2. the three documents are in the workspace and read through the ordinary pipeline;
 *   3. the GSTR-2B is listed with "This looks like a GSTR-2B file: import it on the GST credit page" and a link to it;
 *   4. a zip the server refuses (a path that escapes) stays in the list with its sentence, and nothing is added;
 *   5. a zip over the plan's limit part-way is covered by the live backend test (a stand-in refuses the third admission);
 *      here the tray's wording for it is proven by the unit test of `summariseArchive`.
 * Accessibility is scanned in both themes on the tray with the result showing.
 *
 * Stood in: nothing. The zip is real, the worker unpacks it and the documents are read by the local model stand-in.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { test, expect, settle } from "../support/fixtures";
import { gstin, gstr2b } from "../support/gst";
import { documents, newCustomer, signInAs, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";
import { buildZip } from "../support/zip";

const BUYER = gstin("27", "AAACZ1234F");
const SUPPLIER = gstin("27", "AABCS5555K");

let owner: Customer;
const files: Record<string, string> = {};

const pdf = (number: string, amount: string): Buffer =>
  buildPdf([[`TAX INVOICE ${number}`, `Invoice Number: ${number}`, "Vendor: Sahyadri Packaging", `Total Amount Due: ${amount} INR`]]);

function writeZip(name: string, entries: ReadonlyArray<{ name: string; data: Buffer }>): string {
  const dir = path.join(os.tmpdir(), "servabo-e2e-zip");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  fs.writeFileSync(file, buildZip(entries));
  return file;
}

async function drop(page: Page, file: string): Promise<void> {
  await page.goto(owner.ws());
  const dropzone = page.getByRole("button", { name: "Upload documents" });
  await expect(dropzone).toBeVisible({ timeout: 15_000 });
  await page.locator('input[aria-label="Upload document picker"]').setInputFiles(file);
  await expect(page.getByTestId("upload-queue-item")).toHaveCount(1);
}

test.describe("Zip upload", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    owner = await newCustomer("zip", "Zip Upload Ltd");
    files.backlog = writeZip("backlog.zip", [
      { name: "Invoices/INV-3001.pdf", data: pdf("INV-3001", "1000.00") },
      { name: "Invoices/INV-3002.pdf", data: pdf("INV-3002", "2000.00") },
      { name: "Invoices/INV-3003.pdf", data: pdf("INV-3003", "3000.00") },
      { name: "Invoices/.DS_Store", data: Buffer.from("\x00\x00\x00\x01Bud1", "binary") },
      {
        name: "returns/GSTR2B_092026.json",
        data: Buffer.from(gstr2b(BUYER, "2026-09", [
          { gstin: SUPPLIER, name: "Sahyadri Packaging", docs: [{ number: "INV-3001", date: "2026-09-05", taxable: 1000 }] },
        ])),
      },
      { name: "notes.txt", data: Buffer.from("call the supplier on Monday") },
    ]);
    files.evil = writeZip("evil.zip", [{ name: "../evil.pdf", data: pdf("INV-9999", "1.00") }]);
  });

  test("a zip of invoices becomes documents; the junk is not mentioned and the GSTR-2B is pointed at the GST page", async ({ page }) => {
    await signInAs(page, owner.email);
    await drop(page, files.backlog!);
    await expect(page.getByTestId("upload-queue-item")).toContainText("backlog.zip");
    await page.getByRole("button", { name: "Start Ingestion" }).click();

    const progress = page.getByTestId("archive-progress");
    await expect(progress).toBeVisible({ timeout: 30_000 });
    await expect(progress).toContainText("backlog.zip");
    const summary = progress.getByTestId("archive-summary");
    await expect(summary).toContainText("3 documents added", { timeout: 90_000 });
    await expect(summary).toContainText("2 skipped");
    await expect(summary).toContainText("not a supported file type");
    await expect(summary).toContainText("a GSTR-2B file, import it on the GST credit page");

    const skipped = progress.getByTestId("archive-skipped");
    await expect(skipped).toContainText("notes.txt");
    await expect(skipped).toContainText("GSTR2B_092026.json");
    await expect(skipped).toContainText("This looks like a GSTR-2B file: import it on the GST credit page.");
    await expect(skipped).not.toContainText("DS_Store");

    const listed = await documents(owner);
    const names = listed.map((d) => String(d.original_filename)).sort();
    expect(names).toEqual(["INV-3001.pdf", "INV-3002.pdf", "INV-3003.pdf"]);

    // the GSTR-2B is imported on the GST credit page, which the skipped line links to
    await skipped.getByRole("link", { name: "Open the GST credit page" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "GST credit" })).toBeVisible();
  });

  test("a zip the server refuses stays in the list with its sentence and adds nothing", async ({ page, problems }) => {
    problems.allowHttp(/\/ingestion-batches\/archive/, [400], "the server refuses a zip whose path escapes");
    const before = (await documents(owner)).length;
    await signInAs(page, owner.email);
    await drop(page, files.evil!);
    await page.getByRole("button", { name: "Start Ingestion" }).click();
    const row = page.getByTestId("upload-queue-item");
    await expect(row).toContainText("evil.zip");
    await expect(row.getByRole("alert")).toContainText(/outside|traverse|path/i, { timeout: 30_000 });
    await expect(page.getByTestId("archive-progress")).toHaveCount(0);
    expect((await documents(owner)).length).toBe(before);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the tray with a finished zip has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      await drop(page, files.backlog!);
      await page.getByRole("button", { name: "Start Ingestion" }).click();
      await expect(page.getByTestId("archive-summary")).toContainText("documents added", { timeout: 90_000 });
      await settle(page);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
        testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${v.id} (${v.nodes.length})` });
      }
      expect(found, "the tray with a zip result with serious or critical accessibility violations").toEqual([]);
    });
  }
});
