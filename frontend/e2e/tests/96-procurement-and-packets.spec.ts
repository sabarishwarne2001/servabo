/**
 * PROCUREMENT AND PACKETS: buttons no browser test had pressed (campaign Session C).
 *
 * On Enterprise tenants of their own, with real uploads read by the worker:
 *
 *   1. Three-way match, "Flag dispute": the dialog needs 10+ characters, Cancel changes nothing, the
 *      dispute is written (status, reason, who, audit row) and the case locks; "Approve match" is
 *      one click on a clean match and asks for a written reason when lines did not match.
 *   2. Supplier cost console (platform administrator, Unit economics): "Record invoice", "Reconcile"
 *      (a closed period reconciles; one that is still open is refused with the server's words) and
 *      the "Accept" that a variance with nothing modelled offers.
 *   3. Packets: "Save boundaries", "Approve split" (on the split page and in the Review hub) and
 *      "Keep as one document" on a scanned multi-document packet the worker proposed to divide.
 *
 * Each result is read on the page, through the API and after a reload. A viewer cannot do any of it
 * (the server answers 403), and the page does not offer it.
 *
 * Also on the page since the second pass: the stored reason is shown on a decided case; "Re-score" queues a
 * new score and the old case is shown as replaced; supplier-cost "Reconcile anyway" forces a period that is
 * not closed yet, after the server's refusal. Not reachable at all (the API has no such call): case notes
 * and a "Reject" separate from "Flag dispute"; see NEEDS-OWNER N-131.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import type { Dialog, Locator, Page } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, listWorkItems, loginAs, uploadFile, type ApiSession } from "../support/api";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf, samplePath } from "../support/sample-docs";

const tag = runId().toUpperCase();
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "servabo-e2e-procpack-"));

async function uploadLines(customer: Customer, name: string, lines: string[][]): Promise<string> {
  const file = path.join(dir, name);
  fs.writeFileSync(file, buildPdf(lines));
  const sent = await uploadFile(customer.session, customer.wsId, file);
  expect(sent.status, sent.text.slice(0, 300)).toBe(201);
  return String((sent.body as { id: string }).id);
}

async function allProcessed(customer: Customer, count: number, timeout = 300_000): Promise<void> {
  await expect
    .poll(async () => {
      const items = await listWorkItems(customer.session, customer.wsId);
      return items.length === count && items.every((i) => /COMPLETED|NEEDS_REVIEW/.test(String(i.status)))
        ? "ready"
        : items.map((i) => i.status).join(",");
    }, { timeout, intervals: [2_000, 3_000] })
    .toBe("ready");
}

/* ------------------------------------------------------------------------------------------------
 * 1 and 3 (case actions): three-way match
 * ---------------------------------------------------------------------------------------------- */

interface CaseRow {
  id: string;
  status: string;
  invoice_number: string | null;
  exception_count: number;
  line_count: number;
}
interface CaseDetail extends CaseRow {
  resolution_reason: string | null;
  resolved_by_user_id: string | null;
}
interface AuditRow {
  action: string;
  actor_id: string | null;
  resource_type: string;
  details: Record<string, unknown> | null;
}

const BUYER = "Procurement Actions Ltd";
type CaseKey = "dispute" | "clean" | "override" | "stale" | "shared" | "watched";
const SETS: Record<CaseKey, { vendor: string; po: string; invoice: string; receivedGloves: number; invoicePrice: string }> = {
  dispute: { vendor: `Alder Fasteners ${tag} Ltd`, po: `PO-D-${tag}`, invoice: `INV-D-${tag}`, receivedGloves: 98, invoicePrice: "5.00" },
  clean: { vendor: `Birch Tooling ${tag} Ltd`, po: `PO-C-${tag}`, invoice: `INV-C-${tag}`, receivedGloves: 100, invoicePrice: "5.00" },
  override: { vendor: `Cedar Packaging ${tag} Ltd`, po: `PO-O-${tag}`, invoice: `INV-O-${tag}`, receivedGloves: 100, invoicePrice: "6.00" },
  stale: { vendor: `Dogwood Safety ${tag} Ltd`, po: `PO-S-${tag}`, invoice: `INV-S-${tag}`, receivedGloves: 98, invoicePrice: "5.00" },
  watched: { vendor: `Fir Components ${tag} Ltd`, po: `PO-W-${tag}`, invoice: `INV-W-${tag}`, receivedGloves: 96, invoicePrice: "5.00" },
  shared: { vendor: `Elm Logistics ${tag} Ltd`, po: `PO-H-${tag}`, invoice: `INV-H-${tag}`, receivedGloves: 97, invoicePrice: "5.00" },
};

let proc: Customer;
let procViewer: { email: string; session: ApiSession };
let procContributor: { email: string; session: ApiSession };
const caseIds = {} as Record<CaseKey, string>;

const procApi = (suffix = ""): string => `/workspaces/${proc.wsId}/procurement${suffix}`;

async function caseDetail(id: string, session: ApiSession = proc.session): Promise<CaseDetail> {
  const got = await api<CaseDetail>(session, "GET", procApi(`/cases/${id}`));
  expect(got.status, got.text.slice(0, 300)).toBe(200);
  return got.body;
}

async function auditOfCase(id: string, action: string): Promise<AuditRow[]> {
  let rows: AuditRow[] = [];
  await expect
    .poll(async () => {
      const listed = await api<{ items: AuditRow[] }>(proc.session, "GET",
        `/organizations/${proc.orgId}/audit-logs?resource_type=PROCUREMENT_CASE&resource_id=${id}`);
      expect(listed.status, listed.text.slice(0, 200)).toBe(200);
      rows = listed.body.items.filter((r) => r.action === action);
      return rows.length;
    }, { timeout: 30_000, intervals: [500, 1_000, 2_000] })
    .toBeGreaterThan(0);
  return rows;
}

const statusBadge = (page: Page, text: string): Locator =>
  page.getByRole("heading", { level: 1 }).locator("xpath=following-sibling::span").filter({ hasText: text });

/** The dispute / approve-anyway dialog: a plain panel under its own heading. */
const dialogOf = (page: Page, heading: string | RegExp): Locator =>
  page.getByRole("heading", { name: heading, level: 2 }).locator("xpath=..");

test.describe("Procurement case actions — a tenant of its own, real three-way matches", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(180_000);

  test.beforeAll(async () => {
    test.setTimeout(600_000);
    proc = await newCustomer("proc", BUYER);
    standIn("subscribe", proc.orgSlug, "--plan", "enterprise", "--seats", "4");
    // The tolerance is set BEFORE the documents arrive: publishing a policy re-matches the cases.
    const policy = await api(proc.session, "POST", procApi("/policies"), { price_tolerance_bps: 500 });
    expect(policy.status, policy.text.slice(0, 200)).toBeLessThan(300);

    for (const [key, set] of Object.entries(SETS)) {
      await uploadLines(proc, `purchase-order-${key}-${tag}.pdf`, [[
        "PURCHASE ORDER", `Buyer: ${BUYER}`, `Vendor: ${set.vendor}`, `PO Number: ${set.po}`, "PO Date: 2026-09-01",
        "Currency: USD", "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00",
        "|2|Steel toe boots|10|60.00|600.00", "PO Total: 1100.00 USD"]]);
      await uploadLines(proc, `goods-receipt-${key}-${tag}.pdf`, [[
        "GOODS RECEIPT NOTE", `Receiver: ${BUYER} warehouse 3`, `Vendor: ${set.vendor}`, `Receipt Number: GR-${key}-${tag}`,
        `PO Number: ${set.po}`, "Received Date: 2026-09-12", "|#|Description|Qty received",
        `|1|Industrial safety gloves|${set.receivedGloves}`, "|2|Steel toe boots|10"]]);
      const glovesAmount = (100 * Number(set.invoicePrice)).toFixed(2);
      const subtotal = (100 * Number(set.invoicePrice) + 600).toFixed(2);
      await uploadLines(proc, `invoice-${set.invoice}.pdf`, [[
        "INVOICE", `Vendor: ${set.vendor}`, "Vendor Address: 12 Foundry Road, Leeds LS1 4AB, United Kingdom",
        "Vendor Bank Account: GB29 NWBK 6016 1331 9268 19", `Bill To: ${BUYER}`, `Invoice Number: ${set.invoice}`,
        "Invoice Date: 2026-09-15", "Due Date: 2026-10-15", `PO Number: ${set.po}`, "Currency: USD", "Line items:",
        "|#|Description|Qty|Unit Price|Amount", `|1|Industrial safety gloves|100|${set.invoicePrice}|${glovesAmount}`,
        "|2|Steel toe boots|10|60.00|600.00", `Subtotal: ${subtotal}`,
        // The clean set prints no tax, so its total is the sum of its lines (no header finding either).
        ...(key === "clean" ? [`Total Amount Due: ${subtotal} USD`] : ["Tax (VAT 13.64%): 150.00", `Total Amount Due: ${(Number(subtotal) + 150).toFixed(2)} USD`]),
        "Payment terms: Net 30"]]);
    }
    await allProcessed(proc, 18);

    await expect
      .poll(async () => {
        const listed = await api<CaseRow[]>(proc.session, "GET", procApi("/cases?limit=100"));
        const live = (Array.isArray(listed.body) ? listed.body : []).filter((c) => c.status !== "SUPERSEDED");
        for (const [key, set] of Object.entries(SETS)) {
          const mine = live.filter((c) => c.invoice_number === set.invoice);
          if (mine.length !== 1) return `${key}: ${mine.length} cases`;
          caseIds[key as CaseKey] = mine[0]?.id ?? "";
        }
        return "ready";
      }, { timeout: 180_000, intervals: [1_000, 2_000, 3_000] })
      .toBe("ready");

    procViewer = await addMember(proc, "proc-viewer", "MEMBER", "VIEWER");
    procContributor = await addMember(proc, "proc-contrib", "MEMBER", "CONTRIBUTOR");
  });

  test("the cases are what the tests rely on: exceptions on four, a clean match on one", async () => {
    const dispute = await caseDetail(caseIds.dispute);
    const clean = await caseDetail(caseIds.clean);
    const override = await caseDetail(caseIds.override);
    const stale = await caseDetail(caseIds.stale);
    const shared = await caseDetail(caseIds.shared);
    const watched = await caseDetail(caseIds.watched);
    expect(dispute.exception_count, "98 of 100 gloves received").toBeGreaterThan(0);
    expect(override.exception_count, "6.00 invoiced against 5.00 ordered, over a 5% tolerance").toBeGreaterThan(0);
    expect(stale.exception_count).toBeGreaterThan(0);
    expect(shared.exception_count).toBeGreaterThan(0);
    expect(watched.exception_count).toBeGreaterThan(0);
    expect(clean.exception_count).toBe(0);
    expect(clean.line_count).toBeGreaterThan(0);
    for (const c of [dispute, clean, override, stale, shared, watched]) expect(["NEEDS_REVIEW", "MATCHED", "OPEN"]).toContain(c.status);
  });

  test("Flag dispute: needs a real reason, Cancel changes nothing, and the dispute is written and locks the case", async ({ page }) => {
    const id = caseIds.dispute;
    await signInAs(page, proc.email);
    await page.goto(proc.ws("procurement"));
    await expect(page.getByRole("heading", { name: "Invoice matching" })).toBeVisible();
    // The queue offers the case by its invoice number; Review opens it.
    const row = page.getByRole("row").filter({ hasText: SETS.dispute.invoice });
    await expect(row).toHaveCount(1);
    await row.getByRole("link", { name: "Review" }).click();
    await expect(page).toHaveURL(new RegExp(`/procurement/${id}$`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.dispute.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByText(/\d+ needing attention/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeEnabled();

    // Cancel: the dialog closes and nothing was written.
    await page.getByRole("button", { name: "Flag dispute" }).click();
    const dialog = dialogOf(page, "Flag a dispute");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("At least 10 characters");
    await dialog.getByLabel("Dispute reason").fill("too short");
    await expect(dialog.getByRole("button", { name: "Flag dispute" })).toBeDisabled();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect((await caseDetail(id)).status).not.toBe("DISPUTED");

    // Nine characters (plus spaces that do not count) are still too short; ten go through.
    await page.getByRole("button", { name: "Flag dispute" }).click();
    await dialog.getByLabel("Dispute reason").fill("  123456789  ");
    await expect(dialog.getByRole("button", { name: "Flag dispute" })).toBeDisabled();
    const reason = "Only 98 of the 100 gloves arrived; credit the 2 missing before we pay.";
    await dialog.getByLabel("Dispute reason").fill(reason);
    await expect(dialog.getByRole("button", { name: "Flag dispute" })).toBeEnabled();
    await dialog.getByRole("button", { name: "Flag dispute" }).click();

    // The page: dialog gone, status disputed, both actions locked.
    await expect(dialog).toHaveCount(0);
    await expect(statusBadge(page, "disputed")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve match" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Re-score" })).toBeDisabled();
    // The reason on record is on the page: what went to the supplier, under a heading that says so.
    const recorded = page.getByTestId("resolution-reason");
    await expect(recorded).toContainText("Why it was disputed");
    await expect(recorded).toContainText(reason);

    // The API: the dispute, its reason, and who made it.
    const stored = await caseDetail(id);
    expect(stored.status).toBe("DISPUTED");
    expect(stored.resolution_reason).toBe(reason);
    expect(stored.resolved_by_user_id).toBe(String(proc.session.me.id));
    const audit = await auditOfCase(id, "MATCH_DISPUTED");
    expect(audit).toHaveLength(1);
    expect(audit[0]?.actor_id).toBe(String(proc.session.me.id));

    // After a reload it is still disputed and still locked, and the reason is still shown.
    await page.reload();
    await expect(statusBadge(page, "disputed")).toBeVisible();
    await expect(page.getByTestId("resolution-reason")).toContainText(reason);
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Approve match" })).toBeDisabled();

    // The queue files it under Disputed, counted in the Resolved tile, and not under Needs review.
    await page.goto(proc.ws("procurement"));
    await page.getByRole("button", { name: "Disputed" }).click();
    await expect(page.getByRole("row").filter({ hasText: SETS.dispute.invoice })).toHaveCount(1);
    await page.getByRole("button", { name: "Needs review" }).click();
    await expect(page.getByRole("row").filter({ hasText: SETS.dispute.invoice })).toHaveCount(0);
    await expect(page.getByLabel("Matching at a glance")).toContainText(/\d+ approved · [1-9]\d* disputed/);

    // A second dispute (a second tab) is refused: the case is no longer live; the first reason stands.
    const again = await api<{ detail: { code: string } }>(proc.session, "POST", procApi(`/cases/${id}/dispute`), { reason: "A different, longer reason." });
    expect(again.status).toBe(409);
    expect(again.body.detail.code).toBe("CASE_NOT_LIVE");
    expect((await caseDetail(id)).resolution_reason).toBe(reason);
    await expectHealthyPage(page);
  });

  test("Flag dispute from another tab: a case someone else already resolved says so and stays as it was", async ({ page, problems }) => {
    // The page is opened while the case is live; before the button is pressed it is resolved elsewhere.
    problems.allowHttp(/\/procurement\/cases\/[0-9a-f-]+\/dispute/, [409], "the case was resolved in another tab");
    const id = caseIds.stale;
    await signInAs(page, proc.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.stale.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeEnabled();

    const approved = await api<CaseDetail>(proc.session, "POST", procApi(`/cases/${id}/approve`), { override_reason: "Approved in another tab, exception accepted." });
    expect(approved.status, approved.text.slice(0, 300)).toBe(200);

    await page.getByRole("button", { name: "Flag dispute" }).click();
    const dialog = dialogOf(page, "Flag a dispute");
    await dialog.getByLabel("Dispute reason").fill("Disputing this from a stale tab.");
    await dialog.getByRole("button", { name: "Flag dispute" }).click();
    await expect(page.getByRole("alert")).toContainText("already resolved or re-scored");
    expect((await caseDetail(id)).status).toBe("APPROVED");
    expect((await caseDetail(id)).resolution_reason).toBe("Approved in another tab, exception accepted.");
  });

  test("Approve match on a clean match is one click: approved, no reason asked, nothing disputed", async ({ page }) => {
    const id = caseIds.clean;
    const before = await api<{ status: string; header_findings: unknown; lines: Array<{ outcome: string }> }>(proc.session, "GET", procApi(`/cases/${id}`));
    expect(before.body.status, JSON.stringify([before.body.header_findings, before.body.lines.map((l) => l.outcome)])).toMatch(/^(MATCHED|NEEDS_REVIEW)$/);
    await signInAs(page, proc.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.clean.invoice}`, level: 1 })).toBeVisible();
    await expect(statusBadge(page, before.body.status.replace("_", " ").toLowerCase())).toBeVisible();
    await expect(page.getByText("0 needing attention")).toBeVisible();
    // Every line says Match, in words.
    await expect(page.getByRole("cell", { name: "Match", exact: true })).toHaveCount(2);

    await page.getByRole("button", { name: "Approve match" }).click();
    await expect(statusBadge(page, "approved")).toBeVisible();
    await expect(page.getByRole("heading", { name: /Approve (with|without)/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Approve match" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeDisabled();

    const stored = await caseDetail(id);
    expect(stored.status).toBe("APPROVED");
    expect(stored.resolution_reason).toBeNull();
    expect(stored.resolved_by_user_id).toBe(String(proc.session.me.id));
    const audit = await auditOfCase(id, "MATCH_APPROVED");
    expect(audit[0]?.details).toMatchObject({ override_given: false, exception_count: 0 });
    await page.reload();
    await expect(statusBadge(page, "approved")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve match" })).toBeDisabled();
    await expectHealthyPage(page);
  });

  test("Approve match on a case with exceptions asks why; no reason, no approval; the reason is kept with the approval", async ({ page }) => {
    const id = caseIds.override;
    await signInAs(page, proc.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.override.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByText(/[1-9]\d* needing attention/)).toBeVisible();
    await expect(page.getByRole("cell", { name: /% price$/ })).toHaveCount(1);

    await page.getByRole("button", { name: "Approve match" }).click();
    const dialog = dialogOf(page, /^Approve with \d+ unresolved lines?$/);
    await expect(dialog).toBeVisible();
    // The case is still open; the approve button waits for words.
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");
    await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    await dialog.getByLabel("Override reason").fill("   ");
    await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    // Cancel leaves it open.
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");

    // The server refuses the same approval without a reason, whoever drives it.
    const bare = await api<{ detail: { code: string } }>(proc.session, "POST", procApi(`/cases/${id}/approve`), {});
    expect(bare.status).toBe(422);
    expect(bare.body.detail.code).toBe("OVERRIDE_REASON_REQUIRED");
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");

    await page.getByRole("button", { name: "Approve match" }).click();
    const reason = "Supplier agreed the new price in writing on 2026-09-14; ticket PRC-2217.";
    await dialog.getByLabel("Override reason").fill(reason);
    await dialog.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(statusBadge(page, "approved")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve match" })).toBeDisabled();
    await expect(page.getByTestId("resolution-reason")).toContainText("Why it was approved");
    await expect(page.getByTestId("resolution-reason")).toContainText(reason);

    const stored = await caseDetail(id);
    expect(stored.status).toBe("APPROVED");
    expect(stored.resolution_reason).toBe(reason);
    const audit = await auditOfCase(id, "MATCH_APPROVED");
    expect(audit[0]?.details).toMatchObject({ override_given: true });
    expect(audit[0]?.details?.red_outcomes).toContain("PRICE_VARIANCE");
    await page.reload();
    await expect(statusBadge(page, "approved")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("a line opens its source document beside the grid, and Close puts the grid back", async ({ page }) => {
    await signInAs(page, proc.email);
    await page.goto(proc.ws(`procurement/${caseIds.clean}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.clean.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByLabel("Source document")).toHaveCount(0);
    await page.getByRole("row").filter({ hasText: "Industrial safety gloves" }).click();
    const source = page.getByLabel("Source document");
    await expect(source).toBeVisible();
    await expect(source).toContainText("invoice");
    await source.getByRole("button", { name: "Close" }).click();
    await expect(source).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("a viewer cannot approve or dispute: the server refuses both (403) and the case is unchanged", async () => {
    const id = caseIds.shared;
    for (const [suffix, body] of [["approve", { override_reason: "A viewer's perfectly long reason." }], ["dispute", { reason: "A viewer's perfectly long reason." }]] as const) {
      const refused = await api(procViewer.session, "POST", procApi(`/cases/${id}/${suffix}`), body);
      expect(refused.status, `${suffix}: ${refused.text.slice(0, 200)}`).toBe(403);
    }
    expect((await caseDetail(id)).status, "the refusals changed nothing").toBe("NEEDS_REVIEW");
    expect((await caseDetail(id)).resolution_reason).toBeNull();
    // The viewer can read it.
    expect((await caseDetail(id, procViewer.session)).id).toBe(id);
  });

  test("a contributor decides with the keyboard: d opens the dispute dialog, and the dispute stands", async ({ page }) => {
    const id = caseIds.shared;
    await signInAs(page, procContributor.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.shared.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeEnabled();
    await page.getByRole("heading", { level: 1 }).click();
    await page.keyboard.press("j");
    await expect(page.getByRole("row").filter({ hasText: "Steel toe boots" })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("k");
    await expect(page.getByRole("row").filter({ hasText: "Industrial safety gloves" })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("d");
    const dialog = dialogOf(page, "Flag a dispute");
    await expect(dialog).toBeVisible();
    const reason = "Receipt shows 97 gloves, invoice bills 100: please correct the invoice.";
    await dialog.getByLabel("Dispute reason").fill(reason);
    await dialog.getByRole("button", { name: "Flag dispute" }).click();
    await expect(statusBadge(page, "disputed")).toBeVisible();

    const stored = await caseDetail(id);
    expect(stored.status).toBe("DISPUTED");
    expect(stored.resolution_reason).toBe(reason);
    expect(stored.resolved_by_user_id).toBe(String(procContributor.session.me.id));
    await page.reload();
    await expect(statusBadge(page, "disputed")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("a viewer's Flag dispute button is disabled: no dialog opens and nothing changes (F-510)", async ({ page }) => {
    const id = caseIds.watched;
    await signInAs(page, procViewer.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.watched.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Approve match" })).toBeDisabled();
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");
    await expect(statusBadge(page, "needs review")).toBeVisible();
  });

  test("a dispute reason that was cancelled does not turn up in the approval box (F-511)", async ({ page }) => {
    const id = caseIds.watched;
    await signInAs(page, proc.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.watched.invoice}`, level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Flag dispute" }).click();
    const dispute = dialogOf(page, "Flag a dispute");
    await dispute.getByLabel("Dispute reason").fill("Words meant for the supplier, not for the approval.");
    await dispute.getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "Approve match" }).click();
    const approve = dialogOf(page, /^Approve with \d+ unresolved lines?$/);
    await expect(approve.getByLabel("Override reason")).toHaveValue("");
    await approve.getByRole("button", { name: "Cancel" }).click();
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");
  });

  test("a viewer is not offered Approve match or Flag dispute, nor the d and a shortcuts", async ({ page }) => {
    const id = caseIds.watched;
    await signInAs(page, procViewer.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.watched.invoice}`, level: 1 })).toBeVisible();
    for (const button of await page.getByRole("button", { name: /^(Approve match|Flag dispute|Re-score)$/ }).all()) {
      await expect(button).toBeDisabled();
    }
    await page.getByRole("heading", { level: 1 }).click();
    await page.keyboard.press("d");
    await page.keyboard.press("a");
    await expect(page.getByRole("heading", { name: /^(Flag a dispute|Approve with)/ })).toHaveCount(0);
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");
  });

  test("Re-score scores again: unchanged documents leave the case as it is; a changed policy replaces it, and the old one is history", async ({ page }) => {
    const id = caseIds.watched;
    const liveCases = async (): Promise<CaseRow[]> => {
      const listed = await api<CaseRow[]>(proc.session, "GET", procApi("/cases?limit=100"));
      return (Array.isArray(listed.body) ? listed.body : [])
        .filter((c) => c.invoice_number === SETS.watched.invoice && c.status !== "SUPERSEDED");
    };
    await signInAs(page, proc.email);
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByRole("heading", { name: `Three-way match · ${SETS.watched.invoice}`, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-score" })).toBeEnabled();

    // Nothing on file has changed: the page says it is queued, then that this is still the current case.
    await page.getByRole("button", { name: "Re-score" }).click();
    await expect(page.getByText("Re-scoring is queued.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-score" })).toBeDisabled();
    await expect(page.getByText("Nothing had changed, so this is still the current case.")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("button", { name: "Re-score" })).toBeEnabled();
    expect((await caseDetail(id)).status).toBe("NEEDS_REVIEW");
    expect((await liveCases()).map((c) => c.id)).toEqual([id]);

    // The inputs change (a new tolerance is published): the next score replaces this case with a new one,
    // and the open page, which looks again while the score is queued, says so.
    const published = await api(proc.session, "POST", procApi("/policies"), { price_tolerance_bps: 700 });
    expect(published.status, published.text.slice(0, 200)).toBeLessThan(300);
    await page.reload();
    await page.getByRole("button", { name: "Re-score" }).click();
    await expect(page.getByText("This case was replaced by a newer score")).toBeVisible({ timeout: 90_000 });
    await expect
      .poll(async () => (await caseDetail(id)).status, { timeout: 90_000, intervals: [1_000, 2_000, 3_000] })
      .toBe("SUPERSEDED");
    await expect.poll(async () => (await liveCases()).length, { timeout: 30_000 }).toBe(1);
    const live = await liveCases();
    expect(live[0]?.id).not.toBe(id);

    // The old case, opened again, is plainly history: no decision is offered, and the server would refuse one.
    await page.goto(proc.ws(`procurement/${id}`));
    await expect(page.getByText("This case was replaced by a newer score")).toBeVisible();
    for (const name of ["Approve match", "Flag dispute", "Re-score"]) {
      await expect(page.getByRole("button", { name })).toBeDisabled();
    }
    const refused = await api<{ detail: { code: string } }>(proc.session, "POST", procApi(`/cases/${id}/approve`), { override_reason: "Too late." });
    expect(refused.status).toBe(409);
    expect(refused.body.detail.code).toBe("CASE_NOT_LIVE");

    // The current case is live and can be decided.
    await page.goto(proc.ws(`procurement/${live[0]?.id}`));
    await expect(page.getByRole("button", { name: "Flag dispute" })).toBeEnabled();
    await expectHealthyPage(page);
  });
});

/* ------------------------------------------------------------------------------------------------
 * 2: supplier cost console (platform administrator)
 * ---------------------------------------------------------------------------------------------- */

interface SupplierInvoice {
  id: string;
  provider: string;
  period_start: string;
  period_end: string;
  invoiced_total_micros: number;
  currency: string;
  invoice_reference: string | null;
  notes: string | null;
  origin: string;
  latest_reconciliation: { id: string; status: string } | null;
}
interface Reconciliation {
  id: string;
  status: string;
  modelled_total_micros: number;
  variance_micros: number;
  variance_ratio: number | null;
  note: string | null;
  reconciled_by_user_id: string | null;
  is_authoritative_cost: boolean;
  cost_basis_method: string;
}

const isoDay = (daysAgo: number): string => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

test.describe("Supplier cost console — Record invoice, Reconcile, Accept", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(120_000);
  test.use({ user: "P.superadmin" });

  // A provider no usage record carries: its modelled cost is nothing, so a reconciliation must say INVESTIGATE.
  const provider = `e2e-cost-${runId()}`;
  const closed = { start: isoDay(20), end: isoDay(15) };
  const open = { start: isoDay(1), end: isoDay(0) };
  let admin: ApiSession;

  const invoicesOf = async (name: string): Promise<SupplierInvoice[]> => {
    const listed = await api<{ entries: SupplierInvoice[] }>(admin, "GET", `/admin/cogs/supplier-invoices?provider=${name}`);
    expect(listed.status, listed.text.slice(0, 300)).toBe(200);
    return listed.body.entries;
  };
  const runsOf = async (invoiceId: string): Promise<Reconciliation[]> => {
    const listed = await api<Reconciliation[]>(admin, "GET", `/admin/cogs/supplier-invoices/${invoiceId}/reconciliations`);
    expect(listed.status, listed.text.slice(0, 300)).toBe(200);
    return listed.body;
  };
  const invoiceRow = (page: Page, name: string): Locator => page.getByRole("row").filter({ hasText: name }).first();
  const supplierSection = (page: Page): Locator =>
    page.locator("section").filter({ has: page.getByRole("heading", { name: "Supplier invoices" }) });

  async function openConsole(page: Page): Promise<void> {
    await page.goto("/admin/margins");
    await expect(page.getByRole("heading", { name: "Unit economics", level: 1 })).toBeVisible();
    await expect(supplierSection(page).getByRole("button", { name: "Record invoice" })).toBeVisible();
    await settle(page);
  }

  async function fillInvoice(page: Page, p: { provider: string; start: string; end: string; amount: string; reference?: string; notes?: string; currency?: string }): Promise<Locator> {
    const dialog = page.getByRole("dialog", { name: "Record a supplier invoice" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Provider").fill(p.provider);
    await dialog.getByLabel("Period start").fill(p.start);
    await dialog.getByLabel("Period end").fill(p.end);
    await dialog.getByLabel("Invoiced total").fill(p.amount);
    if (p.currency) await dialog.getByLabel("Currency").fill(p.currency);
    if (p.reference) await dialog.getByLabel(/Invoice reference/).fill(p.reference);
    if (p.notes) await dialog.getByLabel(/Notes/).fill(p.notes);
    return dialog;
  }

  test.beforeAll(async () => {
    admin = await loginAs("P.superadmin");
  });

  test("Record invoice: refuses nonsense, records a closed-period invoice, refuses the same period twice", async ({ page, problems }) => {
    problems.allowHttp(/\/admin\/cogs\/supplier-invoices$/, [409], "the same provider and period twice");
    await openConsole(page);
    const before = await invoicesOf(provider);
    expect(before).toHaveLength(0);

    await supplierSection(page).getByRole("button", { name: "Record invoice" }).click();
    const dialog = await fillInvoice(page, { provider, start: closed.end, end: closed.start, amount: "1234.56" });
    const submit = dialog.getByRole("button", { name: "Record invoice" });
    // The period ends before it starts: said, and not sendable.
    await expect(dialog).toContainText("The period ends before it starts.");
    await expect(submit).toBeDisabled();
    await dialog.getByLabel("Period start").fill(closed.start);
    await dialog.getByLabel("Period end").fill(closed.end);
    await expect(dialog).not.toContainText("The period ends before it starts.");
    // A currency that is not three letters, a document id that is not a UUID.
    await dialog.getByLabel("Currency").fill("US");
    await expect(submit).toBeDisabled();
    await dialog.getByLabel("Currency").fill("usd");
    await dialog.getByLabel(/Stored document ID/).fill("not-a-uuid");
    await expect(dialog).toContainText("Not a valid UUID.");
    await expect(submit).toBeDisabled();
    await dialog.getByLabel(/Stored document ID/).fill("");
    await dialog.getByLabel("Invoiced total").fill("");
    await expect(submit).toBeDisabled();
    // Cancel records nothing.
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect(await invoicesOf(provider)).toHaveLength(0);

    // Now for real.
    await supplierSection(page).getByRole("button", { name: "Record invoice" }).click();
    const filled = await fillInvoice(page, { provider: provider.toUpperCase(), start: closed.start, end: closed.end, amount: "1234.56", reference: `REF-${tag}`, notes: "Recorded by the browser test." });
    await expect(filled.getByRole("button", { name: "Record invoice" })).toBeEnabled();
    await filled.getByRole("button", { name: "Record invoice" }).click();
    await expect(filled).toHaveCount(0);

    // The page: one row, by provider (the server keeps it lower-case), period, reference, amount; not reconciled yet.
    const row = invoiceRow(page, provider);
    await expect(row).toContainText(`${closed.start} → ${closed.end}`);
    await expect(row).toContainText(`REF-${tag}`);
    await expect(row).toContainText("operator-supplied invoice");
    await expect(row).toContainText("$1,234.56");
    await expect(row).toContainText("not reconciled");
    await expect(row.getByRole("button", { name: "Reconcile" })).toBeEnabled();
    await expect(row.getByRole("button", { name: "Accept" })).toHaveCount(0);

    // The API agrees, and so does the page after a reload.
    const stored = await invoicesOf(provider);
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ provider, period_start: closed.start, period_end: closed.end, invoiced_total_micros: 1_234_560_000,
      currency: "USD", invoice_reference: `REF-${tag}`, notes: "Recorded by the browser test.", origin: "OPERATOR_UPLOAD", latest_reconciliation: null });
    await page.reload();
    await expect(invoiceRow(page, provider)).toContainText("$1,234.56");

    // The same provider and period again is refused, in words, and nothing is added.
    await supplierSection(page).getByRole("button", { name: "Record invoice" }).click();
    const again = await fillInvoice(page, { provider, start: closed.start, end: closed.end, amount: "99" });
    await again.getByRole("button", { name: "Record invoice" }).click();
    await expect(again.getByRole("alert")).toBeVisible();
    await expect(again).toBeVisible();
    expect(await invoicesOf(provider)).toHaveLength(1);
    await again.getByRole("button", { name: "Cancel" }).click();
    await expectHealthyPage(page);
  });

  test("Reconcile: a closed period is compared with what was modelled; nothing modelled means INVESTIGATE; each press is one more run", async ({ page }) => {
    const [invoice] = await invoicesOf(provider);
    expect(invoice, "the invoice recorded by the previous test").toBeTruthy();
    await openConsole(page);
    const row = invoiceRow(page, provider);
    await expect(row).toContainText("not reconciled");

    await row.getByRole("button", { name: "Reconcile" }).click();
    await expect(row.getByText("INVESTIGATE", { exact: true })).toBeVisible();
    await expect(row).not.toContainText("not reconciled");
    // Nothing was modelled for this provider: the ratio is "unknown", never 0%.
    await expect(row).toContainText(/ratio (unknown|—|n\/a)/i);
    await expect(row.getByRole("button", { name: "Accept" })).toBeVisible();

    let runs = await runsOf(invoice?.id ?? "");
    expect(runs).toHaveLength(1);
    expect(runs[0]).toMatchObject({ status: "INVESTIGATE", modelled_total_micros: 0, variance_micros: 1_234_560_000, variance_ratio: null,
      reconciled_by_user_id: String(admin.me.id) });
    expect(runs[0]).toMatchObject({ is_authoritative_cost: true, cost_basis_method: "ARCH18_SUPPLIER_COST" });
    await expect(row).toContainText("basis:");
    expect((await invoicesOf(provider))[0]?.latest_reconciliation?.status).toBe("INVESTIGATE");

    // After a reload the row still says so.
    await page.reload();
    await expect(invoiceRow(page, provider).getByText("INVESTIGATE", { exact: true })).toBeVisible();

    // A second press appends a second run (history is never rewritten); the page lists both.
    await invoiceRow(page, provider).getByRole("button", { name: "Reconcile" }).click();
    await expect.poll(async () => (await runsOf(invoice?.id ?? "")).length).toBe(2);
    runs = await runsOf(invoice?.id ?? "");
    expect(new Set(runs.map((r) => r.id)).size).toBe(2);
    const history = invoiceRow(page, provider).locator("xpath=following-sibling::tr[1]").locator("details");
    await history.getByText("Show reconciliation history").click();
    await expect(history.getByText("2 reconciliation runs")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("Accept: a note is required (cancel and an empty note change nothing); an accepted variance is a new row that names what it accepts", async ({ page }) => {
    const [invoice] = await invoicesOf(provider);
    const runsBefore = await runsOf(invoice?.id ?? "");
    await openConsole(page);
    const row = invoiceRow(page, provider);
    const accept = row.getByRole("button", { name: "Accept" });
    await expect(accept).toBeVisible();

    // The browser's own prompt: dismissed, then answered with nothing.
    const asked: string[] = [];
    page.once("dialog", (d: Dialog) => { asked.push(d.message()); void d.dismiss(); });
    await accept.click();
    await expect.poll(() => asked.length).toBe(1);
    expect(asked[0]).toContain("Why is this variance acceptable?");
    page.once("dialog", (d: Dialog) => { asked.push(d.message()); void d.accept("   "); });
    await accept.click();
    await expect.poll(() => asked.length).toBe(2);
    expect(await runsOf(invoice?.id ?? "")).toHaveLength(runsBefore.length);

    const note = `Provider billed a flat fee outside our metering; signed off in test ${tag}.`;
    page.once("dialog", (d: Dialog) => { void d.accept(note); });
    await accept.click();
    await expect(row.getByText("ACCEPTED", { exact: true })).toBeVisible();
    await expect(row).toContainText(note);
    await expect(row.getByRole("button", { name: "Accept" })).toHaveCount(0);

    const runs = await runsOf(invoice?.id ?? "");
    expect(runs).toHaveLength(runsBefore.length + 1);
    const accepted = runs.find((r) => r.status === "ACCEPTED");
    expect(accepted).toMatchObject({ note, variance_micros: 1_234_560_000, reconciled_by_user_id: String(admin.me.id) });
    expect(runs.filter((r) => r.status === "INVESTIGATE")).toHaveLength(runsBefore.length);
    expect(accepted?.id, "the acceptance is a row of its own").not.toBe(runs.find((r) => r.status === "INVESTIGATE")?.id);
    expect((await invoicesOf(provider))[0]?.latest_reconciliation?.status).toBe("ACCEPTED");
    await page.reload();
    await expect(invoiceRow(page, provider).getByText("ACCEPTED", { exact: true })).toBeVisible();
    await expectHealthyPage(page);
  });

  test("Reconcile on a period that is not closed yet is refused in words and adds no run; \"Reconcile anyway\" then forces it", async ({ page, problems }) => {
    const young = `${provider}-y`.slice(0, 32);
    problems.allowHttp(/\/admin\/cogs\/supplier-invoices\/[0-9a-f-]+\/reconcile$/, [409], "the period has not closed yet");
    const created = await api<SupplierInvoice>(admin, "POST", "/admin/cogs/supplier-invoices", {
      provider: young, period_start: open.start, period_end: open.end, invoiced_total_micros: 5_000_000, currency: "USD" });
    expect(created.status, created.text.slice(0, 300)).toBe(201);

    await openConsole(page);
    const row = invoiceRow(page, young);
    await expect(row).toContainText("not reconciled");
    await row.getByRole("button", { name: "Reconcile" }).click();
    const refusal = page.getByRole("alert").filter({ hasText: /not\s+treated as final|T\+\d+ days/ });
    await expect(refusal).toBeVisible();
    await expect(invoiceRow(page, young)).toContainText("not reconciled");
    expect(await runsOf(created.body.id)).toHaveLength(0);

    // The refusal offers the way on, and only after the refusal: nothing is forced by the first press.
    const anyway = refusal.getByRole("button", { name: "Reconcile anyway" });
    await expect(anyway).toBeVisible();
    await anyway.click();
    await expect(invoiceRow(page, young)).not.toContainText("not reconciled");
    await expect(page.getByRole("button", { name: "Reconcile anyway" })).toHaveCount(0);
    await expect(page.getByRole("alert").filter({ hasText: /not\s+treated as final|T\+\d+ days/ })).toHaveCount(0);
    const runs = await runsOf(created.body.id);
    expect(runs).toHaveLength(1);
    expect(runs[0]?.status).toBe("INVESTIGATE");
  });

  test("only the platform administrator: an organization owner is refused every one of these (403 or 404)", async () => {
    const [invoice] = await invoicesOf(provider);
    const owner = await loginAs("C.owner");
    const created = await api(owner, "POST", "/admin/cogs/supplier-invoices", {
      provider: `${provider}-x`.slice(0, 32), period_start: closed.start, period_end: closed.end, invoiced_total_micros: 1, currency: "USD" });
    expect([403, 404], "the platform routes answer 404 to non-operators, so they do not reveal themselves").toContain(created.status);
    const reconciled = await api(owner, "POST", `/admin/cogs/supplier-invoices/${invoice?.id}/reconcile`, {});
    expect([403, 404]).toContain(reconciled.status);
    const listed = await api(owner, "GET", "/admin/cogs/supplier-invoices");
    expect([403, 404]).toContain(listed.status);
    const accepted = await api(owner, "POST", `/admin/cogs/reconciliations/${invoice?.latest_reconciliation?.id}/accept`, { note: "an owner's note" });
    expect([403, 404]).toContain(accepted.status);
    expect(await invoicesOf(`${provider}-x`.slice(0, 32))).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------------------------------------
 * 4: scanned packets
 * ---------------------------------------------------------------------------------------------- */

interface SplitRow {
  id: string;
  work_item_id: string;
  original_filename: string;
  status: string;
  page_count: number;
  segment_count: number;
}
interface SplitDetail {
  split: SplitRow;
  segments: Array<{ ordinal: number; page_start: number; page_end: number; document_type: string | null; child_work_item_id: string | null }>;
  failure_reason: string | null;
}

/** A four-page packet of different documents (invoice, order, receipt, contract), unique to this run. */
function packetPages(label: string): string[][] {
  const vendor = `Packet Supplies ${label} Ltd`;
  return [
    ["INVOICE", `Vendor: ${vendor}`, "Vendor Address: 12 Foundry Road, Leeds LS1 4AB, United Kingdom", "Bill To: Packets Review Ltd",
      `Invoice Number: INV-PK-${label}`, "Invoice Date: 2026-09-15", "Due Date: 2026-10-15", `PO Number: PO-PK-${label}`, "Currency: USD",
      "Line items:", "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00",
      "|2|Steel toe boots|10|60.00|600.00", "Subtotal: 1100.00", "Total Amount Due: 1100.00 USD", "Payment terms: Net 30"],
    ["PURCHASE ORDER", "Buyer: Packets Review Ltd", `Vendor: ${vendor}`, `PO Number: PO-PK-${label}`, "PO Date: 2026-09-01", "Currency: USD",
      "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00", "|2|Steel toe boots|10|60.00|600.00",
      "PO Total: 1100.00 USD"],
    ["GOODS RECEIPT NOTE", "Receiver: Packets Review Ltd warehouse 3", `Vendor: ${vendor}`, `Receipt Number: GR-PK-${label}`,
      `PO Number: PO-PK-${label}`, "Received Date: 2026-09-12", "|#|Description|Qty received", "|1|Industrial safety gloves|98",
      "|2|Steel toe boots|10"],
    ["MASTER SERVICES AGREEMENT", `Agreement Number: MSA-PK-${label}`, `Between Packets Review Ltd (Customer) and ${vendor} (Supplier)`,
      "Effective Date: 2026-01-01. Term: 12 months. Renewal Date: 2026-12-31.",
      "1. Payment. Customer shall pay each undisputed invoice within 30 days of receipt.",
      "2. Reporting. Supplier shall deliver a monthly service report within 10 days",
      "   after the end of each calendar month.", "3. Insurance. Supplier shall maintain liability insurance of at least USD 1,000,000.",
      "4. Termination. Either party may terminate with 60 days written notice before 2026-11-01.",
      "5. Liability cap. Supplier liability is limited to 12 months of fees.",
      "6. Governing law. This agreement is governed by the laws of England and Wales.",
      "7. Confidentiality. Each party shall keep the other party's information confidential."],
  ];
}

test.describe("Scanned packets — Save boundaries, Approve split, Keep as one document", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  let pk: Customer;
  let pkViewer: { email: string; session: ApiSession };
  let pkContributor: { email: string; session: ApiSession };
  // Four packets: the repository's sample (page), one for the Review hub, one for the viewer and for rejecting.
  const names = { page: "scanned-packet-E2E.pdf", hub: `packet-hub-${tag}.pdf`, keep: `packet-keep-${tag}.pdf` };
  const splitIds = {} as Record<"page" | "hub" | "keep", string>;

  const splitsApi = (suffix = ""): string => `/workspaces/${pk.wsId}/packet-splits${suffix}`;
  const splitOf = async (id: string, session: ApiSession = pk.session): Promise<SplitDetail> => {
    const got = await api<SplitDetail>(session, "GET", splitsApi(`/${id}`));
    expect(got.status, got.text.slice(0, 300)).toBe(200);
    return got.body;
  };
  const starts = (detail: SplitDetail): number[] => detail.segments.map((s) => s.page_start);
  const filenames = async (): Promise<string[]> =>
    (await listWorkItems(pk.session, pk.wsId)).map((i) => String(i.original_filename));

  test.beforeAll(async () => {
    test.setTimeout(600_000);
    pk = await newCustomer("pkt", "Packets Review Ltd");
    standIn("subscribe", pk.orgSlug, "--plan", "enterprise", "--seats", "4");
    // The repository's own sample packet (support/sample-docs.ts) goes in as it is.
    const sample = await uploadFile(pk.session, pk.wsId, samplePath("packet"));
    expect(sample.status, sample.text.slice(0, 300)).toBe(201);
    for (const [key, label] of [["hub", `H${tag}`], ["keep", `K${tag}`]] as const) {
      const file = path.join(dir, names[key]);
      fs.writeFileSync(file, buildPdf(packetPages(label)));
      const sent = await uploadFile(pk.session, pk.wsId, file);
      expect(sent.status, sent.text.slice(0, 300)).toBe(201);
    }
    await allProcessed(pk, 3, 420_000);
    // The worker proposes a split of each packet; wait for all three plans.
    await expect
      .poll(async () => {
        const listed = await api<{ items: SplitRow[] }>(pk.session, "GET", splitsApi());
        const items = listed.body.items ?? [];
        for (const key of ["page", "hub", "keep"] as const) {
          const mine = items.find((i) => i.original_filename === names[key]);
          if (!mine) return `${key}: no plan yet`;
          if (mine.status !== "PROPOSED") return `${key}: ${mine.status}`;
          splitIds[key] = mine.id;
        }
        return "ready";
      }, { timeout: 240_000, intervals: [2_000, 3_000] })
      .toBe("ready");
    pkViewer = await addMember(pk, "pkt-viewer", "MEMBER", "VIEWER");
    pkContributor = await addMember(pk, "pkt-contrib", "MEMBER", "CONTRIBUTOR");
  });

  test("the worker proposed a plan of at least two documents for each packet", async () => {
    for (const key of ["page", "hub", "keep"] as const) {
      const detail = await splitOf(splitIds[key]);
      expect(detail.split.page_count, key).toBe(4);
      expect(detail.segments.length, `${key}: documents proposed`).toBeGreaterThanOrEqual(2);
      expect(detail.segments[0]?.page_start).toBe(1);
    }
  });

  test("Save boundaries then Approve split on the split page: the corrected plan is kept, then cut into documents; the original stays", async ({ page }) => {
    const id = splitIds.page;
    const planned = await splitOf(id);
    const initial = starts(planned).slice(1);
    expect(initial.length).toBeGreaterThanOrEqual(1);
    // Correct the plan by one boundary: add one where the model saw none (or remove one if it saw all three).
    const addable = [2, 3, 4].filter((p) => !initial.includes(p));
    const toggled = addable.length > 0 ? (addable[0] as number) : (initial[initial.length - 1] as number);
    const kept = (addable.length > 0 ? [...initial, toggled] : initial.filter((p) => p !== toggled)).sort((a, b) => a - b);
    const verb = addable.length > 0 ? "Add" : "Remove";
    const flipped = addable.length > 0 ? "Remove" : "Add";

    await signInAs(page, pk.email);
    await page.goto(pk.ws("packet-splits"));
    await expect(page.getByRole("heading", { name: "Scanned packets", level: 1 })).toBeVisible();
    const listRow = page.getByRole("row").filter({ hasText: names.page });
    await expect(listRow).toContainText("PROPOSED");
    await listRow.getByRole("link", { name: names.page }).click();
    await expect(page).toHaveURL(new RegExp(`/packet-splits/${id}$`));
    await expect(page.getByRole("heading", { name: names.page, level: 1 })).toBeVisible();
    await expect(page.getByText("PROPOSED", { exact: true })).toBeVisible();
    await expect(page.getByText(`4 pages → ${initial.length + 1} documents`)).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: /^Pages \d+–\d+/ })).toHaveCount(initial.length + 1);

    // Nothing is edited yet: there is nothing to save.
    await expect(page.getByRole("button", { name: "Save boundaries" })).toBeDisabled();
    await page.getByRole("button", { name: `${verb} a document boundary before page ${toggled}` }).click();
    await expect(page.getByText(`4 pages → ${kept.length + 1} documents`)).toBeVisible();
    await expect(page.getByRole("button", { name: `${flipped} a document boundary before page ${toggled}` })).toHaveAttribute("aria-pressed", String(addable.length > 0));
    await expect(page.getByRole("button", { name: "Save boundaries" })).toBeEnabled();
    // Nothing has been written until Save.
    expect(starts(await splitOf(id)).slice(1)).toEqual(initial);

    await page.getByRole("button", { name: "Save boundaries" }).click();
    await expect.poll(async () => starts(await splitOf(id)).slice(1)).toEqual(kept);
    expect((await splitOf(id)).split.status).toBe("PROPOSED");
    await expect(page.getByRole("button", { name: "Save boundaries" })).toBeDisabled();
    await page.reload();
    await expect(page.getByText(`4 pages → ${kept.length + 1} documents`)).toBeVisible();
    await expect(page.getByText("PROPOSED", { exact: true })).toBeVisible();

    // Approve split: the plan is decided now; the worker cuts the documents.
    await page.getByRole("button", { name: "Approve split" }).click();
    await expect(page.getByText(/^(APPROVED|APPLYING|APPLIED)$/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve split" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Keep as one document" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save boundaries" })).toBeDisabled();

    await expect.poll(async () => (await splitOf(id)).split.status, { timeout: 120_000, intervals: [1_000, 2_000] }).toBe("APPLIED");
    const applied = await splitOf(id);
    expect(applied.segments).toHaveLength(kept.length + 1);
    expect(applied.segments.every((s) => Boolean(s.child_work_item_id))).toBe(true);
    expect(starts(applied).slice(1)).toEqual(kept);
    // The documents exist in the workspace, named for their pages; the original upload is kept.
    await expect
      .poll(async () => (await filenames()).filter((n) => /^scanned-packet-E2E - part \d/.test(n)).length, { timeout: 60_000 })
      .toBe(kept.length + 1);
    expect(await filenames()).toContain(names.page);

    await page.reload();
    await expect(page.getByText("APPLIED", { exact: true })).toBeVisible();
    await expect(page.getByText("· created")).toHaveCount(kept.length + 1);
    await expect(page.getByRole("button", { name: "Approve split" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save boundaries" })).toBeDisabled();
    // The list says so too.
    await page.goto(pk.ws("packet-splits"));
    await expect(page.getByRole("row").filter({ hasText: names.page })).toContainText("APPLIED");

    // Approving again (a second tab) is refused and changes nothing.
    const again = await api(pk.session, "POST", splitsApi(`/${id}/approve`), {});
    expect(again.status).toBe(422);
    expect((await splitOf(id)).segments).toHaveLength(kept.length + 1);
    await expectHealthyPage(page);
  });

  test("Approve split in the Review hub does the same: the item leaves the queue and the documents are cut", async ({ page }) => {
    const id = splitIds.hub;
    const planned = await splitOf(id);
    await signInAs(page, pk.email);
    await page.goto(`${pk.ws("verification")}?view=SPLIT`);
    await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Packet splits", selected: true })).toBeVisible();
    const list = page.getByRole("list", { name: "Review items" });
    await expect(list).toBeVisible({ timeout: 30_000 });
    const row = list.getByRole("listitem").filter({ hasText: names.hub });
    await expect(row).toHaveCount(1);
    await row.getByRole("button", { name: "Resolve", exact: true }).click();
    await expect(row).toContainText("Approving creates one document per part");
    await row.getByRole("button", { name: "Approve split", exact: true }).click();
    await expect(list.getByRole("listitem").filter({ hasText: names.hub })).toHaveCount(0);

    await expect.poll(async () => (await splitOf(id)).split.status, { timeout: 120_000, intervals: [1_000, 2_000] }).toBe("APPLIED");
    const applied = await splitOf(id);
    expect(applied.segments).toHaveLength(planned.segments.length);
    expect(applied.segments.every((s) => Boolean(s.child_work_item_id))).toBe(true);
    await expect
      .poll(async () => (await filenames()).filter((n) => n.startsWith(`packet-hub-${tag} - part`)).length, { timeout: 60_000 })
      .toBe(planned.segments.length);
    const open = await api<{ items: Array<{ item_id: string }> }>(pk.session, "GET", `/workspaces/${pk.wsId}/review?kind=SPLIT&status=OPEN&page_size=100`);
    expect(open.body.items.map((i) => i.item_id)).not.toContain(id);

    // History keeps it; the split page shows it applied.
    await page.getByRole("tab", { name: "History" }).click();
    await expect(page.getByRole("list", { name: "Review items" }).getByRole("listitem").filter({ hasText: names.hub })).toHaveCount(1, { timeout: 30_000 });
    await page.goto(pk.ws(`packet-splits/${id}`));
    await expect(page.getByText("APPLIED", { exact: true })).toBeVisible();
    await expectHealthyPage(page);
  });

  test("a viewer reads the plan but is offered nothing, and the server refuses a viewer's approve, reject and correction (403)", async ({ page }) => {
    const id = splitIds.keep;
    const before = starts(await splitOf(id));
    for (const [method, suffix, body] of [["POST", "approve", {}], ["POST", "reject", undefined], ["PUT", "boundaries", { boundaries: [2] }]] as const) {
      const refused = await api(pkViewer.session, method, splitsApi(`/${id}/${suffix}`), body);
      expect(refused.status, `${suffix}: ${refused.text.slice(0, 200)}`).toBe(403);
    }
    expect(await splitOf(id, pkViewer.session)).toBeTruthy();
    expect((await splitOf(id)).split.status).toBe("PROPOSED");
    expect(starts(await splitOf(id))).toEqual(before);

    await signInAs(page, pkViewer.email);
    await page.goto(pk.ws(`packet-splits/${id}`));
    await expect(page.getByRole("heading", { name: names.keep, level: 1 })).toBeVisible();
    for (const name of ["Save boundaries", "Approve split", "Keep as one document"]) {
      await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
    }
    await expect(page.getByRole("button", { name: /a document boundary before page 2/ })).toBeDisabled();
    await expect(page.getByText("Contributors and admins correct, approve or reject a split.")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("Keep as one document (a contributor): the plan is rejected, no document is cut, the original stays whole", async ({ page }) => {
    const id = splitIds.keep;
    const itemsBefore = (await filenames()).length;
    await signInAs(page, pkContributor.email);
    await page.goto(pk.ws(`packet-splits/${id}`));
    await expect(page.getByRole("heading", { name: names.keep, level: 1 })).toBeVisible();
    await expect(page.getByText("PROPOSED", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Keep as one document" }).click();
    await expect(page.getByText("REJECTED", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve split" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Keep as one document" })).toBeDisabled();

    const stored = await splitOf(id);
    expect(stored.split.status).toBe("REJECTED");
    expect(stored.segments.every((s) => s.child_work_item_id === null)).toBe(true);
    expect((await filenames()).length).toBe(itemsBefore);
    await page.reload();
    await expect(page.getByText("REJECTED", { exact: true })).toBeVisible();
    // A rejected plan cannot be approved afterwards, from anywhere.
    const approve = await api(pk.session, "POST", splitsApi(`/${id}/approve`), {});
    expect(approve.status).toBe(422);
    expect((await splitOf(id)).split.status).toBe("REJECTED");
    await expectHealthyPage(page);
  });
});
