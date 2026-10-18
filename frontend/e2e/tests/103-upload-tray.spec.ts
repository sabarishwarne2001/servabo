/**
 * THE UPLOAD TRAY: Pause, Resume, Cancel and Retry on a large file (campaign Session C, long tail).
 *
 * Every file is sent in 8 MB parts through a resumable session. A 9 MB file is two parts; the
 * browser's part requests are slowed (the requests still reach the real server) so there is time to press
 * the tray's buttons, and one part is made to fail once for Retry. Each is checked on the page and
 * against the server: a paused upload sends nothing more until Resume and then completes; Cancel leaves
 * no document behind; a failed upload shows Retry, which finishes it from the parts the server already holds.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api } from "../support/api";
import { runId } from "../support/env";
import { newCustomer, signInAs, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

/** A 9 MB PDF on disk (one page, one long line of text): two parts, under the free trial's 10 MB limit. */
function bigPdf(label: string): string {
  const dir = path.join(os.tmpdir(), "servabo-e2e-journeys");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${label}-${runId()}.pdf`);
  fs.writeFileSync(file, buildPdf([[`TAX INVOICE ${label}`, "X".repeat(9_000_000)]]));
  return file;
}

const documentNamed = async (customer: Customer, name: string): Promise<{ id: string } | undefined> => {
  const listed = await api<{ items?: Array<{ id: string; original_filename: string }> } | Array<{ id: string; original_filename: string }>>(
    customer.session, "GET", `/workspaces/${customer.wsId}/work-items?page_size=100`);
  const rows = Array.isArray(listed.body) ? listed.body : (listed.body.items ?? []);
  return rows.find((row) => row.original_filename === name);
};

test.describe("Upload tray", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let customer: Customer;
  const PART = /\/upload-sessions\/[0-9a-f-]+\/parts\/\d+/;

  test.beforeAll(async () => {
    customer = await newCustomer("tray", "Upload Tray Ltd");
  });

  /** An assistant conversation's page has the dropzone that sends files through the resumable tray
   *  (the Documents page's queue does not). */
  async function startUpload(page: import("@playwright/test").Page, file: string): Promise<void> {
    const conversation = await api<{ id: string }>(customer.session, "POST", `/workspaces/${customer.wsId}/assistant/conversations`, { work_item_id: null });
    expect(conversation.status, conversation.text).toBeLessThan(300);
    await page.goto(customer.ws(`assistant/c/${conversation.body.id}`));
    await expect(page.locator("#fp-upload-input")).toBeAttached({ timeout: 20_000 });
    await page.locator("#fp-upload-input").setInputFiles(file);
  }

  test("Pause stops the upload, Resume finishes it, and the document arrives whole", async ({ page }) => {
    const file = bigPdf("pause");
    const name = path.basename(file);
    let parts = 0;
    await page.route(PART, async (route) => {
      parts += 1;
      await new Promise((resolve) => setTimeout(resolve, 3_000));  // a slow link, not a fake one
      await route.continue();
    });
    await signInAs(page, customer.email);
    await startUpload(page, file);

    const tray = page.getByRole("complementary", { name: "Uploads" });
    await tray.getByRole("button", { name: `Pause ${name}` }).click();
    await expect(tray).toContainText("paused");
    await expect(tray, "pausing is not a failure").not.toContainText(/failed/i);
    await expect(tray.getByRole("button", { name: `Resume ${name}` })).toBeVisible();
    // Nothing more is sent while it is paused: the number of part requests stops growing.
    const seen = parts;
    await expect.poll(() => parts, { timeout: 8_000, intervals: [2_000] }).toBeLessThanOrEqual(seen + 1);
    expect(await documentNamed(customer, name), "not complete while paused").toBeUndefined();

    await tray.getByRole("button", { name: `Resume ${name}` }).click();
    await expect.poll(async () => Boolean(await documentNamed(customer, name)), { timeout: 120_000, intervals: [2_000] }).toBe(true);
    await expect(tray.getByRole("button", { name: `Pause ${name}` })).toHaveCount(0, { timeout: 30_000 });
    await expectHealthyPage(page);
  });

  test("Cancel stops the upload and no document is left behind", async ({ page }) => {
    const file = bigPdf("cancel");
    const name = path.basename(file);
    await page.route(PART, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2_500));
      await route.continue();
    });
    await signInAs(page, customer.email);
    await startUpload(page, file);
    const tray = page.getByRole("complementary", { name: "Uploads" });
    await tray.getByRole("button", { name: `Cancel ${name}` }).click();
    await expect(tray.getByRole("button", { name: `Cancel ${name}` })).toHaveCount(0);
    await expect(tray).toContainText(/cancel/i);
    await expect(tray, "a cancelled upload is not counted as a failure").not.toContainText(/failed/i);
    await page.reload();
    await settle(page);
    expect(await documentNamed(customer, name)).toBeUndefined();
    await expectHealthyPage(page);
  });

  test("a part that fails shows Retry, which finishes the upload", async ({ page, problems }) => {
    problems.allowHttp(PART, [503], "one part is made to fail once");
    const file = bigPdf("retry");
    const name = path.basename(file);
    let failed = false;
    await page.route(PART, async (route) => {
      if (!failed) {
        failed = true;
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Storage is busy." }) });
      }
      return route.continue();
    });
    await signInAs(page, customer.email);
    await startUpload(page, file);
    const tray = page.getByRole("complementary", { name: "Uploads" });
    await expect(tray.getByRole("button", { name: `Retry ${name}` })).toBeVisible({ timeout: 60_000 });
    expect(await documentNamed(customer, name)).toBeUndefined();

    await tray.getByRole("button", { name: `Retry ${name}` }).click();
    await expect.poll(async () => Boolean(await documentNamed(customer, name)), { timeout: 120_000, intervals: [2_000] }).toBe(true);
    await expect(tray.getByRole("button", { name: `Retry ${name}` })).toHaveCount(0);
    await expectHealthyPage(page);
  });
});
