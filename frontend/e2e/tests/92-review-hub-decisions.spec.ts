/**
 * REVIEW HUB DECISIONS (Verification → Review; campaign Session C).
 *
 * The review hub is one queue over everything that waits on a person. On a tenant of its own
 * (Enterprise plan, so every kind of item is switched on) the worker and the engines raise real
 * items from real uploads, and this spec decides them in the browser, one by one and in bulk:
 *
 *   - Tables:        "Accept figures" (table becomes Reviewed) and "Reject table" (Rejected)
 *   - Entity merges: "Same record — merge" (the two records become one) and "Different — keep
 *                    separate" (two records stay, the pair is remembered as separate)
 *   - Obligations:   "Confirm obligation" (Confirmed) and "Not an obligation" (Rejected)
 *   - ERP postings:  "Retry posting" (after the mapping is put right), "The ERP has it" (with the
 *                    ERP's reference) and "Do not post" on postings the mapping made fail
 *   - Comparisons:   "Confirm differences" on one, then selecting two and "Dismiss all"
 *   - Clauses:       selecting three and "All pass"
 *   - Anomalies:     selecting three and "Dismiss all" (which needs a reason of 10+ characters)
 *
 * Every decision is checked on the page (the item leaves the queue and shows in History), through
 * the object's own API (its status really changed), and in the audit log (one REVIEW_ITEM row
 * naming the kind and the decision). The bulk checks also prove the items that were NOT selected
 * stay open and untouched. A viewer cannot open the hub and the server refuses them; a
 * contributor sees no buttons on an ERP posting and the server refuses them too.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import type { Locator, Page } from "@playwright/test";

import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api, listWorkItems, uploadFile, type ApiSession } from "../support/api";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

const tag = runId().toUpperCase();
const INVOICE_NUMBER = `INV-${tag}`;
const PO_NUMBER = `PO-${tag}`;
const VENDOR = `Northwind Fasteners ${tag} Ltd`;
const BUYER = "Review Hub Ltd";
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "servabo-e2e-review-hub-"));

interface QueueItem {
  readonly kind: string;
  readonly item_id: string;
  readonly headline: string;
  readonly document_name: string | null;
  readonly status: string;
  readonly version: number;
}
interface AuditRow {
  readonly actor_id: string | null;
  readonly resource_type: string;
  readonly details: { readonly review_kind?: string; readonly resolution?: string } | null;
}
interface TableDetail { readonly table: { readonly status: string } }
interface Finding { readonly id: string; readonly status: string; readonly resolution_note: string | null }
interface ObligationRow { readonly id: string; readonly review: string; readonly state: string }
interface Discrepancy { readonly status: string; readonly is_material: boolean }
interface RunDetail { readonly run: { readonly status: string }; readonly discrepancies: Discrepancy[] }
interface Candidate { readonly id: string; readonly left_name: string; readonly right_name: string }
interface EntityRow { readonly id: string; readonly display_name: string; readonly merged_records: number }
interface TargetRow { readonly id: string; readonly name: string }
interface PostingRow { readonly id: string; readonly state: string; readonly target_id: string; readonly external_id: string | null }
interface Spec { header: Array<{ to: string; required?: boolean }> }
interface Versions { default_spec: Spec }

let customer: Customer;
let contributor: { email: string; session: ApiSession };
let viewer: { email: string; session: ApiSession };
let caseId = "";
const documentIds: string[] = [];
const targets: Record<"retry" | "accept" | "cancel" | "contributor", TargetRow> = {} as never;
const postingOf: Record<string, string> = {};

const ws = (suffix = ""): string => `/workspaces/${customer.wsId}${suffix}`;
const erp = (suffix = ""): string => ws(`/erp${suffix}`);
const contractFile = (n: number): string => `contract-${n}-${tag}.pdf`;

async function upload(name: string, lines: string[]): Promise<string> {
  const file = path.join(dir, name);
  fs.writeFileSync(file, buildPdf([lines]));
  const sent = await uploadFile(customer.session, customer.wsId, file);
  expect(sent.status, sent.text.slice(0, 200)).toBe(201);
  return String((sent.body as { id: string }).id);
}

/** Five line items (qty × price = amount); the third line's amount is printed 5.00 too high. */
function flaggedTable(label: string): string[] {
  const rows: Array<[string, number, number]> = [["Bolts", 10, 2.5], ["Nuts", 20, 1.25], ["Washers", 40, 0.75], ["Gaskets", 5, 8], ["Clamps", 8, 6.5]];
  const printed = (index: number): number => rows[index][1] * rows[index][2] + (index === 2 ? 5 : 0);
  const total = rows.reduce((sum, row) => sum + row[1] * row[2], 0);
  return [`PARTS STATEMENT ${label}`, `Reference: STMT-${label}-${tag}`, "Line items:", "|#|Description|Qty|Unit Price|Amount",
    ...rows.map((row, i) => `|${i + 1}|${row[0]}|${row[1]}|${row[2].toFixed(2)}|${printed(i).toFixed(2)}`), `|||||${total.toFixed(2)}`];
}

/** A services agreement: it fails the "30 days" clause check, differs from the others in its terms,
 *  and carries a delivery date written 0N/06/2026 (day-first or month-first: the extractor doubts it). */
function contract(n: number, noticeDays: number, paymentDays: number, law: string): string[] {
  return [
    `SERVICES AGREEMENT ${tag}-${n}`, "between Contoso Retail and Acme Supplies Ltd",
    "1. Services. Acme shall provide maintenance services.",
    `2. Termination. Either party may terminate this Agreement by giving ${noticeDays} days' written notice.`,
    `3. Payment. The Customer shall pay each invoice within ${paymentDays} days of receipt.`,
    `4. Governing law. ${law}.`,
    `5. Delivery. The Supplier shall deliver the Migration Plan on or before 0${n}/06/2026.`,
  ];
}

function invoice(number: string, vendor: string): string[] {
  return ["INVOICE", `Vendor: ${vendor}`, "Vendor Address: 12 Foundry Road, Leeds LS1 4AB, United Kingdom", `Bill To: ${BUYER}`,
    `Invoice Number: ${number}`, "Invoice Date: 2026-09-15", "Currency: USD", "Total Amount Due: 100.00 USD"];
}

async function queue(kind: string, status: "OPEN" | "RESOLVED" = "OPEN", session: ApiSession = customer.session): Promise<QueueItem[]> {
  const listed = await api<{ items: QueueItem[] }>(session, "GET", ws(`/review?kind=${kind}&status=${status}&page_size=100`));
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
}

async function counts(): Promise<Record<string, number>> {
  const listed = await api<{ counts_by_kind: Record<string, number> }>(customer.session, "GET", ws("/review?page_size=1"));
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.counts_by_kind;
}

async function itemWhere(kind: string, test: (item: QueueItem) => boolean, what: string): Promise<QueueItem> {
  const found = (await queue(kind)).find(test);
  expect(found, `an open ${kind} item for ${what}`).toBeTruthy();
  return found as QueueItem;
}

async function auditOf(itemId: string): Promise<AuditRow[]> {
  let rows: AuditRow[] = [];
  await expect.poll(async () => {
    const listed = await api<{ items: AuditRow[] }>(customer.session, "GET",
      `/organizations/${customer.orgId}/audit-logs?resource_type=REVIEW_ITEM&resource_id=${itemId}`);
    expect(listed.status, listed.text.slice(0, 200)).toBe(200);
    rows = listed.body.items;
    return rows.length;
  }, { timeout: 30_000, intervals: [500, 1_000, 2_000] }).toBeGreaterThan(0);
  return rows;
}

/** One REVIEW_ITEM audit row for this item, by this person, naming the kind and the decision. */
async function expectAudited(itemId: string, kind: string, decision: string, actor: ApiSession = customer.session): Promise<void> {
  const rows = await auditOf(itemId);
  expect(rows).toHaveLength(1);
  expect(rows[0]).toMatchObject({ resource_type: "REVIEW_ITEM", actor_id: String(actor.me.id) });
  expect(rows[0].details).toMatchObject({ review_kind: kind, resolution: decision });
}

async function auditOfCount(itemId: string): Promise<number> {
  const listed = await api<{ items: AuditRow[] }>(customer.session, "GET",
    `/organizations/${customer.orgId}/audit-logs?resource_type=REVIEW_ITEM&resource_id=${itemId}`);
  expect(listed.status, listed.text.slice(0, 200)).toBe(200);
  return listed.body.items.length;
}

const hubList = (page: Page): Locator => page.getByRole("list", { name: "Review items" });
const rowOf = (page: Page, text: string | RegExp): Locator => hubList(page).getByRole("listitem").filter({ hasText: text });

async function openHub(page: Page, view: string, tabName: string): Promise<void> {
  await page.goto(`${customer.ws("verification")}?view=${view}`);
  await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
  await expect(page.getByRole("tab", { name: tabName, selected: true })).toBeVisible();
  await expect(hubList(page)).toBeVisible({ timeout: 30_000 });
}

/** Press Resolve on a row and then one of the kind's decision buttons. */
async function decide(row: Locator, button: string | RegExp): Promise<void> {
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "Resolve", exact: true }).click();
  const choice = row.getByRole("button", typeof button === "string" ? { name: button, exact: true } : { name: button });
  await expect(choice).toBeVisible();
  await choice.click();
}

async function expectInHistory(page: Page, text: string | RegExp, kindLabel: string): Promise<void> {
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("tab", { name: "History", selected: true })).toBeVisible();
  const row = rowOf(page, text).filter({ hasText: kindLabel });
  await expect(row).toHaveCount(1, { timeout: 30_000 });
  await row.getByRole("button", { expanded: false }).first().click();
  await expect(row.getByText("Resolved.")).toBeVisible();
}

async function csvTarget(label: string): Promise<TargetRow> {
  const created = await api<{ target: TargetRow }>(customer.session, "POST", erp("/targets"),
    { name: `${label} ${tag}`, format: "CSV", transport: "DOWNLOAD" });
  expect(created.status, created.text.slice(0, 300)).toBe(201);
  return created.body.target;
}

async function saveMapping(targetId: string, spec: Spec, note: string): Promise<void> {
  const saved = await api(customer.session, "PUT", erp(`/targets/${targetId}/mappings/VENDOR_BILL`), { spec, note });
  expect(saved.status, saved.text.slice(0, 300)).toBe(200);
}

async function defaultSpec(targetId: string): Promise<Spec> {
  const versions = await api<Versions>(customer.session, "GET", erp(`/targets/${targetId}/mappings/VENDOR_BILL`));
  expect(versions.status, versions.text.slice(0, 300)).toBe(200);
  return versions.body.default_spec;
}

async function postingDetail(postingId: string): Promise<{ posting: PostingRow; attempts: Array<{ kind: string; message: string | null }> }> {
  const detail = await api<{ posting: PostingRow; attempts: Array<{ kind: string; message: string | null }> }>(customer.session, "GET", erp(`/postings/${postingId}`));
  expect(detail.status, detail.text.slice(0, 300)).toBe(200);
  return detail.body;
}

test.describe("Review hub — decide one item of each kind, then in bulk", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(900_000);
    customer = await newCustomer("rhub", BUYER);
    standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "6");
    // The tolerance is set BEFORE the documents arrive: publishing a policy re-matches the cases.
    const policy = await api(customer.session, "POST", ws("/procurement/policies"), { price_tolerance_bps: 500 });
    expect(policy.status, policy.text.slice(0, 200)).toBeLessThan(300);
    // A clause check the contracts fail (they give 10 to 25 days' notice): clause items for the hub.
    const check = await api<{ rule_id: string; node_key: string }>(customer.session, "POST", ws("/assertions/clause-checks"), { name: "Notice at least 30 days" });
    expect(check.status, check.text).toBe(201);
    const saved = await api(customer.session, "PUT", ws(`/assertions/rules/${check.body.rule_id}/nodes/${check.body.node_key}`),
      { node_key: check.body.node_key, sentence: "The notice period for termination must be at least 30 days.", threshold: "0.8" });
    expect(saved.status, saved.text).toBe(200);

    documentIds.push(await upload(contractFile(1), contract(1, 15, 30, "India")));
    documentIds.push(await upload(contractFile(2), contract(2, 10, 60, "Singapore")));
    documentIds.push(await upload(contractFile(3), contract(3, 20, 90, "England")));
    documentIds.push(await upload(contractFile(4), contract(4, 25, 45, "Ireland")));
    // Two spellings of one supplier each: the entity graph is unsure and asks a person.
    await upload(`inv-a-${tag}.pdf`, invoice(`INV-A-${tag}`, "Hartwell Fasteners Supplies Ltd"));
    await upload(`inv-b-${tag}.pdf`, invoice(`INV-B-${tag}`, "Hartwell Fasteners Supply Ltd"));
    await upload(`inv-c-${tag}.pdf`, invoice(`INV-C-${tag}`, "Larkspur Industrial Suppliers Ltd"));
    await upload(`inv-d-${tag}.pdf`, invoice(`INV-D-${tag}`, "Larkspur Industrial Supplies Ltd"));
    // Tables whose figures do not reconcile.
    for (const label of ["accept", "reject", "viewer"]) await upload(`parts-${label}-${tag}.pdf`, flaggedTable(label));
    // A purchase order, a goods receipt and an invoice that match: an approved case to post.
    await upload(`purchase-order-${PO_NUMBER}.pdf`, [
      "PURCHASE ORDER", `Buyer: ${BUYER}`, `Vendor: ${VENDOR}`, `PO Number: ${PO_NUMBER}`, "PO Date: 2026-09-01",
      "Currency: USD", "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00",
      "|2|Steel toe boots|10|60.00|600.00", "PO Total: 1100.00 USD"]);
    await upload(`goods-receipt-GR-${tag}.pdf`, [
      "GOODS RECEIPT NOTE", `Receiver: ${BUYER} warehouse 3`, `Vendor: ${VENDOR}`, `Receipt Number: GR-${tag}`,
      `PO Number: ${PO_NUMBER}`, "Received Date: 2026-09-12", "|#|Description|Qty received",
      "|1|Industrial safety gloves|100", "|2|Steel toe boots|10"]);
    await upload(`invoice-${INVOICE_NUMBER}.pdf`, [
      "INVOICE", `Vendor: ${VENDOR}`, "Vendor Address: 12 Foundry Road, Leeds LS1 4AB, United Kingdom",
      "Vendor Bank Account: GB29 NWBK 6016 1331 9268 19", `Bill To: ${BUYER}`, `Invoice Number: ${INVOICE_NUMBER}`,
      "Invoice Date: 2026-09-15", "Due Date: 2026-10-15", `PO Number: ${PO_NUMBER}`, "Currency: USD", "Line items:",
      "|#|Description|Qty|Unit Price|Amount", "|1|Industrial safety gloves|100|5.00|500.00",
      "|2|Steel toe boots|10|60.00|600.00", "Subtotal: 1100.00", "Tax (VAT 13.64%): 150.00",
      "Total Amount Due: 1250.00 USD", "Payment terms: Net 30"]);
    await expect.poll(async () => {
      const items = await listWorkItems(customer.session, customer.wsId);
      return items.length === 14 && items.every((i) => /COMPLETED|NEEDS_REVIEW/.test(String(i.status))) ? "ready" : items.map((i) => i.status).join(",");
    }, { timeout: 420_000, intervals: [2_000, 3_000] }).toBe("ready");

    // Four comparisons: each starts from a different contract, so each row names its own document.
    for (const [first, second] of [[0, 1], [1, 2], [2, 3], [3, 0]] as const) {
      const requested = await api(customer.session, "POST", ws("/corroboration/runs"), { work_item_ids: [documentIds[first], documentIds[second]] });
      expect(requested.status, requested.text.slice(0, 300)).toBeLessThan(300);
    }
    // The approved case, and four ERP postings that fail because the mapping asks for a field the invoice lacks.
    let found: Array<{ id: string }> = [];
    await expect.poll(async () => {
      const listed = await api<Array<{ id: string; status: string; invoice_number?: string }>>(customer.session, "GET", ws("/procurement/cases"));
      found = (Array.isArray(listed.body) ? listed.body : []).filter((c) => c.status !== "SUPERSEDED" && c.invoice_number === INVOICE_NUMBER);
      return found.length;
    }, { timeout: 120_000, intervals: [1_000, 2_000] }).toBe(1);
    caseId = found[0]?.id ?? "";
    const approved = await api<{ status: string }>(customer.session, "POST", ws(`/procurement/cases/${caseId}/approve`), {});
    expect(approved.status, approved.text.slice(0, 300)).toBe(200);
    for (const key of ["retry", "accept", "cancel", "contributor"] as const) {
      const target = await csvTarget(`Books ${key}`);
      targets[key] = target;
      const spec = JSON.parse(JSON.stringify(await defaultSpec(target.id))) as Spec;
      const field = spec.header.find((f) => f.to === "VendorTaxId");
      expect(field, "the default mapping has a VendorTaxId field").toBeTruthy();
      if (field) field.required = true;
      await saveMapping(target.id, spec, "Require the vendor tax id");
      const posted = await api<{ results: Array<{ posting_id: string | null; state: string | null }> }>(customer.session, "POST", erp("/postings"),
        { target_id: target.id, source_kind: "PROCUREMENT_CASE", source_id: caseId, object_kinds: ["VENDOR_BILL"] });
      expect(posted.status, posted.text.slice(0, 300)).toBe(201);
      expect(posted.body.results[0]?.state).toBe("FAILED");
      postingOf[key] = posted.body.results[0]?.posting_id ?? "";
    }

    await expect.poll(async () => {
      const c = await counts();
      if (!(c.OBLIGATION >= 4 && c.TABLE >= 3 && c.CORROBORATION >= 4 && c.MERGE >= 2 && c.POSTING >= 4)) return JSON.stringify(c);
      const clauses = (await queue("ASSERTION")).map((i) => i.document_name ?? "");
      const contracts = [1, 2, 3, 4].filter((n) => clauses.includes(contractFile(n))).length;
      const anomalies = (await queue("ANOMALY")).filter((i) => i.headline.includes("contract-")).length;
      return contracts === 4 && clauses.length > 4 && anomalies >= 3 ? "ready" : `clauses ${clauses.length} (${contracts} contracts), contract anomalies ${anomalies}`;
    }, { timeout: 420_000, intervals: [3_000, 5_000] }).toBe("ready");

    contributor = await addMember(customer, "rhub-contrib", "MEMBER", "CONTRIBUTOR");
    viewer = await addMember(customer, "rhub-viewer", "MEMBER", "VIEWER");
  });

  test("Tables: Accept figures marks the table Reviewed; Reject table marks it Rejected; the others stay open", async ({ page }) => {
    const accept = await itemWhere("TABLE", (i) => i.document_name === `parts-accept-${tag}.pdf`, "the table to accept");
    const reject = await itemWhere("TABLE", (i) => i.document_name === `parts-reject-${tag}.pdf`, "the table to reject");
    const tableStatus = async (id: string): Promise<string> => {
      const detail = await api<TableDetail>(customer.session, "GET", ws(`/tables/${id}`));
      expect(detail.status, detail.text.slice(0, 200)).toBe(200);
      return detail.body.table.status;
    };
    expect(await tableStatus(accept.item_id)).toBe("FLAGGED");

    await signInAs(page, customer.email);
    await openHub(page, "TABLE", "Tables");
    const open = (await counts()).TABLE;
    await expect(hubList(page).getByRole("listitem")).toHaveCount(open);

    // Accept figures.
    const acceptRow = rowOf(page, `parts-accept-${tag}.pdf`);
    await decide(acceptRow, "Accept figures");
    await expect(page.getByText("Resolved: accept.").first()).toBeVisible();
    await expect(acceptRow).toHaveCount(0);
    await expect(hubList(page).getByRole("listitem")).toHaveCount(open - 1);
    expect(await tableStatus(accept.item_id)).toBe("REVIEWED");
    expect((await queue("TABLE")).map((i) => i.item_id)).not.toContain(accept.item_id);
    await expectAudited(accept.item_id, "TABLE", "ACCEPT");
    await expectInHistory(page, `parts-accept-${tag}.pdf`, "Table");

    // Reject table, after a reload (the hub starts from what the server holds).
    await openHub(page, "TABLE", "Tables");
    await expect(rowOf(page, `parts-accept-${tag}.pdf`)).toHaveCount(0);
    const rejectRow = rowOf(page, `parts-reject-${tag}.pdf`);
    await decide(rejectRow, "Reject table");
    await expect(page.getByText("Resolved: reject.").first()).toBeVisible();
    await expect(rejectRow).toHaveCount(0);
    expect(await tableStatus(reject.item_id)).toBe("REJECTED");
    await expectAudited(reject.item_id, "TABLE", "REJECT");

    // The third table was not touched.
    const viewerTable = await itemWhere("TABLE", (i) => i.document_name === `parts-viewer-${tag}.pdf`, "the untouched table");
    expect(await tableStatus(viewerTable.item_id)).toBe("FLAGGED");
    await expect(rowOf(page, `parts-viewer-${tag}.pdf`)).toHaveCount(1);
    expect((await counts()).TABLE).toBe(open - 2);
    await expectHealthyPage(page);
  });

  test("Entity merges: 'Same record — merge' joins the two records; 'Different — keep separate' keeps two and remembers it", async ({ page }) => {
    const candidates = async (state: string): Promise<Candidate[]> => {
      const listed = await api<Candidate[]>(customer.session, "GET", ws(`/entities/merge-candidates?status=${state}`));
      expect(listed.status, listed.text.slice(0, 200)).toBe(200);
      return listed.body;
    };
    const records = async (name: string): Promise<EntityRow[]> => {
      const listed = await api<{ items: EntityRow[] }>(customer.session, "GET", ws(`/entities?kind=ORGANIZATION&q=${name}`));
      expect(listed.status, listed.text.slice(0, 200)).toBe(200);
      return listed.body.items;
    };
    const hartwell = (await candidates("OPEN")).find((c) => /Hartwell/.test(c.left_name));
    const larkspur = (await candidates("OPEN")).find((c) => /Larkspur/.test(c.left_name));
    expect(hartwell && larkspur, "an open merge proposal for each supplier").toBeTruthy();
    expect(await records("Hartwell")).toHaveLength(2);
    expect(await records("Larkspur")).toHaveLength(2);

    await signInAs(page, customer.email);
    await openHub(page, "MERGE", "Entity merges");
    await expect(hubList(page).getByRole("listitem")).toHaveCount(2);

    // Same record — merge.
    const mergeRow = rowOf(page, /Hartwell/);
    await decide(mergeRow, "Same record — merge");
    await expect(page.getByText("Resolved: merge.").first()).toBeVisible();
    await expect(mergeRow).toHaveCount(0);
    expect((await candidates("MERGED")).map((c) => c.id)).toContain(hartwell!.id);
    const merged = await records("Hartwell");
    expect(merged, "the two spellings are now one record").toHaveLength(1);
    expect(merged[0]?.merged_records).toBe(1);
    await expectAudited(hartwell!.id, "MERGE", "MERGE");
    await expectInHistory(page, /Hartwell/, "Entity merge");

    // Different — keep separate.
    await openHub(page, "MERGE", "Entity merges");
    const separateRow = rowOf(page, /Larkspur/);
    await decide(separateRow, "Different — keep separate");
    await expect(page.getByText("Resolved: separate.").first()).toBeVisible();
    await expect(separateRow).toHaveCount(0);
    expect((await candidates("SEPARATE")).map((c) => c.id)).toContain(larkspur!.id);
    const apart = await records("Larkspur");
    expect(apart, "still two records").toHaveLength(2);
    expect(apart.every((r) => r.merged_records === 0)).toBe(true);
    await expectAudited(larkspur!.id, "MERGE", "SEPARATE");
    expect((await counts()).MERGE).toBe(0);
    await expectHealthyPage(page);
  });

  test("Obligations: Confirm obligation confirms it; Not an obligation rejects it and it leaves the lists", async ({ page }) => {
    const confirm = await itemWhere("OBLIGATION", (i) => i.document_name === contractFile(1), "contract 1's delivery");
    const reject = await itemWhere("OBLIGATION", (i) => i.document_name === contractFile(2), "contract 2's delivery");
    const obligation = async (id: string): Promise<ObligationRow> => {
      const got = await api<{ obligation: ObligationRow }>(customer.session, "GET", ws(`/obligations/${id}`));
      expect(got.status, got.text.slice(0, 200)).toBe(200);
      return got.body.obligation;
    };
    expect((await obligation(confirm.item_id)).review).toBe("PENDING");

    await signInAs(page, customer.email);
    await openHub(page, "OBLIGATION", "Obligations");
    const confirmRow = rowOf(page, "due 01 Jun 2026");
    await decide(confirmRow, "Confirm obligation");
    await expect(page.getByText("Resolved: confirm.").first()).toBeVisible();
    await expect(confirmRow).toHaveCount(0);
    expect((await obligation(confirm.item_id)).review).toBe("CONFIRMED");
    await expectAudited(confirm.item_id, "OBLIGATION", "CONFIRM");
    await expectInHistory(page, "due 01 Jun 2026", "Obligation");

    await openHub(page, "OBLIGATION", "Obligations");
    const rejectRow = rowOf(page, "due 02 Jun 2026");
    await decide(rejectRow, "Not an obligation");
    await expect(page.getByText("Resolved: reject.").first()).toBeVisible();
    await expect(rejectRow).toHaveCount(0);
    expect((await obligation(reject.item_id)).review).toBe("REJECTED");
    const listed = await api<{ items: ObligationRow[] }>(customer.session, "GET", ws("/obligations?limit=100"));
    expect(listed.status, listed.text.slice(0, 200)).toBe(200);
    expect(listed.body.items.map((o) => o.id), "a rejected obligation leaves every list").not.toContain(reject.item_id);
    expect(listed.body.items.map((o) => o.id)).toContain(confirm.item_id);
    await expectAudited(reject.item_id, "OBLIGATION", "REJECT");

    // The other two are still waiting, untouched.
    for (const n of [3, 4]) {
      const item = await itemWhere("OBLIGATION", (i) => i.document_name === contractFile(n), `contract ${n}'s delivery`);
      expect((await obligation(item.item_id)).review).toBe("PENDING");
    }
    expect((await counts()).OBLIGATION).toBe(2);
    await expectHealthyPage(page);
  });

  test("ERP postings: Retry posting, The ERP has it and Do not post settle failed postings", async ({ page }) => {
    const item = async (key: string): Promise<QueueItem> => itemWhere("POSTING", (i) => i.item_id === postingOf[key], `the ${key} posting`);
    const retry = await item("retry");
    const accept = await item("accept");
    const cancel = await item("cancel");
    for (const key of ["retry", "accept", "cancel"]) expect((await postingDetail(postingOf[key])).posting.state).toBe("FAILED");

    await signInAs(page, customer.email);
    await openHub(page, "POSTING", "ERP postings");
    await expect(hubList(page).getByRole("listitem")).toHaveCount(4);

    // Retry posting: with the mapping still wrong the file cannot be built, so a person first puts the mapping right.
    await saveMapping(targets.retry.id, await defaultSpec(targets.retry.id), "Back to the default");
    const retryRow = rowOf(page, `Books retry ${tag}`);
    await decide(retryRow, "Retry posting");
    await expect(page.getByText("Resolved: retry.").first()).toBeVisible();
    await expect(retryRow).toHaveCount(0);
    const retried = await postingDetail(postingOf.retry);
    expect(retried.posting.state, "the file was built and handed to the target").toBe("DELIVERED");
    await expectAudited(retry.item_id, "POSTING", "RETRY");

    // The ERP has it: with the ERP's own reference.
    const acceptRow = rowOf(page, `Books accept ${tag}`);
    await expect(acceptRow).toHaveCount(1);
    await acceptRow.getByRole("button", { name: "Resolve", exact: true }).click();
    await acceptRow.getByLabel("ERP reference (when accepting)").fill(`BILL-${tag}`);
    await acceptRow.getByRole("button", { name: "The ERP has it" }).click();
    await expect(page.getByText("Resolved: accept.").first()).toBeVisible();
    await expect(acceptRow).toHaveCount(0);
    const accepted = await postingDetail(postingOf.accept);
    expect(accepted.posting.state).toBe("DONE");
    expect(accepted.posting.external_id).toBe(`BILL-${tag}`);
    await expectAudited(accept.item_id, "POSTING", "ACCEPT");

    // Do not post.
    const cancelRow = rowOf(page, `Books cancel ${tag}`);
    await decide(cancelRow, "Do not post");
    await expect(page.getByText("Resolved: cancel.").first()).toBeVisible();
    await expect(cancelRow).toHaveCount(0);
    expect((await postingDetail(postingOf.cancel)).posting.state).toBe("CANCELLED");
    await expectAudited(cancel.item_id, "POSTING", "CANCEL");

    // The fourth posting was not touched and is still the only one waiting; the three left in History.
    expect((await postingDetail(postingOf.contributor)).posting.state).toBe("FAILED");
    await expect(rowOf(page, `Books contributor ${tag}`)).toHaveCount(1);
    expect((await counts()).POSTING).toBe(1);
    await expectInHistory(page, `Books cancel ${tag}`, "ERP posting");
    await expectHealthyPage(page);
  });

  test("Comparisons: Confirm differences on one; select two and Dismiss all; the fourth stays open", async ({ page }) => {
    const run = (n: number) => itemWhere("CORROBORATION", (i) => i.document_name === contractFile(n), `the comparison starting at contract ${n}`);
    const [first, second, third, fourth] = [await run(1), await run(2), await run(3), await run(4)];
    const materialStatuses = async (id: string): Promise<string[]> => {
      const detail = await api<RunDetail>(customer.session, "GET", ws(`/corroboration/runs/${id}`));
      expect(detail.status, detail.text.slice(0, 200)).toBe(200);
      return detail.body.discrepancies.filter((d) => d.is_material).map((d) => d.status);
    };
    for (const item of [first, second, third, fourth]) {
      const statuses = await materialStatuses(item.item_id);
      expect(statuses.length).toBeGreaterThan(0);
      expect(new Set(statuses)).toEqual(new Set(["OPEN"]));
    }

    await signInAs(page, customer.email);
    await openHub(page, "CORROBORATION", "Comparisons");
    await expect(hubList(page).getByRole("listitem")).toHaveCount(4);

    // Confirm differences, one comparison.
    const firstRow = rowOf(page, `Documents disagree: ${contractFile(1)}`);
    await decide(firstRow, "Confirm differences");
    await expect(page.getByText("Resolved: confirm.").first()).toBeVisible();
    await expect(firstRow).toHaveCount(0);
    expect(new Set(await materialStatuses(first.item_id))).toEqual(new Set(["CONFIRMED"]));
    await expectAudited(first.item_id, "CORROBORATION", "CONFIRM");

    // Select two of the three that are left, and dismiss them together.
    const secondRow = rowOf(page, `Documents disagree: ${contractFile(2)}`);
    const thirdRow = rowOf(page, `Documents disagree: ${contractFile(3)}`);
    await secondRow.getByRole("button", { name: "Select", exact: true }).click();
    await thirdRow.getByRole("button", { name: "Select", exact: true }).click();
    const bulk = page.getByRole("region", { name: "Bulk actions" });
    await expect(bulk).toContainText("2 selected");
    await bulk.getByRole("button", { name: "Dismiss all" }).click();
    await expect(page.getByText("2 done.").first()).toBeVisible();
    await expect(secondRow).toHaveCount(0);
    await expect(thirdRow).toHaveCount(0);
    await expect(bulk).toHaveCount(0);
    for (const item of [second, third]) {
      expect(new Set(await materialStatuses(item.item_id)), "every selected comparison was dismissed server-side").toEqual(new Set(["DISMISSED"]));
      await expectAudited(item.item_id, "CORROBORATION", "DISMISS");
    }
    // Not selected: still open in the queue and untouched on the server.
    expect(new Set(await materialStatuses(fourth.item_id))).toEqual(new Set(["OPEN"]));
    expect((await queue("CORROBORATION")).map((i) => i.item_id)).toEqual([fourth.item_id]);
    expect(await auditOfCount(fourth.item_id)).toBe(0);
    await expect(rowOf(page, `Documents disagree: ${contractFile(4)}`)).toHaveCount(1);
    await expectInHistory(page, `Documents disagree: ${contractFile(2)}`, "Comparison");
    await expectHealthyPage(page);
  });

  test("Clauses: select three and All pass; a fourth is decided alone with Fails; the invoices' clauses stay open", async ({ page }) => {
    const clause = (n: number) => itemWhere("ASSERTION", (i) => i.document_name === contractFile(n), `contract ${n}'s clause`);
    const [one, two, three, four] = [await clause(1), await clause(2), await clause(3), await clause(4)];
    const waiting = async (): Promise<string[]> => {
      const listed = await api<Array<{ evaluation_id: string }>>(customer.session, "GET", ws("/assertions/reviews?limit=200"));
      expect(listed.status, listed.text.slice(0, 200)).toBe(200);
      return listed.body.map((r) => r.evaluation_id);
    };
    const before = await waiting();
    for (const item of [one, two, three, four]) expect(before).toContain(item.item_id);
    const others = (await queue("ASSERTION")).filter((i) => ![one, two, three, four].some((x) => x.item_id === i.item_id));
    expect(others.length, "the invoices' clause items").toBeGreaterThan(0);

    await signInAs(page, customer.email);
    await openHub(page, "ASSERTION", "Clause assertions");
    const rows = [1, 2, 3].map((n) => rowOf(page, contractFile(n)));
    const bulk = page.getByRole("region", { name: "Bulk actions" });
    await expect(bulk).toHaveCount(0);
    for (const row of rows) await row.getByRole("button", { name: "Select", exact: true }).click();
    await expect(bulk).toContainText("3 selected");
    await bulk.getByRole("button", { name: "All pass" }).click();
    await expect(page.getByText("3 done.").first()).toBeVisible();
    for (const row of rows) await expect(row).toHaveCount(0);
    await expect(bulk).toHaveCount(0);
    const after = await waiting();
    for (const item of [one, two, three]) {
      expect(after, "decided server-side").not.toContain(item.item_id);
      await expectAudited(item.item_id, "ASSERTION", "PASS");
    }
    // Not selected: the fourth contract's clause and every invoice's are still waiting.
    expect(after).toContain(four.item_id);
    for (const item of others) expect(after).toContain(item.item_id);

    // One clause decided alone: Fails.
    const fourRow = rowOf(page, contractFile(4));
    await decide(fourRow, "Fails");
    await expect(page.getByText("Resolved: fail.").first()).toBeVisible();
    await expect(fourRow).toHaveCount(0);
    expect(await waiting()).not.toContain(four.item_id);
    await expectAudited(four.item_id, "ASSERTION", "FAIL");
    for (const item of others) expect(await waiting()).toContain(item.item_id);
    await expectInHistory(page, contractFile(4), "Clause");
    await expectHealthyPage(page);
  });

  test("Anomalies: Dismiss all needs a reason of ten characters, then dismisses the selected findings only", async ({ page }) => {
    const all = await queue("ANOMALY");
    // Three of the six near-duplicate findings between the contracts (which document is named first depends on scan order).
    const mine = all.filter((i) => i.headline.includes("contract-")).slice(0, 3);
    expect(mine, "the contracts raised near-duplicate findings").toHaveLength(3);
    const rest = all.filter((i) => !mine.some((m) => m.item_id === i.item_id));
    expect(rest.length).toBeGreaterThan(0);
    const finding = async (id: string): Promise<Finding> => {
      const got = await api<Finding>(customer.session, "GET", ws(`/anomalies/${id}`));
      expect(got.status, got.text.slice(0, 200)).toBe(200);
      return got.body;
    };

    await signInAs(page, customer.email);
    await openHub(page, "ANOMALY", "Anomalies");
    const rows = mine.map((item) => rowOf(page, item.headline));
    for (const row of rows) await row.getByRole("button", { name: "Select", exact: true }).click();
    const bulk = page.getByRole("region", { name: "Bulk actions" });
    await expect(bulk).toContainText("3 selected");
    const dismiss = bulk.getByRole("button", { name: "Dismiss all" });
    await expect(dismiss).toBeDisabled();
    await bulk.getByLabel("Dismissal reason").fill("too short");
    await expect(dismiss).toBeDisabled();
    const reason = "Rescans of the same agreement, checked by hand";
    await bulk.getByLabel("Dismissal reason").fill(reason);
    await expect(dismiss).toBeEnabled();
    await dismiss.click();
    await expect(page.getByText("3 done.").first()).toBeVisible();
    for (const row of rows) await expect(row).toHaveCount(0);
    for (const item of mine) {
      const saved = await finding(item.item_id);
      expect(saved.status, "dismissed server-side").toBe("DISMISSED");
      expect(saved.resolution_note).toBe(reason);
      await expectAudited(item.item_id, "ANOMALY", "DISMISSED");
    }
    // Not selected: still open, on the page and on the server.
    const stillOpen = (await queue("ANOMALY")).map((i) => i.item_id);
    for (const item of rest) {
      expect(stillOpen).toContain(item.item_id);
      expect((await finding(item.item_id)).status).toBe("OPEN");
    }
    await expect(hubList(page).getByRole("listitem")).toHaveCount(rest.length);
    await expectInHistory(page, mine[0]!.headline, "Anomaly");
    await expectHealthyPage(page);
  });

  test("A viewer cannot open the hub and the server refuses their decisions; a contributor sees no ERP buttons", async ({ page }) => {
    const table = await itemWhere("TABLE", (i) => i.document_name === `parts-viewer-${tag}.pdf`, "the untouched table");
    const posting = await itemWhere("POSTING", (i) => i.item_id === postingOf.contributor, "the untouched posting");
    const nobody = "00000000-0000-4000-8000-000000000000";

    // --- the viewer, on the page ---
    await signInAs(page, viewer.email);
    await page.goto(customer.ws("verification"));
    await expect(page.getByRole("heading", { name: "Access restricted" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Review items" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Resolve", exact: true })).toHaveCount(0);

    // --- the viewer, at the server ---
    const refused = await api(viewer.session, "GET", ws("/review?page_size=5"));
    expect(refused.status, refused.text.slice(0, 200)).toBe(403);
    const resolveTable = await api(viewer.session, "POST", ws(`/review/TABLE/${table.item_id}/resolve`), { table_verdict: "ACCEPT", expected_version: table.version });
    expect(resolveTable.status, resolveTable.text.slice(0, 200)).toBe(403);
    const resolvePosting = await api(viewer.session, "POST", ws(`/review/POSTING/${posting.item_id}/resolve`), { posting_verdict: "CANCEL" });
    expect(resolvePosting.status, resolvePosting.text.slice(0, 200)).toBe(403);
    const bulkTable = await api(viewer.session, "POST", ws("/review/bulk"), {
      action: "resolve", kind: "TABLE", ids: [table.item_id], idempotency_key: `viewer-${tag}`, payload: { table_verdict: "ACCEPT" } });
    expect(bulkTable.status, bulkTable.text.slice(0, 200)).toBe(403);
    expect((await api(viewer.session, "POST", ws(`/review/TABLE/${nobody}/assign`), { assignee_user_id: String(viewer.session.me.id) })).status).toBe(403);

    // --- the contributor: the hub opens, but an ERP posting offers no decision ---
    await signInAs(page, contributor.email);
    await openHub(page, "POSTING", "ERP postings");
    const row = rowOf(page, `Books contributor ${tag}`);
    await expect(row).toHaveCount(1);
    await row.getByRole("button", { name: "Resolve", exact: true }).click();
    await expect(row.getByText("Only a workspace administrator or the organization owner can retry, accept or cancel an ERP posting.")).toBeVisible();
    for (const name of ["Retry posting", "The ERP has it", "Do not post"]) {
      await expect(row.getByRole("button", { name }), name).toHaveCount(0);
    }
    // The server says the same, for one item and for a bulk request (which refuses the item, not the request).
    const single = await api(contributor.session, "POST", ws(`/review/POSTING/${posting.item_id}/resolve`), { posting_verdict: "CANCEL", expected_version: posting.version });
    expect(single.status, single.text.slice(0, 200)).toBe(403);
    const bulk = await api<{ ok: number; refused: number; results: Array<{ outcome: string; code: string | null }> }>(contributor.session, "POST", ws("/review/bulk"), {
      action: "resolve", kind: "POSTING", ids: [posting.item_id], idempotency_key: `contributor-${tag}`, payload: { posting_verdict: "CANCEL" },
      expected_versions: { [posting.item_id]: posting.version } });
    expect(bulk.status, bulk.text.slice(0, 200)).toBe(200);
    expect(bulk.body).toMatchObject({ ok: 0, refused: 1 });
    expect(bulk.body.results[0]).toMatchObject({ outcome: "refused", code: "FORBIDDEN" });

    // Nothing changed behind any of the refusals.
    expect((await postingDetail(postingOf.contributor)).posting.state).toBe("FAILED");
    const still = await api<TableDetail>(customer.session, "GET", ws(`/tables/${table.item_id}`));
    expect(still.body.table.status).toBe("FLAGGED");
    expect((await queue("TABLE")).map((i) => i.item_id)).toContain(table.item_id);
    expect(await auditOfCount(table.item_id)).toBe(0);
    expect(await auditOfCount(posting.item_id)).toBe(0);
    await expectHealthyPage(page);
  });
});
