/**
 * A ZIP IN THE GLOBAL UPLOAD TRAY (Final session 2A, Phase 4). A new conversation's dropzone hands files to the global
 * upload tray, which survives navigation. It now takes a zip by the same path as the Documents page (spec 118): the zip
 * goes up whole, the server unpacks it and adds each document through the ordinary intake, and the tray shows the same
 * parent row with "N documents added, M skipped". A file type the workspace refuses inside the zip is skipped with its
 * reason; nothing about the zip is uploaded as a document of its own.
 *
 * Stood in: nothing. The zip is real, the worker unpacks it and the documents are read by the local model stand-in.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { documents, newCustomer, signInAs, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";
import { buildZip } from "../support/zip";

let owner: Customer;
let zipFile: string;
let conversationId: string;

const pdf = (number: string): Buffer =>
  buildPdf([[`TAX INVOICE ${number}`, `Invoice Number: ${number}`, "Vendor: Sahyadri Packaging", "Total Amount Due: 1000.00 INR"]]);

test.describe("A zip in the global upload tray", () => {
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    owner = await newCustomer("trayzip", "Tray Zip Traders");
    const dir = path.join(os.tmpdir(), "servabo-e2e-zip");
    fs.mkdirSync(dir, { recursive: true });
    zipFile = path.join(dir, "assistant-backlog.zip");
    fs.writeFileSync(zipFile, buildZip([
      { name: "INV-4101.pdf", data: pdf("INV-4101") },
      { name: "INV-4102.pdf", data: pdf("INV-4102") },
      { name: "notes.txt", data: Buffer.from("call the supplier") },
    ]));
    const created = await api<{ id: string }>(owner.session, "POST", `/workspaces/${owner.wsId}/assistant/conversations`, { title: "Backlog" });
    expect([200, 201], created.text).toContain(created.status);
    conversationId = created.body.id;
  });

  test("dropped on a conversation, the zip becomes documents and the tray says what it added", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.ws(`assistant/c/${conversationId}`));
    await settle(page);
    await expect(page.getByText(/ZIP/).first()).toBeVisible({ timeout: 20_000 });
    await page.locator("#fp-upload-input").setInputFiles(zipFile);

    const tray = page.getByRole("complementary", { name: "Uploads" });
    const archive = tray.getByTestId("tray-archive");
    await expect(archive).toBeVisible({ timeout: 30_000 });
    await expect(archive).toContainText("assistant-backlog.zip");
    const summary = archive.getByTestId("archive-summary");
    await expect(summary).toContainText("2 documents added", { timeout: 90_000 });
    await expect(summary).toContainText("1 skipped");
    await expect(archive.getByTestId("archive-skipped")).toContainText("notes.txt");

    const names = (await documents(owner)).map((d) => String(d.original_filename)).sort();
    expect(names).toEqual(["INV-4101.pdf", "INV-4102.pdf"]);
  });
});
