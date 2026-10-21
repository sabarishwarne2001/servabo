/**
 * ERP POSTING (Workspace → ERP posting): the buttons that change the books.
 *
 * On a tenant of its own (Business plan) with a real three-way match: a purchase order, a goods
 * receipt and an invoice are uploaded, read by the worker and matched, and the case is approved.
 * No ERP is reachable from a test run, so the spec drives what needs none:
 *
 *   - a DOWNLOAD target (CSV): the rendered file is kept in Servabo and a person confirms the
 *     import. "Post N" plans the postings (exactly once), "Do not post" cancels one, "Imported"
 *     marks one posted.
 *   - a failed post, made the honest way: an administrator saves a mapping that REQUIRES a field
 *     the invoice does not carry (the vendor's tax id), so the file cannot be built and the
 *     posting is Failed. "Retry" with the mapping still wrong fails again; after the mapping is
 *     put right, "Retry" builds the file.
 *   - an HTTP target (QuickBooks preset) pointing at a host that does not exist: "Set credential"
 *     stores the token (only its fingerprint comes back) and "Test connection" reports, truthfully,
 *     that it is not connected. The DOWNLOAD target's test says it has nothing to connect to.
 *   - the mapping editor: "Save as new version" keeps the old one, "Restore default" brings back
 *     the shipped mapping as a new version; bad JSON and a bad mapping are refused.
 *   - a contributor and a viewer see no way to do any of it, and the server refuses them (403).
 *
 * Each result is read on the page and again through the API (or after a reload).
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api, listWorkItems, uploadFile, type ApiSession } from "../support/api";
import { runId } from "../support/env";
import { buildPdf } from "../support/sample-docs";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";

interface TargetRow {
  id: string;
  name: string;
  credential_set: boolean;
  credential_fingerprint: string | null;
  postings: number;
}
interface PostingRow {
  id: string;
  object_kind: string;
  state: string;
  target_id: string;
  document_number: string | null;
  external_id: string | null;
  attempts: number;
  mapping_version: number | null;
  rendered_filename: string | null;
  last_error: string | null;
}
interface Attempt { seq: number; kind: string; outcome: string; message: string | null }
interface PostingDetail {
  posting: PostingRow;
  attempts: Attempt[];
  review_note: string | null;
}
interface PostResult { object_kind: string; posting_id: string | null; created: boolean; state: string | null; error: string | null }
interface MappingRow { id: string; version: number; status: string; spec: Spec; note: string | null }
interface Spec { header: Array<{ to: string; required?: boolean }> }
interface Versions { active: MappingRow | null; versions: MappingRow[]; default_spec: Spec }
interface TestResult { ok: boolean; kind: string; message: string }

const tag = runId().toUpperCase();
const INVOICE_NUMBER = `INV-${tag}`;
const PO_NUMBER = `PO-${tag}`;
const INVOICE_FILE = `invoice-${INVOICE_NUMBER}.pdf`;
const VENDOR = `Northwind Fasteners ${tag} Ltd`;
const BUYER = "ERP Posting Ltd";
// Session J: these questions are asked in Servabo's own dialog (never a browser confirm).
const CONFIRM_TEXT = "This posting will not be sent to the target.";
const RESTORE_TEXT = "The active mapping is replaced by the default for this format, as a new version.";

let customer: Customer;
let contributor: { email: string; session: ApiSession };
let viewer: { email: string; session: ApiSession };
let caseId: string;
let sequence = 0;

const erp = (suffix = ""): string => `/workspaces/${customer.wsId}/erp${suffix}`;

/** A target of this test's own (each test works on its own, so none depends on another). */
async function csvTarget(label: string): Promise<TargetRow> {
  sequence += 1;
  const created = await api<{ target: TargetRow }>(customer.session, "POST", erp("/targets"), {
    name: `${label} ${tag}-${sequence}`,
    format: "CSV",
    transport: "DOWNLOAD",
  });
  expect(created.status, created.text.slice(0, 300)).toBe(201);
  return created.body.target;
}

/** A QuickBooks-preset HTTP target on a host that does not exist (".test" is reserved for that). */
async function quickBooksTarget(label: string): Promise<TargetRow> {
  sequence += 1;
  const created = await api<{ target: TargetRow }>(customer.session, "POST", erp("/targets"), {
    name: `${label} ${tag}-${sequence}`,
    format: "JSON",
    transport: "HTTP",
    preset: "QUICKBOOKS_ONLINE",
    auth_mode: "BEARER",
    config: { http: { base_url: "https://qbo.erp-e2e.test" }, qbo: { realm_id: "9130" } },
  });
  expect(created.status, created.text.slice(0, 300)).toBe(201);
  return created.body.target;
}

async function postVia(session: ApiSession, targetId: string, kinds: string[]): Promise<PostResult[]> {
  const posted = await api<{ results: PostResult[] }>(session, "POST", erp("/postings"), {
    target_id: targetId,
    source_kind: "PROCUREMENT_CASE",
    source_id: caseId,
    object_kinds: kinds,
  });
  expect(posted.status, posted.text.slice(0, 300)).toBe(201);
  return posted.body.results;
}

async function postingsOf(targetId: string): Promise<PostingRow[]> {
  const listed = await api<{ items: PostingRow[] }>(customer.session, "GET", erp(`/postings?target_id=${targetId}`));
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
}

async function detailOf(postingId: string): Promise<PostingDetail> {
  const detail = await api<PostingDetail>(customer.session, "GET", erp(`/postings/${postingId}`));
  expect(detail.status, detail.text.slice(0, 300)).toBe(200);
  return detail.body;
}

async function mappingsOf(targetId: string, kind = "VENDOR_BILL"): Promise<Versions> {
  const versions = await api<Versions>(customer.session, "GET", erp(`/targets/${targetId}/mappings/${kind}`));
  expect(versions.status, versions.text.slice(0, 300)).toBe(200);
  return versions.body;
}

async function targetRow(targetId: string): Promise<TargetRow> {
  const listed = await api<{ items: TargetRow[] }>(customer.session, "GET", erp("/targets"));
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  const row = listed.body.items.find((t) => t.id === targetId);
  expect(row, `target ${targetId} is listed`).toBeTruthy();
  return row as TargetRow;
}

/** A mapping that asks for a field this invoice does not carry: the file cannot be built. */
function requiringTaxId(spec: Spec): Spec {
  const copy = JSON.parse(JSON.stringify(spec)) as Spec;
  const field = copy.header.find((f) => f.to === "VendorTaxId");
  expect(field, "the default mapping has a VendorTaxId field").toBeTruthy();
  if (field) field.required = true;
  return copy;
}

async function saveMappingVia(targetId: string, spec: Spec, note: string): Promise<void> {
  const saved = await api(customer.session, "PUT", erp(`/targets/${targetId}/mappings/VENDOR_BILL`), { spec, note });
  expect(saved.status, saved.text.slice(0, 300)).toBe(200);
}

/**
 * Answer the in-app question the last click opened: confirm it with the named button or cancel it.
 * Returns the dialog's text, so the caller still asserts what was asked. (The browser fixture fails
 * any test that opens a native dialog, so this is the only way a question can be asked.)
 */
async function answerDialog(page: Page, accept: false | string): Promise<string> {
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  const asked = await dialog.innerText();
  await dialog.getByRole("button", { name: accept === false ? "Cancel" : accept, exact: true }).click();
  await expect(dialog).toHaveCount(0);
  return asked;
}

const stateBadge = (page: Page, label: string) => page.getByText(label, { exact: true }).first();

test.describe("ERP posting — a tenant of its own, a real approved match", () => {
  test.setTimeout(150_000);

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    customer = await newCustomer("erp", BUYER);
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "4");
    // The tolerance is set BEFORE the documents arrive: publishing a policy re-matches the cases.
    const policy = await api(customer.session, "POST", `/workspaces/${customer.wsId}/procurement/policies`, { price_tolerance_bps: 500 });
    expect(policy.status, policy.text.slice(0, 200)).toBeLessThan(300);

    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "servabo-e2e-erp-"));
    const documents: Array<[string, string[]]> = [
      [`purchase-order-${PO_NUMBER}.pdf`, [
        "PURCHASE ORDER", `Buyer: ${BUYER}`, `Vendor: ${VENDOR}`, `PO Number: ${PO_NUMBER}`, "PO Date: 2026-09-01",
        "Currency: USD", "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00",
        "|2|Steel toe boots|10|60.00|600.00", "PO Total: 1100.00 USD"]],
      [`goods-receipt-GR-${tag}.pdf`, [
        "GOODS RECEIPT NOTE", `Receiver: ${BUYER} warehouse 3`, `Vendor: ${VENDOR}`, `Receipt Number: GR-${tag}`,
        `PO Number: ${PO_NUMBER}`, "Received Date: 2026-09-12", "|#|Description|Qty received",
        "|1|Industrial safety gloves|100", "|2|Steel toe boots|10"]],
      [INVOICE_FILE, [
        "INVOICE", `Vendor: ${VENDOR}`, "Vendor Address: 12 Foundry Road, Leeds LS1 4AB, United Kingdom",
        "Vendor Bank Account: GB29 NWBK 6016 1331 9268 19", `Bill To: ${BUYER}`, `Invoice Number: ${INVOICE_NUMBER}`,
        "Invoice Date: 2026-09-15", "Due Date: 2026-10-15", `PO Number: ${PO_NUMBER}`, "Currency: USD", "Line items:",
        "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00",
        "|2|Steel toe boots|10|60.00|600.00", "Subtotal: 1100.00", "Tax (VAT 13.64%): 150.00",
        "Total Amount Due: 1250.00 USD", "Payment terms: Net 30"]],
    ];
    for (const [name, lines] of documents) {
      const file = path.join(dir, name);
      fs.writeFileSync(file, buildPdf([lines]));
      const upload = await uploadFile(customer.session, customer.wsId, file);
      expect(upload.status, upload.text.slice(0, 300)).toBe(201);
    }
    await expect
      .poll(async () => {
        const items = await listWorkItems(customer.session, customer.wsId);
        return items.length === documents.length && items.every((i) => /COMPLETED|NEEDS_REVIEW/.test(String(i.status)));
      }, { timeout: 240_000, intervals: [2_000, 3_000] })
      .toBe(true);

    let found: Array<{ id: string }> = [];
    await expect
      .poll(async () => {
        const listed = await api<Array<{ id: string; status: string; invoice_number?: string }>>(
          customer.session, "GET", `/workspaces/${customer.wsId}/procurement/cases`);
        found = (Array.isArray(listed.body) ? listed.body : []).filter(
          (c) => c.status !== "SUPERSEDED" && c.invoice_number === INVOICE_NUMBER);
        return found.length;
      }, { timeout: 120_000, intervals: [1_000, 2_000] })
      .toBe(1);
    caseId = found[0]?.id ?? "";
    const approved = await api<{ status: string }>(customer.session, "POST", `/workspaces/${customer.wsId}/procurement/cases/${caseId}/approve`, {});
    expect(approved.status, approved.text.slice(0, 300)).toBe(200);
    expect(approved.body.status).toBe("APPROVED");

    contributor = await addMember(customer, "erp-contrib", "MEMBER", "CONTRIBUTOR");
    viewer = await addMember(customer, "erp-viewer", "MEMBER", "VIEWER");
  });

  test("Post N plans the checked objects once, however often it is pressed", async ({ page }) => {
    const target = await csvTarget("Post books");
    await signInAs(page, customer.email);
    await page.goto(customer.ws("erp"));
    await page.getByRole("tab", { name: "Ready to post" }).click();

    const card = page.getByRole("article").filter({ hasText: INVOICE_FILE });
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.getByLabel("Target").selectOption({ label: target.name });
    // Nothing is checked yet, so there is nothing to post.
    await expect(card.getByRole("button", { name: /^Post( \d+)?$/ })).toBeDisabled();
    await card.getByLabel("Post Vendor bill").check();
    await card.getByLabel("Post Purchase order").check();
    const post = card.getByRole("button", { name: "Post 2" });
    await expect(post).toBeEnabled();
    await post.click();

    // The page says what it planned, and a CSV import waits for a person to confirm it.
    const result = card.getByRole("list");
    await expect(result.getByRole("listitem")).toHaveCount(2);
    await expect(result).toContainText("Vendor bill: planned Awaiting acknowledgement");
    await expect(result).toContainText("Purchase order: planned Awaiting acknowledgement");

    // The ledger really holds both, each rendered, none sent anywhere.
    const rows = await postingsOf(target.id);
    expect(rows.map((r) => r.object_kind).sort()).toEqual(["PURCHASE_ORDER", "VENDOR_BILL"]);
    expect(rows.every((r) => r.state === "DELIVERED" && r.rendered_filename?.endsWith(".csv"))).toBe(true);
    const bill = rows.find((r) => r.object_kind === "VENDOR_BILL");
    expect(bill?.document_number).toBe(INVOICE_NUMBER);

    // Pressing it again (a double click, a second tab) finds the same two postings.
    await post.click();
    await expect(result).toContainText("Vendor bill: already in the ledger");
    await expect(result).toContainText("Purchase order: already in the ledger");
    expect((await postingsOf(target.id)).map((r) => r.id).sort()).toEqual(rows.map((r) => r.id).sort());
    const again = await postVia(customer.session, target.id, ["VENDOR_BILL", "PURCHASE_ORDER"]);
    expect(again.map((r) => r.created)).toEqual([false, false]);

    // After a reload the objects are in the ledger: not postable again, and linked to their posting.
    await page.reload();
    await page.getByRole("tab", { name: "Ready to post" }).click();
    const reloaded = page.getByRole("article").filter({ hasText: INVOICE_FILE });
    await reloaded.getByLabel("Target").selectOption({ label: target.name });
    await expect(reloaded.getByLabel("Post Vendor bill")).toBeDisabled();
    await expect(reloaded.getByLabel("Post Purchase order")).toBeDisabled();
    await expect(reloaded.getByRole("link", { name: "Awaiting acknowledgement" })).toHaveCount(2);

    // The link leads to the posting, which shows the figures and the file that was built.
    await reloaded.getByRole("link", { name: "Awaiting acknowledgement" }).first().click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Vendor bill|Purchase order/);
    await expect(page.getByLabel("Rendered file")).toContainText(/INV-|PO-/);
    await expectHealthyPage(page);
  });

  test("Retry sends a failed posting through again — it fails honestly until the mapping is right", async ({ page }) => {
    const target = await csvTarget("Retry books");
    const original = await mappingsOf(target.id);
    await saveMappingVia(target.id, requiringTaxId(original.default_spec), "Require the vendor tax id");
    const [planned] = await postVia(customer.session, target.id, ["VENDOR_BILL"]);
    expect(planned?.created).toBe(true);
    expect(planned?.state).toBe("FAILED");
    const postingId = planned?.posting_id ?? "";
    expect((await detailOf(postingId)).attempts.map((a) => a.kind)).toEqual(["RENDER"]);

    await signInAs(page, customer.email);
    await page.goto(customer.ws(`erp/targets/${target.id}`));
    await page.getByRole("link", { name: "Vendor bill", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(`Vendor bill ${INVOICE_NUMBER}`);
    await expect(stateBadge(page, "Failed")).toBeVisible();
    await expect(page.getByText(/VendorTaxId: required/).first()).toBeVisible();
    const decide = page.getByRole("region", { name: "Decide" });
    await expect(decide.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(decide.getByRole("button", { name: "The ERP has it" })).toBeVisible();
    await expect(decide.getByRole("button", { name: "Do not post" })).toBeVisible();
    const attempts = page.getByRole("region", { name: "Attempts" });
    await expect(attempts.getByRole("listitem")).toHaveCount(1);

    // 1. Retry with the mapping still wrong: the file still cannot be built, and the page says so.
    await decide.getByLabel("Note").fill("Looked at it, trying again");
    await decide.getByRole("button", { name: "Retry" }).click();
    await expect(attempts.getByRole("listitem")).toHaveCount(3);
    await expect(attempts).toContainText("RETRY by a person: Looked at it, trying again");
    await expect(stateBadge(page, "Failed")).toBeVisible();
    await expect(page.getByText(/Reviewer's note: Looked at it, trying again/)).toBeVisible();
    const second = await detailOf(postingId);
    expect(second.posting.state).toBe("FAILED");
    expect(second.attempts.map((a) => `${a.kind}:${a.outcome}`)).toEqual(["RENDER:PERMANENT", "REVIEW:OK", "RENDER:PERMANENT"]);
    expect(second.review_note).toBe("Looked at it, trying again");

    // 2. The administrator puts the mapping right; Retry builds the file.
    await saveMappingVia(target.id, original.default_spec, "Back to the default");
    await decide.getByLabel("Note").fill("Mapping fixed");
    await decide.getByRole("button", { name: "Retry" }).click();
    await expect(stateBadge(page, "Awaiting acknowledgement")).toBeVisible();
    await expect(page.getByLabel("Rendered file")).toContainText(INVOICE_NUMBER);
    await expect(page.getByLabel("Rendered file")).toContainText(VENDOR);
    await expect(page.getByText("Reviewer's note: Mapping fixed")).toBeVisible();
    await expect(attempts).toContainText("rendered again with mapping v3");
    const fixed = await detailOf(postingId);
    expect(fixed.posting.state).toBe("DELIVERED");
    expect(fixed.posting.mapping_version).toBe(3);
    expect(fixed.attempts.map((a) => `${a.kind}:${a.outcome}`)).toEqual([
      "RENDER:PERMANENT", "REVIEW:OK", "RENDER:PERMANENT", "REVIEW:OK", "RENDER:OK", "SEND:OK",
    ]);
    // The file the page shows is the file the server keeps.
    const file = await api<string>(customer.session, "GET", erp(`/postings/${postingId}/file`));
    expect(file.status).toBe(200);
    expect(file.text).toContain(INVOICE_NUMBER);

    // The import is confirmed with the ERP's own reference: the posting is Posted, for good.
    await page.reload();
    await expect(stateBadge(page, "Awaiting acknowledgement")).toBeVisible();
    await page.getByLabel("ERP reference (when it has it)").fill(`BILL-${tag}`);
    await page.getByRole("button", { name: "Imported" }).click();
    await expect(stateBadge(page, "Posted")).toBeVisible();
    await expect(page.getByRole("region", { name: "Summary" })).toContainText(`BILL-${tag}`);
    await expect(page.getByRole("region", { name: "Decide" })).toHaveCount(0);
    const done = await detailOf(postingId);
    expect(done.posting.state).toBe("DONE");
    expect(done.posting.external_id).toBe(`BILL-${tag}`);
    await expectHealthyPage(page);
  });

  test("a posted posting can be neither retried nor cancelled", async () => {
    const target = await csvTarget("Final books");
    const [planned] = await postVia(customer.session, target.id, ["PURCHASE_ORDER"]);
    const postingId = planned?.posting_id ?? "";
    const accepted = await api(customer.session, "POST", erp(`/postings/${postingId}/acknowledge`), { accepted: true, reference: `PO-${tag}-X` });
    expect(accepted.status, accepted.text.slice(0, 200)).toBe(200);
    expect((await detailOf(postingId)).posting.state).toBe("DONE");
    for (const verb of ["retry", "cancel"]) {
      const refused = await api(customer.session, "POST", erp(`/postings/${postingId}/${verb}`), {});
      expect(refused.status, `${verb} of a posted posting: ${refused.text.slice(0, 200)}`).toBe(409);
    }
    expect((await detailOf(postingId)).posting.state).toBe("DONE");
  });

  test("Do not post cancels a posting after a confirmation, and it stays cancelled", async ({ page }) => {
    const target = await csvTarget("Cancel books");
    const [planned] = await postVia(customer.session, target.id, ["PURCHASE_ORDER"]);
    expect(planned?.state).toBe("DELIVERED");
    const postingId = planned?.posting_id ?? "";

    await signInAs(page, customer.email);
    await page.goto(customer.ws(`erp/postings/${postingId}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(`Purchase order ${PO_NUMBER}`);
    await expect(stateBadge(page, "Awaiting acknowledgement")).toBeVisible();
    const decide = page.getByRole("region", { name: "Decide" });
    // A delivered posting can only be cancelled (or confirmed), not retried.
    await expect(decide.getByRole("button", { name: "Retry" })).toHaveCount(0);

    // Dismissing the confirmation changes nothing.
    await decide.getByLabel("Note").fill("Entered by hand instead");
    await decide.getByRole("button", { name: "Do not post" }).click();
    expect(await answerDialog(page, false)).toContain(CONFIRM_TEXT);
    await expect(stateBadge(page, "Awaiting acknowledgement")).toBeVisible();
    expect((await detailOf(postingId)).posting.state).toBe("DELIVERED");

    // Accepting it cancels the posting.
    await decide.getByRole("button", { name: "Do not post" }).click();
    expect(await answerDialog(page, "Do not send")).toContain(CONFIRM_TEXT);
    await expect(stateBadge(page, "Cancelled")).toBeVisible();
    await expect(page.getByRole("region", { name: "Decide" })).toHaveCount(0);
    await expect(page.getByText("Reviewer's note: Entered by hand instead")).toBeVisible();
    const cancelled = await detailOf(postingId);
    expect(cancelled.posting.state).toBe("CANCELLED");
    expect(cancelled.attempts.at(-1)).toMatchObject({ kind: "REVIEW", outcome: "OK" });
    expect(cancelled.attempts.at(-1)?.message).toContain("CANCEL by a person");

    await page.reload();
    await expect(stateBadge(page, "Cancelled")).toBeVisible();
    // It is still in the ledger, so it cannot be planned again; the list shows it cancelled.
    const again = await postVia(customer.session, target.id, ["PURCHASE_ORDER"]);
    expect(again[0]).toMatchObject({ created: false, state: "CANCELLED", posting_id: postingId });
    await page.goto(customer.ws(`erp/targets/${target.id}`));
    const row = page.getByRole("row").filter({ hasText: PO_NUMBER });
    await expect(row).toContainText("Cancelled");
    await expectHealthyPage(page);
  });

  test("Save as new version keeps the old mapping; Restore default brings the shipped one back", async ({ page, problems }) => {
    problems.allowHttp(/\/erp\/targets\/[^/]+\/mappings\/VENDOR_BILL$/, [422], "a mapping the server cannot accept is refused");
    const target = await csvTarget("Mapping books");
    const first = await mappingsOf(target.id);
    expect(first.active?.version).toBe(1);

    await signInAs(page, customer.email);
    await page.goto(customer.ws(`erp/targets/${target.id}`));
    const editor = page.getByLabel("Mapping for VENDOR_BILL");
    await expect(page.getByText(/Active: version 1/)).toBeVisible();
    const shipped = JSON.parse(await editor.inputValue()) as Spec;
    expect(shipped).toEqual(first.default_spec);

    // Text that is not JSON is refused on the page, before anything is sent.
    await editor.fill("{ this is not json");
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText(/Not valid JSON/)).toBeVisible();
    // JSON that is not a mapping is refused by the server, which says why.
    await editor.fill(JSON.stringify({ language: "fp-map/1", header: [] }));
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText(/must be 'VENDOR_BILL'|maps nothing/)).toBeVisible();
    expect((await mappingsOf(target.id)).versions).toHaveLength(1);

    // A good change becomes version 2, with its note; version 1 is kept, retired.
    const changed = requiringTaxId(shipped);
    await editor.fill(JSON.stringify(changed, null, 2));
    await page.getByLabel("Note for this version").fill("Require the vendor tax id");
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText(/Active: version 2/)).toBeVisible();
    await expect(page.getByText(/“Require the vendor tax id”/)).toBeVisible();
    await expect(page.getByText("Earlier versions (1)")).toBeVisible();
    const second = await mappingsOf(target.id);
    expect(second.active).toMatchObject({ version: 2, note: "Require the vendor tax id" });
    expect(second.active?.spec).toEqual(changed);
    expect(second.versions.map((v) => `${v.version}:${v.status}`)).toEqual(["2:ACTIVE", "1:RETIRED"]);
    await page.reload();
    await expect(page.getByText(/Active: version 2/)).toBeVisible();
    expect(JSON.parse(await page.getByLabel("Mapping for VENDOR_BILL").inputValue())).toEqual(changed);

    // Restore default asks first; "no" changes nothing.
    await page.getByRole("button", { name: "Restore default" }).click();
    expect(await answerDialog(page, false)).toContain(RESTORE_TEXT);
    await expect(page.getByText(/Active: version 2/)).toBeVisible();
    expect((await mappingsOf(target.id)).versions).toHaveLength(2);

    // "Yes" makes the shipped mapping version 3 (nothing is overwritten) and shows it in the editor.
    await page.getByRole("button", { name: "Restore default" }).click();
    expect(await answerDialog(page, "Restore default")).toContain(RESTORE_TEXT);
    await expect(page.getByText(/Active: version 3/)).toBeVisible();
    await expect(page.getByText("Earlier versions (2)")).toBeVisible();
    expect(JSON.parse(await page.getByLabel("Mapping for VENDOR_BILL").inputValue())).toEqual(first.default_spec);
    const third = await mappingsOf(target.id);
    expect(third.active?.version).toBe(3);
    expect(third.active?.spec).toEqual(first.default_spec);
    expect(third.versions.map((v) => `${v.version}:${v.status}`)).toEqual(["3:ACTIVE", "2:RETIRED", "1:RETIRED"]);
    // The mapping with the required tax id is still in the history, loadable into the editor.
    await page.getByText("Earlier versions (2)").click();
    await page.getByRole("button", { name: "Load into the editor" }).first().click();
    expect(JSON.parse(await page.getByLabel("Mapping for VENDOR_BILL").inputValue())).toEqual(changed);
    await expectHealthyPage(page);
  });

  test("Set credential stores a token (only its fingerprint comes back) and Test connection reports the truth", async ({ page, problems }) => {
    problems.allowHttp(/\/erp\/targets\/[^/]+\/credential$/, [422], "an empty credential is refused");
    const qbo = await quickBooksTarget("QuickBooks sandbox");
    const csv = await csvTarget("Connection books");
    const secret = `e2e-token-${tag}`;

    await signInAs(page, customer.email);
    await page.goto(customer.ws(`erp/targets/${qbo.id}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(qbo.name);
    await expect(page.getByText(/not set/)).toBeVisible();

    // Without a credential the test cannot even try.
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(page.getByText("Not connected. set the target's credential first")).toBeVisible();

    // Storing nothing is refused, and says what is missing.
    await page.getByRole("button", { name: "Set credential" }).click();
    await page.getByRole("button", { name: "Store encrypted" }).click();
    await expect(page.getByText(/the credential needs token/)).toBeVisible();
    expect((await targetRow(qbo.id)).credential_set).toBe(false);

    // The token is stored encrypted; the page shows its fingerprint, never the token.
    await page.getByRole("textbox", { name: /^Token/ }).fill(secret);
    await page.getByRole("button", { name: "Store encrypted" }).click();
    await expect(page.getByText(/fingerprint [0-9a-f]+/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Replace" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Set credential" })).toHaveCount(0);
    const stored = await targetRow(qbo.id);
    expect(stored.credential_set).toBe(true);
    expect(stored.credential_fingerprint).toBeTruthy();
    await expect(page.getByText(`fingerprint ${stored.credential_fingerprint}`)).toBeVisible();
    expect(await page.content()).not.toContain(secret);
    const read = await api(customer.session, "GET", erp(`/targets/${qbo.id}`));
    expect(read.text).not.toContain(secret);
    await page.reload();
    await expect(page.getByText(`fingerprint ${stored.credential_fingerprint}`)).toBeVisible();

    // With a credential the test goes out to the ERP's address — which does not exist — and says so.
    await page.getByRole("button", { name: "Test connection" }).click();
    const verdict = page.getByText(/^Not connected\./);
    await expect(verdict).toBeVisible();
    await expect(verdict).toContainText("qbo.erp-e2e.test");
    await expect(page.getByText("set the target's credential first")).toHaveCount(0);
    const probed = await api<TestResult>(customer.session, "POST", erp(`/targets/${qbo.id}/test`));
    expect(probed.status).toBe(200);
    expect(probed.body.ok).toBe(false);
    expect(probed.body.message).toContain("qbo.erp-e2e.test");

    // A download target has nothing to connect to: that test is a success, and it has no credential.
    await page.goto(customer.ws(`erp/targets/${csv.id}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(csv.name);
    await expect(page.getByRole("button", { name: "Set credential" })).toHaveCount(0);
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(page.getByText("Connected. download targets have nothing to connect to")).toBeVisible();
    const download = await api<TestResult>(customer.session, "POST", erp(`/targets/${csv.id}/test`));
    expect(download.body).toMatchObject({ ok: true, kind: "OK" });
    await expectHealthyPage(page);
  });

  test("a contributor and a viewer see none of these buttons, and the server refuses them", async ({ page }) => {
    const csv = await csvTarget("Roles books");
    const qbo = await quickBooksTarget("Roles QuickBooks");
    const [planned] = await postVia(customer.session, csv.id, ["PURCHASE_ORDER"]);
    const postingId = planned?.posting_id ?? "";
    expect(planned?.state).toBe("DELIVERED");

    // --- the contributor, on the pages ---
    await signInAs(page, contributor.email);
    await page.goto(customer.ws("erp"));
    await expect(page.getByRole("heading", { name: "ERP posting", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "New target" })).toHaveCount(0);
    await page.getByRole("tab", { name: "Ready to post" }).click();
    const card = page.getByRole("article").filter({ hasText: INVOICE_FILE });
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.getByLabel("Target").selectOption({ label: csv.name });
    await expect(card.getByLabel("Post Vendor bill")).toBeDisabled();
    await expect(card.getByRole("button", { name: /^Post( \d+)?$/ })).toHaveCount(0);

    await page.goto(customer.ws(`erp/postings/${postingId}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(`Purchase order ${PO_NUMBER}`);
    await expect(stateBadge(page, "Awaiting acknowledgement")).toBeVisible();
    await expect(page.getByRole("region", { name: "Decide" })).toHaveCount(0);
    for (const name of ["Do not post", "Retry", "Imported", "The ERP has it"]) {
      await expect(page.getByRole("button", { name }), name).toHaveCount(0);
    }

    await page.goto(customer.ws(`erp/targets/${qbo.id}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(qbo.name);
    await expect(page.getByLabel("Mapping for VENDOR_BILL")).toBeVisible();
    await expect(page.getByLabel("Mapping for VENDOR_BILL")).not.toBeEditable();
    for (const name of ["Test connection", "Set credential", "Replace", "Save as new version", "Restore default", "Save settings"]) {
      await expect(page.getByRole("button", { name }), name).toHaveCount(0);
    }

    // --- the server, for both people ---
    const defaultSpec = (await mappingsOf(csv.id)).default_spec;
    const body = { target_id: csv.id, source_kind: "PROCUREMENT_CASE", source_id: caseId, object_kinds: ["VENDOR_BILL"] };
    for (const [who, person] of [["contributor", contributor], ["viewer", viewer]] as const) {
      const attempts: Array<[string, string, unknown]> = [
        ["POST", erp("/postings"), body],
        ["POST", erp(`/postings/${postingId}/retry`), {}],
        ["POST", erp(`/postings/${postingId}/accept`), {}],
        ["POST", erp(`/postings/${postingId}/cancel`), {}],
        ["POST", erp(`/postings/${postingId}/acknowledge`), { accepted: true }],
        ["POST", erp(`/targets/${qbo.id}/test`), undefined],
        ["PUT", erp(`/targets/${qbo.id}/credential`), { credential: { token: "not-allowed" } }],
        ["PUT", erp(`/targets/${csv.id}/mappings/VENDOR_BILL`), { spec: defaultSpec, note: "no" }],
        ["POST", erp(`/targets/${csv.id}/mappings/VENDOR_BILL/default`), undefined],
      ];
      for (const [method, url, payload] of attempts) {
        const refused = await api(person.session, method, url, payload);
        expect(refused.status, `${who}: ${method} ${url}: ${refused.text.slice(0, 200)}`).toBe(403);
      }
    }
    // The viewer cannot preview or download a posting's file (a contributor can).
    const preview = { target_id: csv.id, source_kind: "PROCUREMENT_CASE", source_id: caseId, object_kind: "VENDOR_BILL" };
    expect((await api(viewer.session, "POST", erp("/postings/preview"), preview)).status).toBe(403);
    expect((await api(viewer.session, "GET", erp(`/postings/${postingId}/file`))).status).toBe(403);
    expect((await api(contributor.session, "GET", erp(`/postings/${postingId}/file`))).status).toBe(200);
    // Reading stays open to both.
    for (const person of [contributor, viewer]) {
      expect((await api(person.session, "GET", erp(`/postings/${postingId}`))).status).toBe(200);
    }

    // Nothing changed behind the refusals.
    expect((await detailOf(postingId)).posting.state).toBe("DELIVERED");
    expect((await postingsOf(csv.id)).map((p) => p.object_kind)).toEqual(["PURCHASE_ORDER"]);
    expect((await targetRow(qbo.id)).credential_set).toBe(false);
    expect((await mappingsOf(csv.id)).versions).toHaveLength(1);
    await expectHealthyPage(page);
  });
});
