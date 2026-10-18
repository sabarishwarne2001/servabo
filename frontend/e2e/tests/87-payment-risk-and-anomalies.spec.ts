/**
 * PAYMENT RISK AND ANOMALIES — the audit radar's decision buttons (campaign session C).
 *
 * A new Business customer uploads real invoice PDFs one after the other and the worker's own radar
 * scan raises the findings (nothing is seeded or faked):
 *   A  vendor V, account X, total 1,250.00
 *   B  vendor V, account Y, total 6,000.00   -> "Bank account changed" (HIGH) and "Round total" (LOW)
 *   C  vendor V, account Z, total 1,250.00   -> "Bank account changed" (HIGH)
 *   D  a rescanned copy of A (same invoice number)  -> a duplicate-document anomaly
 *   E  a rescanned copy of B (same invoice number)  -> a duplicate-document anomaly, "Round total"
 *
 * On the Audit radar page, in the browser:
 *   Payment risk: "Confirm risk" settles a flag as CONFIRMED; "Not a risk…" opens a reason box whose
 *     "Dismiss" needs at least 10 characters, "Cancel" changes nothing, and the reason is shown to the
 *     next reader as "Reviewer: …".
 *   Anomalies: "This is a real finding" confirms; "Not an anomaly" needs a reason, keeps it, and
 *     writes a suppression.
 * Each decision is checked on the page, after a reload and through the API. The server refuses an
 * empty or too short reason and refuses a viewer, whatever the page shows.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, listWorkItems, uploadFile } from "../support/api";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";
import type { ApiSession } from "../support/api";

const TERMINAL = new Set(["COMPLETED", "FAILED", "ERROR", "NEEDS_REVIEW", "REVIEW", "PENDING_REVIEW"]);

interface Flag {
  readonly id: string;
  readonly document: string | null;
  readonly kind: "BANK_ACCOUNT_CHANGED" | "ROUND_AMOUNT";
  readonly severity: string;
  readonly status: "OPEN" | "CONFIRMED" | "DISMISSED";
  readonly summary: string;
  readonly review_note: string | null;
  readonly reviewed_at: string | null;
}
interface FlagList { readonly items: Flag[]; readonly counts_by_status: Record<string, number> }
interface Finding {
  readonly id: string;
  readonly kind: string;
  readonly status: "OPEN" | "CONFIRMED" | "DISMISSED";
  readonly headline: string;
  readonly resolved_at: string | null;
  readonly resolution_note: string | null;
  readonly subject_work_item_id: string;
  readonly counterpart_work_item_id: string | null;
}
interface Suppression { readonly kind: string; readonly item_a_id: string; readonly item_b_id: string; readonly reason: string }

const KIND_LABEL = { BANK_ACCOUNT_CHANGED: "Bank account changed", ROUND_AMOUNT: "Round total" } as const;

const SUFFIX = runId().toLowerCase();
const VENDOR = `Radar Probe Supplies ${SUFFIX} Ltd`;
const NUMBER = { a: `INV-RA-${SUFFIX.toUpperCase()}`, b: `INV-RB-${SUFFIX.toUpperCase()}`, c: `INV-RC-${SUFFIX.toUpperCase()}` };
const FILE = {
  a: `radar-a-${SUFFIX}.pdf`,
  b: `radar-b-${SUFFIX}.pdf`,
  c: `radar-c-${SUFFIX}.pdf`,
  d: `radar-d-copy-of-a-${SUFFIX}.pdf`,
  e: `radar-e-copy-of-b-${SUFFIX}.pdf`,
};
const ACCOUNT = { x: "GB29 NWBK 6016 1331 9268 19", y: "GB94 BARC 1020 1530 0934 59", z: "DE89 3704 0044 0532 0130 00" };

function writeInvoice(file: string, lines: { number: string; account: string; total: string; extra?: string }): string {
  const dir = path.join(os.tmpdir(), "servabo-e2e-radar", SUFFIX);
  fs.mkdirSync(dir, { recursive: true });
  const target = path.join(dir, file);
  fs.writeFileSync(target, buildPdf([[
    "INVOICE",
    `Vendor: ${VENDOR}`,
    "Vendor Address: 4 Probe Lane, Leeds LS1 4AB, United Kingdom",
    `Vendor Bank Account: ${lines.account}`,
    "Bill To: Radar Probe Buyer Inc",
    `Invoice Number: ${lines.number}`,
    "Invoice Date: 2026-09-15",
    "Due Date: 2026-10-15",
    "Currency: USD",
    "Line items:",
    `Total Amount Due: ${lines.total} USD`,
    "Payment terms: Net 30",
    ...(lines.extra ? [lines.extra] : []),
  ]]));
  return target;
}

let customer: Customer;
let viewer: { email: string; session: ApiSession };

async function flags(session: ApiSession = customer.session): Promise<Flag[]> {
  const listed = await api<FlagList>(session, "GET", `/workspaces/${customer.wsId}/payment-risk`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
}

async function flagOf(document: string, kind: Flag["kind"]): Promise<Flag> {
  const found = (await flags()).find((flag) => flag.document === document && flag.kind === kind);
  expect(found, `a ${kind} flag on ${document}`).toBeTruthy();
  return found as Flag;
}

async function findings(session: ApiSession = customer.session): Promise<Finding[]> {
  const listed = await api<{ items: Finding[] }>(session, "GET", `/workspaces/${customer.wsId}/anomalies?limit=100`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
}

async function duplicateOf(invoiceNumber: string): Promise<Finding> {
  const all = await findings();
  const found = all.find((finding) => finding.kind === "DUPLICATE_DOCUMENT" && finding.headline.includes(invoiceNumber));
  expect(found, `a duplicate finding naming ${invoiceNumber}; have ${all.map((f) => `${f.headline} [${f.status}]`).join(" | ")}`).toBeTruthy();
  return found as Finding;
}

async function uploadAndWait(file: string, expectedCount: number): Promise<void> {
  const upload = await uploadFile(customer.session, customer.wsId, file);
  expect(upload.status, upload.text.slice(0, 300)).toBe(201);
  await expect
    .poll(async () => {
      const items = await listWorkItems(customer.session, customer.wsId);
      const statuses = items.map((item) => String(item.status).toUpperCase());
      return items.length === expectedCount && statuses.every((status) => TERMINAL.has(status)) ? "ready" : `${items.length}/${expectedCount} documents: ${statuses.join(",")}`;
    }, { timeout: 180_000, intervals: [1_000, 2_000, 3_000] })
    .toBe("ready");
}

const paymentPanel = (page: Page) => page.getByRole("region", { name: "Payment risk" });
const flagRow = (page: Page, document: string, kind: Flag["kind"]) =>
  paymentPanel(page).getByRole("listitem").filter({ hasText: document }).filter({ hasText: KIND_LABEL[kind] });
const openCount = async (page: Page): Promise<number> => {
  const text = (await paymentPanel(page).getByText(/^\d+ open$/).textContent()) ?? "";
  return Number(text.replace(/\D/g, ""));
};
const findingRow = (page: Page, finding: Finding) =>
  page.getByRole("list", { name: "Findings" }).getByRole("listitem").filter({ hasText: finding.headline });

/** Open a finding's evidence (it may already be open: the row stays expanded when the filter changes). */
async function expandFinding(page: Page, finding: Finding): Promise<void> {
  const header = findingRow(page, finding).getByRole("button", { name: new RegExp(finding.headline.slice(0, 40)) });
  if ((await header.getAttribute("aria-expanded")) === "false") await header.click();
  await expect(header).toHaveAttribute("aria-expanded", "true");
}

async function openRadar(page: Page): Promise<void> {
  await page.goto(customer.ws("radar"));
  await settle(page);
  await expect(page.getByRole("heading", { name: "Audit radar", level: 1 })).toBeVisible();
  await expect(paymentPanel(page)).toBeVisible();
}

test.describe("Payment risk and anomalies — real findings, decided in the browser", () => {
  // Each test decides its own findings, so one failing test does not hide the ones after it.
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(600_000);
    customer = await newCustomer("radar", "Radar Decisions Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "3");
    viewer = await addMember(customer, "radar-viewer", "MEMBER", "VIEWER");

    // One at a time and in this order: "the vendor's previous invoice" is the one uploaded before.
    await uploadAndWait(writeInvoice(FILE.a, { number: NUMBER.a, account: ACCOUNT.x, total: "1250.00" }), 1);
    await uploadAndWait(writeInvoice(FILE.b, { number: NUMBER.b, account: ACCOUNT.y, total: "6000.00" }), 2);
    await uploadAndWait(writeInvoice(FILE.c, { number: NUMBER.c, account: ACCOUNT.z, total: "1250.00" }), 3);
    await uploadAndWait(writeInvoice(FILE.d, { number: NUMBER.a, account: ACCOUNT.x, total: "1250.00", extra: "Scanned copy received by post" }), 4);
    await uploadAndWait(writeInvoice(FILE.e, { number: NUMBER.b, account: ACCOUNT.y, total: "6000.00", extra: "Scanned copy received by post" }), 5);

    // The worker's scan runs after the documents settle: wait for what it should have raised.
    await expect
      .poll(async () => {
        const raised = await flags();
        const has = (document: string, kind: Flag["kind"]) => raised.some((f) => f.document === document && f.kind === kind);
        const dups = (await findings()).filter((f) => f.kind === "DUPLICATE_DOCUMENT").map((f) => f.headline).join("|");
        const missing = [
          ["b: changed account", has(FILE.b, "BANK_ACCOUNT_CHANGED")], ["b: round total", has(FILE.b, "ROUND_AMOUNT")],
          ["c: changed account", has(FILE.c, "BANK_ACCOUNT_CHANGED")], ["e: round total", has(FILE.e, "ROUND_AMOUNT")],
          ["duplicate of a", dups.includes(NUMBER.a)], ["duplicate of b", dups.includes(NUMBER.b)],
        ].filter(([, present]) => !present).map(([name]) => name);
        return missing.length === 0 ? "raised" : `not yet raised: ${missing.join(", ")}`;
      }, { timeout: 180_000, intervals: [1_000, 2_000, 3_000] })
      .toBe("raised");
  });

  test("the worker raised the findings: a changed account (HIGH) and a round total (LOW), accounts masked", async ({ page }) => {
    const bank = await flagOf(FILE.b, "BANK_ACCOUNT_CHANGED");
    expect([bank.severity, bank.status]).toEqual(["HIGH", "OPEN"]);
    // Only the last four characters of either account are ever stored or shown.
    expect(bank.summary).toContain("•••• 3459");
    expect(bank.summary).toContain("•••• 6819");
    expect(bank.summary).not.toContain(ACCOUNT.y.replace(/ /g, ""));
    const round = await flagOf(FILE.b, "ROUND_AMOUNT");
    expect([round.severity, round.status]).toEqual(["LOW", "OPEN"]);

    await signInAs(page, customer.email);
    await openRadar(page);
    const row = flagRow(page, FILE.b, "BANK_ACCOUNT_CHANGED");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("HIGH");
    await expect(row).toContainText("•••• 3459");
    await expect(row).toContainText("•••• 6819");
    await expect(row.getByRole("button", { name: "Confirm risk" })).toBeVisible();
    await expect(row.getByRole("button", { name: "Not a risk…" })).toBeVisible();
    await expect(flagRow(page, FILE.b, "ROUND_AMOUNT")).toContainText("LOW");
    await expectHealthyPage(page);
  });

  test("the server refuses an empty or too short reason, and a viewer; nothing changes", async () => {
    const target = await flagOf(FILE.c, "BANK_ACCOUNT_CHANGED");
    const base = `/workspaces/${customer.wsId}/payment-risk/${target.id}`;

    for (const reason of ["", "   ", "too short"]) {
      const refused = await api(customer.session, "POST", `${base}/dismiss`, { reason });
      expect(refused.status, `reason ${JSON.stringify(reason)}: ${refused.text.slice(0, 200)}`).toBe(422);
    }
    // A viewer reads the flags but can neither confirm nor dismiss.
    expect((await flags(viewer.session)).length).toBeGreaterThan(0);
    const confirm = await api(viewer.session, "POST", `${base}/confirm`);
    expect(confirm.status, confirm.text.slice(0, 200)).toBe(403);
    const dismiss = await api(viewer.session, "POST", `${base}/dismiss`, { reason: "A long enough reason from a viewer" });
    expect(dismiss.status, dismiss.text.slice(0, 200)).toBe(403);

    const after = await flagOf(FILE.c, "BANK_ACCOUNT_CHANGED");
    expect([after.status, after.review_note, after.reviewed_at]).toEqual(["OPEN", null, null]);
  });

  test("a viewer sees the payment risk but is not offered a decision", async ({ page }) => {
    await signInAs(page, viewer.email);
    await openRadar(page);
    const row = flagRow(page, FILE.c, "BANK_ACCOUNT_CHANGED");
    await expect(row).toHaveCount(1);
    await expect(paymentPanel(page).getByRole("button", { name: "Confirm risk" })).toHaveCount(0);
    await expect(paymentPanel(page).getByRole("button", { name: "Not a risk…" })).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("a viewer is not offered an anomaly decision, and the server refuses one; the finding stays open", async ({ page }) => {
    const target = await duplicateOf(NUMBER.a);
    const base = `/workspaces/${customer.wsId}/anomalies/${target.id}`;
    const confirm = await api(viewer.session, "POST", `${base}/confirm`, {});
    expect(confirm.status, confirm.text.slice(0, 200)).toBe(403);
    const dismiss = await api(viewer.session, "POST", `${base}/dismiss`, { reason: "A viewer should not be able to say this" });
    expect(dismiss.status, dismiss.text.slice(0, 200)).toBe(403);

    // In the browser the evidence is readable but there is nothing to press (as on the payment panel).
    await signInAs(page, viewer.email);
    await openRadar(page);
    await expandFinding(page, target);
    const row = findingRow(page, target);
    await expect(row.getByRole("button", { name: "This is a real finding" })).toHaveCount(0);
    await expect(row.getByRole("button", { name: "Not an anomaly" })).toHaveCount(0);
    await expect(row.getByRole("textbox")).toHaveCount(0);
    await expect(row.getByText("Only contributors and administrators can decide a finding.")).toBeVisible();
    expect((await api<Finding>(customer.session, "GET", base)).body.status).toBe("OPEN");
  });

  test("Confirm risk settles the flag as confirmed; it survives a reload and shows under Show settled", async ({ page }) => {
    const target = await flagOf(FILE.b, "BANK_ACCOUNT_CHANGED");
    await signInAs(page, customer.email);
    await openRadar(page);
    const before = await openCount(page);
    expect(before).toBe((await flags()).filter((f) => f.status === "OPEN").length);

    const row = flagRow(page, FILE.b, "BANK_ACCOUNT_CHANGED");
    const decided = page.waitForResponse((r) => r.url().includes(`/payment-risk/${target.id}/confirm`) && r.request().method() === "POST");
    await row.getByRole("button", { name: "Confirm risk" }).click();
    expect((await decided).status()).toBe(200);

    // Settled flags leave the open list and the count drops by one.
    await expect(flagRow(page, FILE.b, "BANK_ACCOUNT_CHANGED")).toHaveCount(0);
    await expect.poll(() => openCount(page)).toBe(before - 1);
    await paymentPanel(page).getByLabel("Show settled").check();
    const settled = flagRow(page, FILE.b, "BANK_ACCOUNT_CHANGED");
    await expect(settled).toContainText("CONFIRMED");
    await expect(settled.getByRole("button", { name: "Confirm risk" })).toHaveCount(0);

    const saved = await flagOf(FILE.b, "BANK_ACCOUNT_CHANGED");
    expect([saved.status, saved.review_note]).toEqual(["CONFIRMED", null]);
    expect(saved.reviewed_at).toBeTruthy();
    expect((await flagOf(FILE.b, "ROUND_AMOUNT")).status).toBe("OPEN");  // only that flag moved

    await page.reload();
    await settle(page);
    await expect(flagRow(page, FILE.b, "BANK_ACCOUNT_CHANGED")).toHaveCount(0);
    await paymentPanel(page).getByLabel("Show settled").check();
    await expect(flagRow(page, FILE.b, "BANK_ACCOUNT_CHANGED")).toContainText("CONFIRMED");
    // A flag cannot be decided twice.
    const twice = await api(customer.session, "POST", `/workspaces/${customer.wsId}/payment-risk/${target.id}/dismiss`, { reason: "Changing my mind afterwards" });
    expect(twice.status).toBe(409);
    expect((await flagOf(FILE.b, "BANK_ACCOUNT_CHANGED")).status).toBe("CONFIRMED");
    await expectHealthyPage(page);
  });

  test("Not a risk… needs a reason of 10 characters; Cancel changes nothing; the reason is shown as the reviewer's note", async ({ page }) => {
    const target = await flagOf(FILE.b, "ROUND_AMOUNT");
    const reason = `Fixed monthly retainer agreed in the contract (${SUFFIX})`;
    await signInAs(page, customer.email);
    await openRadar(page);
    const row = flagRow(page, FILE.b, "ROUND_AMOUNT");

    await row.getByRole("button", { name: "Not a risk…" }).click();
    const box = row.getByRole("textbox", { name: "Why this is not a risk" });
    const dismiss = row.getByRole("button", { name: "Dismiss", exact: true });
    await expect(box).toBeVisible();
    await expect(dismiss).toBeDisabled();
    await box.fill("   ");
    await expect(dismiss).toBeDisabled();
    await box.fill("too short");  // 9 characters
    await expect(dismiss).toBeDisabled();

    // Cancel closes the box and records nothing.
    await row.getByRole("button", { name: "Cancel" }).click();
    await expect(box).toHaveCount(0);
    await expect(row.getByRole("button", { name: "Not a risk…" })).toBeVisible();
    expect((await flagOf(FILE.b, "ROUND_AMOUNT")).status).toBe("OPEN");

    await row.getByRole("button", { name: "Not a risk…" }).click();
    await box.fill("exactly 10");
    await expect(dismiss).toBeEnabled();
    await box.fill(reason);
    const decided = page.waitForResponse((r) => r.url().includes(`/payment-risk/${target.id}/dismiss`) && r.request().method() === "POST");
    await dismiss.click();
    const response = await decided;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toEqual({ reason });

    await expect(flagRow(page, FILE.b, "ROUND_AMOUNT")).toHaveCount(0);
    await paymentPanel(page).getByLabel("Show settled").check();
    const settled = flagRow(page, FILE.b, "ROUND_AMOUNT");
    await expect(settled).toContainText("DISMISSED");
    await expect(settled).toContainText(`Reviewer: ${reason}`);

    const saved = await flagOf(FILE.b, "ROUND_AMOUNT");
    expect([saved.status, saved.review_note]).toEqual(["DISMISSED", reason]);
    expect(saved.reviewed_at).toBeTruthy();

    await page.reload();
    await settle(page);
    await paymentPanel(page).getByLabel("Show settled").check();
    await expect(flagRow(page, FILE.b, "ROUND_AMOUNT")).toContainText(`Reviewer: ${reason}`);
    // The viewer reads the same reason.
    const asViewer = (await flags(viewer.session)).find((f) => f.id === target.id);
    expect(asViewer?.review_note).toBe(reason);
    await expectHealthyPage(page);
  });

  test("This is a real finding confirms a duplicate; it leaves Open, shows under Confirmed and survives a reload", async ({ page }) => {
    const target = await duplicateOf(NUMBER.b);
    expect(target.status).toBe("OPEN");
    await signInAs(page, customer.email);
    await openRadar(page);

    await expandFinding(page, target);
    const row = findingRow(page, target);
    const decided = page.waitForResponse((r) => r.url().includes(`/anomalies/${target.id}/confirm`) && r.request().method() === "POST");
    await row.getByRole("button", { name: "This is a real finding" }).click();
    expect((await decided).status()).toBe(200);

    // Gone from the Open feed; the Confirmed filter lists it.
    await expect(findingRow(page, target)).toHaveCount(0);
    await page.getByLabel("Status").selectOption("CONFIRMED");
    const confirmed = findingRow(page, target);
    await expect(confirmed).toBeVisible();
    await expect(confirmed).toContainText("confirmed");
    await expandFinding(page, target);
    await expect(confirmed).toContainText(/Confirmed\s/);
    await expect(confirmed.getByRole("button", { name: "This is a real finding" })).toHaveCount(0);

    const saved = await api<Finding>(customer.session, "GET", `/workspaces/${customer.wsId}/anomalies/${target.id}`);
    expect([saved.body.status]).toEqual(["CONFIRMED"]);
    expect(saved.body.resolved_at).toBeTruthy();
    const other = await duplicateOf(NUMBER.a);
    expect(other.status).toBe("OPEN");  // only that finding moved

    await page.reload();
    await settle(page);
    await page.getByLabel("Status").selectOption("CONFIRMED");
    await expect(findingRow(page, target)).toBeVisible();
    await expectHealthyPage(page);
  });

  test("Not an anomaly needs a reason, keeps it and records a suppression for the pair", async ({ page }) => {
    const target = await duplicateOf(NUMBER.a);
    const reason = `The supplier re-sends scans of the same invoice (${SUFFIX})`;
    await signInAs(page, customer.email);
    await openRadar(page);

    await expandFinding(page, target);
    const row = findingRow(page, target);
    const box = row.getByRole("textbox");
    const dismiss = row.getByRole("button", { name: "Not an anomaly" });
    await expect(box).toBeVisible();
    await expect(dismiss).toBeDisabled();
    await box.fill("   ");
    await expect(dismiss).toBeDisabled();
    // The server refuses an empty reason on its own account as well.
    const refused = await api(customer.session, "POST", `/workspaces/${customer.wsId}/anomalies/${target.id}/dismiss`, { reason: "   " });
    expect(refused.status, refused.text.slice(0, 200)).toBe(422);
    expect((await duplicateOf(NUMBER.a)).status).toBe("OPEN");

    await box.fill(reason);
    const decided = page.waitForResponse((r) => r.url().includes(`/anomalies/${target.id}/dismiss`) && r.request().method() === "POST");
    await dismiss.click();
    expect((await decided).status()).toBe(200);

    await expect(findingRow(page, target)).toHaveCount(0);
    await page.getByLabel("Status").selectOption("DISMISSED");
    const dismissed = findingRow(page, target);
    await expect(dismissed).toBeVisible();
    await expandFinding(page, target);
    await expect(dismissed).toContainText(`— ${reason}`);

    const saved = await api<Finding>(customer.session, "GET", `/workspaces/${customer.wsId}/anomalies/${target.id}`);
    expect([saved.body.status, saved.body.resolution_note]).toEqual(["DISMISSED", reason]);
    expect(saved.body.resolved_at).toBeTruthy();
    // The decision is also a standing rule: an administrator sees a suppression.
    const suppressions = await api<Suppression[]>(customer.session, "GET", `/workspaces/${customer.wsId}/anomalies/suppressions`);
    expect(suppressions.status, suppressions.text.slice(0, 200)).toBe(200);
    const pair = new Set([saved.body.subject_work_item_id, saved.body.counterpart_work_item_id]);
    const rule = suppressions.body.find((entry) => pair.has(entry.item_a_id) && pair.has(entry.item_b_id));
    expect(rule, "a suppression for the dismissed pair").toBeTruthy();
    expect(rule?.reason).toBe(reason);

    await page.reload();
    await settle(page);
    await page.getByLabel("Status").selectOption("DISMISSED");
    await expandFinding(page, target);
    await expect(findingRow(page, target)).toContainText(`— ${reason}`);
    await expectHealthyPage(page);
  });

  test("a reason of only blanks is refused, not saved as an empty note", async () => {
    // "          " is 12 characters, so a length check alone lets it through; the reason is then trimmed
    // and the dismissal would be recorded with nothing in it, for the next reviewer to read.
    const target = await flagOf(FILE.e, "ROUND_AMOUNT");
    const blank = await api(customer.session, "POST", `/workspaces/${customer.wsId}/payment-risk/${target.id}/dismiss`, { reason: " ".repeat(12) });
    expect(blank.status, `twelve blanks as a reason: ${blank.text.slice(0, 200)}`).toBeGreaterThanOrEqual(400);
    const after = await flagOf(FILE.e, "ROUND_AMOUNT");
    expect([after.status, after.review_note]).toEqual(["OPEN", null]);
  });
});
