/**
 * EMAIL-IN (Final session 1, 2B): forward invoices to a workspace's own address.
 *
 * Postmark is stood in by `scripts/e2e_stand_in.py inbound-email`, which delivers a real-shaped inbound message to the API's real
 * webhook with the real basic-auth credential. A trial customer of its own, signed in as the workspace's owner:
 *   1. Settings -> Email-in shows the address (long and random, never the workspace's name) with a copy button;
 *   2. mail from a sender nobody allowed is HELD: it is listed under "Waiting for you" with the reason, and nothing is added;
 *   3. "Approve" adds its document, which says "Arrived by email from ..." on its own page;
 *   4. allowing the sender's domain makes the next message arrive straight away, listed under "Recent arrivals";
 *   5. "Change address" asks in the app's own dialog (never a browser pop-up); the old address is then refused (403) and the
 *      new one works;
 *   6. "Discard" asks first and throws a held message away.
 * Accessibility is scanned in both themes on the page with held and arrived messages.
 *
 * Stood in: Postmark (nothing is sent to or from a real mail server).
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { addMember, documents, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

let owner: Customer;
const dir = path.join(os.tmpdir(), "servabo-e2e-email");

function invoice(name: string, number: string): string {
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  fs.writeFileSync(file, buildPdf([[`TAX INVOICE ${number}`, `Invoice Number: ${number}`, "Vendor: Sahyadri Packaging", "Total Amount Due: 500.00 INR"]]));
  return file;
}

const deliver = (file: string, from: string, subject: string, extra: string[] = []): Record<string, unknown> =>
  standIn("inbound-email", owner.orgSlug, "--file", file, "--from", from, "--subject", subject, ...extra);

const open = async (page: import("@playwright/test").Page): Promise<void> => {
  await page.goto(`${owner.ws("settings")}?section=inbound`);
  await expect(page.getByTestId("email-in")).toBeVisible({ timeout: 20_000 });
};

test.describe("Email-in", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  let address = "";

  test.beforeAll(async () => {
    owner = await newCustomer("mailin", "Email In Ltd");
  });

  test("the settings page shows a long random address with a copy button; with no sender allowed every message waits", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    const shown = page.getByTestId("email-in-address");
    await expect(shown).toBeVisible();
    address = (await shown.innerText()).trim();
    expect(address).toMatch(/^[a-z0-9]+\+[a-z0-9]{32}@inbound\.postmarkapp\.com$/);
    expect(address.toLowerCase()).not.toContain(owner.wsSlug.toLowerCase().replace(/[^a-z0-9]/g, "") || "main-workspace-name");
    await expect(page.getByRole("button", { name: "Copy the address" })).toBeVisible();
    await expect(page.getByTestId("email-in-no-senders")).toBeVisible();

    const answer = deliver(invoice("INV-9001.pdf", "INV-9001"), "stranger@elsewhere.example", "Invoice INV-9001");
    expect(answer.http).toBe(200);
    expect(answer.status).toBe("held");
    await page.reload();
    const held = page.getByTestId("email-in-held").getByTestId("inbound-message");
    await expect(held).toHaveCount(1);
    await expect(held).toContainText("stranger@elsewhere.example");
    await expect(held).toContainText("not on this workspace's list of allowed senders");
    expect(await documents(owner)).toHaveLength(0);
  });

  test("approving a held message adds its document, which says how it arrived", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    await page.getByTestId("email-in-held").getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("1 document added. Processing has started.")).toBeVisible();
    await expect(page.getByTestId("email-in-held")).toHaveCount(0);
    await expect(page.getByTestId("email-in-arrivals").getByTestId("inbound-message")).toHaveCount(1);

    const listed = await documents(owner);
    expect(listed).toHaveLength(1);
    await page.goto(`${owner.ws("work-items")}/${String(listed[0]!.id)}`);
    await expect(page.getByTestId("document-source")).toContainText("Arrived by email from stranger@elsewhere.example");
    await expect(page.getByTestId("document-source")).toContainText("Invoice INV-9001");
  });

  test("an allowed sender's mail arrives straight away; a replayed delivery counts once", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    await page.getByLabel("Sender address or domain").fill("supplier.example");
    await page.getByRole("button", { name: "Allow" }).click();
    await expect(page.getByTestId("email-in-senders")).toContainText("supplier.example");

    const file = invoice("INV-9002.pdf", "INV-9002");
    const first = deliver(file, "ap@supplier.example", "Invoice INV-9002", ["--message-id", "e2e-replay-1"]);
    expect(first).toMatchObject({ http: 200, status: "accepted", documents: 1 });
    const again = deliver(file, "ap@supplier.example", "Invoice INV-9002", ["--message-id", "e2e-replay-1"]);
    expect(again).toMatchObject({ http: 200, status: "duplicate" });
    await page.reload();
    await expect(page.getByTestId("email-in-arrivals").getByTestId("inbound-message")).toHaveCount(2);
    expect((await documents(owner)).length).toBe(2);
  });

  test("changing the address asks in the app's own dialog; the old address is refused and the new one works", async ({ page }) => {
    await signInAs(page, owner.email);
    await open(page);
    const before = (await page.getByTestId("email-in-address").innerText()).trim();
    await page.getByRole("button", { name: "Change address" }).click();
    const dialog = page.getByRole("alertdialog", { name: "Change this address?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click().catch(async () => dialog.getByRole("button", { name: "Not now" }).click());
    await expect(page.getByTestId("email-in-address")).toHaveText(before);

    await page.getByRole("button", { name: "Change address" }).click();
    await page.getByRole("alertdialog", { name: "Change this address?" }).getByRole("button", { name: "Change address" }).click();
    await expect(page.getByText("A new address is ready. The old one no longer works.")).toBeVisible();
    await expect(page.getByTestId("email-in-address")).not.toHaveText(before);

    const refused = deliver(invoice("INV-9003.pdf", "INV-9003"), "ap@supplier.example", "Invoice INV-9003", ["--address", before]);
    expect(refused.http).toBe(403);
    const accepted = deliver(invoice("INV-9003.pdf", "INV-9003"), "ap@supplier.example", "Invoice INV-9003");
    expect(accepted).toMatchObject({ http: 200, status: "accepted" });
  });

  test("a held message can be discarded, after asking", async ({ page }) => {
    deliver(invoice("INV-9004.pdf", "INV-9004"), "stranger@elsewhere.example", "Invoice INV-9004");
    await signInAs(page, owner.email);
    await open(page);
    const held = page.getByTestId("email-in-held").getByTestId("inbound-message");
    await expect(held).toHaveCount(1);
    await held.getByRole("button", { name: "Discard" }).click();
    const dialog = page.getByRole("alertdialog", { name: "Discard this message?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Discard" }).click();
    await expect(page.getByTestId("email-in-held")).toHaveCount(0);
  });

  test("only workspace administrators are offered the section, and the server refuses everyone else", async ({ page }) => {
    const member = await addMember(owner, "contrib", "MEMBER", "CONTRIBUTOR");
    await signInAs(page, member.email);
    await page.goto(`${owner.ws("settings")}?section=workspace`);
    await expect(page.getByRole("button", { name: /^General/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Email-in/ })).toHaveCount(0);
    const refused = await api(await apiLogin(member.email), "GET", `/workspaces/${owner.wsId}/inbound-email`);
    expect(refused.status).toBe(403);
    await signInAs(page, owner.email);
    await page.goto(`${owner.ws("settings")}?section=workspace`);
    await expect(page.getByRole("button", { name: /^Email-in/ })).toBeVisible();
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the page with held and arrived messages has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      deliver(invoice("INV-9005.pdf", "INV-9005"), "stranger@elsewhere.example", "Invoice INV-9005");
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      await open(page);
      await expect(page.getByTestId("email-in-held").getByTestId("inbound-message")).toHaveCount(1);
      await settle(page);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
        testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${v.id} (${v.nodes.length})` });
      }
      expect(found, "email-in settings with serious or critical accessibility violations").toEqual([]);
      // leave one held message at most: discard it so the next scheme starts from the same place
      const discard = page.getByTestId("email-in-held").getByRole("button", { name: "Discard" });
      await discard.click();
      await page.getByRole("alertdialog", { name: "Discard this message?" }).getByRole("button", { name: "Discard" }).click();
      await expect(page.getByTestId("email-in-held")).toHaveCount(0);
    });
  }
});
