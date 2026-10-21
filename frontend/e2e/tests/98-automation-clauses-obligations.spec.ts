/**
 * AUTOMATION RULES, CLAUSE CHECKS, OBLIGATIONS AND EXTRACTION MEMORY: the buttons no browser test pressed.
 *
 * Every area works on a new Enterprise customer of its own (so nothing shared changes), sets real data up
 * through the API or the real flow (an upload the worker processes), presses the button in the browser and
 * then proves the result twice: on the page after a reload, and through the API.
 *
 *  1. Automation rules: the on/off switch, "Test" (a dry run that changes nothing), Edit, Duplicate and
 *     Delete (with its confirmation); a disabled rule really stops firing on a newly uploaded document
 *     (the engine runs in the worker); a viewer is refused by the page and by the API.
 *  2. Clause checks: "It passes", "It fails", "Wrong paragraph" (with its corrected paragraph) on the review
 *     queue, and "Test on a document" while editing a clause.
 *  3. Obligations: "Waive" with its reason, and the calendar feed's "Revoke" (the old link must stop working).
 *  4. Extraction memory: "Reset" a layout and "Retire" an anchor rule, after real corrections on documents.
 */
import { execFileSync } from "node:child_process";

import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage } from "../support/fixtures";
import { API_BASE, BACKEND_DIR, runId } from "../support/env";
import { api, fetchOnce, type ApiSession } from "../support/api";
import { addMember, newCustomer, signInAs, standIn, uploadViaApi, type Customer } from "../support/journey";
import { buildPdf, DISPUTED_INVOICE_PAGE } from "../support/sample-docs";

/* ------------------------------------------------------------------ shared helpers */

async function enterpriseCustomer(label: string): Promise<Customer> {
  const customer = await newCustomer(label, `${label} Ltd`);
  standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "5");
  return customer;
}

/** Upload raw PDF bytes under an exact file name; returns the new document's id. */
async function uploadNamed(customer: Customer, filename: string, body: Buffer): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([new Uint8Array(body)], { type: "application/pdf" }), filename);
  const response = await fetchOnce(`${API_BASE}/workspaces/${customer.wsId}/work-items`, {
    method: "POST", headers: { Authorization: `Bearer ${customer.session.accessToken}` }, body: form,
  });
  expect(response.status, await response.clone().text()).toBe(201);
  return String(((await response.json()) as { id: string }).id);
}

/** Upload raw PDF bytes as the customer under a unique name; returns the new document's id. */
const uploadPdf = (customer: Customer, name: string, body: Buffer): Promise<string> =>
  uploadNamed(customer, `${name}-${runId()}.pdf`, body);

/** Wait until the worker has finished with a document. */
async function processed(session: ApiSession, workspaceId: string, id: string): Promise<void> {
  await expect.poll(async () => {
    const item = await api<{ status?: string }>(session, "GET", `/workspaces/${workspaceId}/work-items/${id}`);
    return String(item.body.status ?? "");
  }, { timeout: 180_000, intervals: [2_000] }).not.toMatch(/^(PENDING|QUEUED|PROCESSING|UPLOADED|)$/);
}

/* ================================================================== 1. AUTOMATION RULES */

interface Rule {
  readonly id: string;
  readonly name: string;
  readonly priority: number;
  readonly is_active: boolean;
  readonly on_error?: string;
  readonly triggers?: string[];
  readonly actions: Array<{ action_type: string; config: Record<string, unknown> }>;
}
interface Execution { readonly id: string; readonly rule_id: string; readonly work_item_id: string; readonly status: string }

test.describe("Automation rules: switch, test, edit, duplicate, delete", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  let customer: Customer;
  let viewer: { email: string; session: ApiSession };
  let member: { email: string; session: ApiSession };
  let sampleDocument = "";

  const rulesUrl = (): string => `/workspaces/${customer.wsId}/automation/rules`;

  /** A rule that tells the owner when a document arrives (or a trigger of your choice). */
  async function createRule(name: string, extra: Record<string, unknown> = {}): Promise<Rule> {
    const created = await api<Rule>(customer.session, "POST", rulesUrl(), {
      name,
      priority: 100,
      triggers: ["document.created"],
      condition_groups: [],
      groups_operator: "AND",
      actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: `Fired: ${name}`, message: "A document arrived." } }],
      else_actions: [],
      on_error: "HALT",
      is_active: true,
      ...extra,
    });
    expect(created.status, created.text.slice(0, 400)).toBe(201);
    return created.body;
  }

  async function getRules(): Promise<Rule[]> {
    const listed = await api<Rule[]>(customer.session, "GET", rulesUrl());
    expect(listed.status, listed.text.slice(0, 300)).toBe(200);
    return listed.body;
  }
  const byName = async (name: string): Promise<Rule | undefined> => (await getRules()).find((r) => r.name === name);

  async function executions(ruleId: string): Promise<Execution[]> {
    const listed = await api<{ items: Execution[] }>(customer.session, "GET",
      `/workspaces/${customer.wsId}/automation/executions?rule_id=${ruleId}&limit=200`);
    expect(listed.status, listed.text.slice(0, 300)).toBe(200);
    return listed.body.items;
  }

  const card = (page: Page, name: string) =>
    page.locator("main article").filter({ has: page.getByRole("heading", { name, exact: true }) });

  async function openPage(page: Page): Promise<void> {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await expect(page.getByRole("button", { name: "Create New Rule" })).toBeVisible({ timeout: 30_000 });
  }

  test.beforeAll(async () => {
    test.setTimeout(300_000);
    customer = await enterpriseCustomer("auto");
    viewer = await addMember(customer, "auto-viewer", "MEMBER", "VIEWER");
    member = await addMember(customer, "auto-member", "MEMBER", "CONTRIBUTOR");
    sampleDocument = await uploadViaApi(customer, "auto-sample");
    await processed(customer.session, customer.wsId, sampleDocument);
  });

  test("the switch turns a rule off and on; the page, the API and a reload agree", async ({ page }) => {
    const name = `Switch me ${runId()}`;
    const rule = await createRule(name);
    await openPage(page);
    const toggle = page.getByRole("switch", { name: `Toggle rule ${name}` });
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect(card(page, name)).toContainText("Active");

    const off = page.waitForResponse((r) => r.url().includes(`/automation/rules/${rule.id}`) && r.request().method() === "PATCH");
    await toggle.click();
    expect((await off).status()).toBe(200);
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(card(page, name)).toContainText("Disabled");
    expect((await byName(name))?.is_active).toBe(false);

    await page.reload();
    await expect(page.getByRole("switch", { name: `Toggle rule ${name}` })).toHaveAttribute("aria-checked", "false");
    await expect(card(page, name)).toContainText("Disabled");

    await page.getByRole("switch", { name: `Toggle rule ${name}` }).click();
    await expect(page.getByRole("switch", { name: `Toggle rule ${name}` })).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await byName(name))?.is_active).toBe(true);
    await expectHealthyPage(page);
  });

  test("a disabled rule stops firing on a newly uploaded document; switched on again it fires", async ({ page }) => {
    const stamp = runId();
    const subject = await createRule(`Subject ${stamp}`);
    const control = await createRule(`Control ${stamp}`);

    // 1. Enabled: an upload fires it.
    const first = await uploadViaApi(customer, "fires");
    await expect.poll(async () => (await executions(subject.id)).filter((e) => e.work_item_id === first).length,
      { timeout: 120_000, intervals: [2_000] }).toBeGreaterThan(0);

    // 2. Switch it off in the browser.
    await openPage(page);
    const toggle = page.getByRole("switch", { name: `Toggle rule ${subject.name}` });
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect.poll(async () => (await byName(subject.name))?.is_active).toBe(false);

    // 3. A new matching document: the control rule (still on) proves the engine ran for it, the subject did not.
    const second = await uploadViaApi(customer, "silent");
    await expect.poll(async () => (await executions(control.id)).filter((e) => e.work_item_id === second).length,
      { timeout: 120_000, intervals: [2_000] }).toBeGreaterThan(0);
    await processed(customer.session, customer.wsId, second);
    expect((await executions(subject.id)).filter((e) => e.work_item_id === second)).toHaveLength(0);

    // 4. Switch it back on: the next document fires it again.
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await byName(subject.name))?.is_active).toBe(true);
    const third = await uploadViaApi(customer, "fires-again");
    await expect.poll(async () => (await executions(subject.id)).filter((e) => e.work_item_id === third).length,
      { timeout: 120_000, intervals: [2_000] }).toBeGreaterThan(0);
    await processed(customer.session, customer.wsId, third);
    await expectHealthyPage(page);
  });

  test("Test runs the rule against a document and reports a match, or no match, without running anything", async ({ page }) => {
    const stamp = runId();
    // Created switched off: a dry run works on any rule, and an upload still in flight cannot fire them by accident.
    const matching = await createRule(`Dry match ${stamp}`, { is_active: false });
    const silent = await createRule(`Dry miss ${stamp}`, {
      is_active: false,
      condition_groups: [{ logic_operator: "AND", conditions: [{ field: "vendor_name", operator: "EQUALS", value: "Nobody Ltd" }] }],
    });
    /** How many "Fired: Dry ..." notifications the owner holds (a rule that really ran would add one). */
    const notifications = async (): Promise<number> => {
      const listed = await api<Array<{ title: string }>>(customer.session, "GET", `/workspaces/${customer.wsId}/notifications?limit=100`);
      expect(listed.status, listed.text.slice(0, 200)).toBe(200);
      return listed.body.filter((n) => n.title.startsWith("Fired: Dry")).length;
    };
    const beforeExecutions = (await executions(matching.id)).length;
    const beforeNotifications = await notifications();

    await openPage(page);
    // Matching rule.
    await page.getByRole("button", { name: `Test rule ${matching.name}` }).click();
    const dialog = page.getByRole("dialog", { name: "Test Automation Rule" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Run Test" })).toBeDisabled();
    await dialog.getByLabel("Select Test Work Item").selectOption(sampleDocument);
    const ran = page.waitForResponse((r) => r.url().includes(`/automation/rules/${matching.id}/test`) && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "Run Test" }).click();
    const dry = await ran;
    expect(dry.status()).toBe(200);
    const body = await dry.json() as { matched: boolean; notification_sent: boolean; message: string };
    expect(body.matched).toBe(true);
    expect(body.notification_sent).toBe(false);
    await expect(dialog.getByText("Rule Logic Matched")).toBeVisible();
    await expect(dialog.getByText("Notification Sent").locator("..")).toContainText("No");
    await expect(dialog).toContainText("would run: Notify a role");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);

    // A rule whose condition the document does not meet.
    await page.getByRole("button", { name: `Test rule ${silent.name}` }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Select Test Work Item").selectOption(sampleDocument);
    await dialog.getByRole("button", { name: "Run Test" }).click();
    await expect(dialog.getByText("Rule Logic Did Not Match")).toBeVisible();
    await dialog.getByRole("button", { name: "Close dialog" }).click();
    await expect(dialog).toHaveCount(0);

    // Nothing ran: no execution was recorded, no notification was sent.
    expect((await executions(matching.id)).length).toBe(beforeExecutions);
    expect((await executions(silent.id)).length).toBe(0);
    expect(await notifications()).toBe(beforeNotifications);
    await expectHealthyPage(page);
  });

  test("Edit changes the rule; the list, the API and a reload show the change", async ({ page }) => {
    const stamp = runId();
    const original = `Edit me ${stamp}`;
    const renamed = `Edited ${stamp}`;
    const rule = await createRule(original);
    await openPage(page);
    await page.getByRole("button", { name: `Edit rule ${original}` }).click();
    const builder = page.getByRole("dialog", { name: "Edit automation" });
    await expect(builder).toBeVisible();
    await expect(builder.getByRole("textbox", { name: "Name", exact: true })).toHaveValue(original);
    await builder.getByRole("textbox", { name: "Name", exact: true }).fill(renamed);
    await builder.getByRole("spinbutton", { name: "Priority" }).fill("7");
    await builder.getByLabel("On failure").selectOption("CONTINUE");
    await builder.getByRole("button", { name: "Save changes" }).click();
    await expect(builder).toHaveCount(0);
    await expect(card(page, renamed)).toBeVisible();
    await expect(card(page, renamed)).toContainText("Priority #7");
    await expect(card(page, original)).toHaveCount(0);

    const stored = (await getRules()).find((r) => r.id === rule.id);
    expect(stored?.name).toBe(renamed);
    expect(stored?.priority).toBe(7);
    expect(stored?.on_error).toBe("CONTINUE");
    expect(stored?.is_active).toBe(true);
    expect(stored?.actions[0]?.action_type).toBe("notify.role");

    await page.reload();
    await expect(card(page, renamed)).toContainText("Priority #7");
    await expect(card(page, original)).toHaveCount(0);
  });

  test("Duplicate opens a copy of the rule, saved off, and leaves the original alone", async ({ page }) => {
    const name = `Copy me ${runId()}`;
    const rule = await createRule(name, { priority: 55 });
    await openPage(page);
    await page.getByRole("button", { name: `Duplicate rule ${name}` }).click();
    const builder = page.getByRole("dialog", { name: "Duplicate automation" });
    await expect(builder).toBeVisible();
    await expect(builder.getByRole("textbox", { name: "Name", exact: true })).toHaveValue(`${name} (copy)`);
    await expect(builder.getByRole("checkbox", { name: "Active" })).not.toBeChecked();
    await builder.getByRole("button", { name: "Create rule" }).click();
    await expect(builder).toHaveCount(0);
    await expect(card(page, `${name} (copy)`)).toBeVisible();
    await expect(card(page, `${name} (copy)`)).toContainText("Disabled");

    const rules = await getRules();
    const copy = rules.find((r) => r.name === `${name} (copy)`);
    expect(copy, "the copy exists").toBeTruthy();
    expect(copy?.id).not.toBe(rule.id);
    expect(copy?.is_active).toBe(false);
    expect(copy?.priority).toBe(55);
    expect(copy?.triggers).toEqual(["document.created"]);
    expect(copy?.actions[0]?.config).toMatchObject({ roles: ["OWNER"], title: `Fired: ${name}` });
    const stillThere = rules.find((r) => r.id === rule.id);
    expect(stillThere?.name).toBe(name);
    expect(stillThere?.is_active).toBe(true);

    await page.reload();
    await expect(card(page, `${name} (copy)`)).toContainText("Disabled");
    await expect(card(page, name)).toContainText("Active");
  });

  test("Delete asks first: Cancel keeps the rule, Delete Rule removes it for good", async ({ page }) => {
    const name = `Delete me ${runId()}`;
    const rule = await createRule(name);
    await openPage(page);
    await page.getByRole("button", { name: `Delete rule ${name}` }).click();
    const confirm = page.getByRole("alertdialog", { name: "Delete Automation Rule" });
    await expect(confirm).toBeVisible();
    await expect(confirm).toContainText(`delete "${name}"`);
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toHaveCount(0);
    await expect(card(page, name)).toBeVisible();
    expect(await byName(name)).toBeTruthy();

    await page.getByRole("button", { name: `Delete rule ${name}` }).click();
    const gone = page.waitForResponse((r) => r.url().includes(`/automation/rules/${rule.id}`) && r.request().method() === "DELETE");
    await confirm.getByRole("button", { name: "Delete Rule" }).click();
    expect((await gone).status()).toBe(204);
    await expect(card(page, name)).toHaveCount(0);
    expect(await byName(name)).toBeUndefined();
    expect((await api(customer.session, "GET", `${rulesUrl()}/${rule.id}`)).status).toBe(404);

    await page.reload();
    await expect(page.getByRole("button", { name: "Create New Rule" })).toBeVisible();
    await expect(card(page, name)).toHaveCount(0);
  });

  test("a viewer is shown 'Access restricted' and refused by the API; a contributor is refused changes", async ({ page, problems }) => {
    const name = `Guarded ${runId()}`;
    const rule = await createRule(name);

    // The server: a viewer cannot read, change, test or delete; a contributor can read but not change.
    problems.allowHttp(/\/automation\//, [403], "a viewer / contributor is refused the rule actions on purpose");
    for (const person of [viewer, member]) {
      const patch = await api(person.session, "PATCH", `${rulesUrl()}/${rule.id}`, { is_active: false });
      expect(patch.status, `${person.email} PATCH`).toBe(403);
      const del = await api(person.session, "DELETE", `${rulesUrl()}/${rule.id}`);
      expect(del.status, `${person.email} DELETE`).toBe(403);
      const dry = await api(person.session, "POST", `${rulesUrl()}/${rule.id}/test`, { work_item_id: sampleDocument });
      expect(dry.status, `${person.email} test`).toBe(403);
    }
    expect((await api(viewer.session, "GET", rulesUrl())).status).toBe(403);
    expect((await api(member.session, "GET", rulesUrl())).status).toBe(200);
    const unchanged = await byName(name);
    expect(unchanged?.is_active).toBe(true);

    // The page: the viewer is turned away.
    await signInAs(page, viewer.email);
    await page.goto(customer.ws("automation"));
    await expect(page.getByText("Access restricted")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("switch", { name: `Toggle rule ${name}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Delete rule ${name}` })).toHaveCount(0);
  });

  test("a contributor reads the rules but is offered nothing to change them with, as the server only lets an administrator (F-516)", async ({ page }) => {
    const name = `Admin only ${runId()}`;
    await createRule(name);
    await signInAs(page, member.email);
    await page.goto(customer.ws("automation"));
    const toggle = page.getByRole("switch", { name: `Toggle rule ${name}` });
    await expect(toggle).toBeVisible({ timeout: 30_000 });
    await expect(toggle, "the state is shown, read-only").toBeDisabled();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    for (const label of [`Test rule ${name}`, `Duplicate rule ${name}`, `Edit rule ${name}`, `Delete rule ${name}`]) {
      await expect(page.getByRole("button", { name: label }), label).toHaveCount(0);
    }
    await expect(page.getByRole("button", { name: /^Create (New Rule|your first rule)$/ })).toHaveCount(0);
    expect((await byName(name))?.is_active).toBe(true);
  });
});

/* ================================================================== 2. CLAUSE CHECKS */

/** Read straight from the database what the API does not return (a reviewer's verdict). */
function dbRows(sql: string): Array<Record<string, unknown>> {
  const python = process.env.E2E_PYTHON ?? "python3";
  const code = [
    "import json, sys",
    "from sqlalchemy import text",
    "from app.db.session import SessionLocal",
    "with SessionLocal() as db:",
    "    rows = [dict(r._mapping) for r in db.execute(text(sys.argv[1]))]",
    "print(json.dumps(rows, default=str))",
  ].join("\n");
  const out = execFileSync(python, ["-c", code, sql], { cwd: BACKEND_DIR, encoding: "utf8", timeout: 60_000 });
  const lines = out.trim().split("\n");
  return JSON.parse(lines[lines.length - 1] ?? "[]") as Array<Record<string, unknown>>;
}

const contract = (days: number): Buffer => buildPdf([[
  "SERVICES AGREEMENT", "between Contoso Retail and Acme Supplies Ltd",
  "1. Services. Acme shall provide maintenance services.",
  `2. Termination. Either party may terminate this Agreement by giving ${days} days' written notice.`,
  "3. Governing law. India."]]);

interface ReviewItem { readonly evaluation_id: string; readonly document_name: string | null; readonly sentence: string }

test.describe("Clause checks: it passes, it fails, wrong paragraph, test on a document", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);

  const SENTENCE = "The notice period for termination must be at least 30 days.";
  let customer: Customer;
  let check: { rule_id: string; node_key: string };
  let contractDocs: Array<{ id: string; name: string }> = [];

  const reviewsUrl = (): string => `/workspaces/${customer.wsId}/assertions/reviews`;
  const pending = async (): Promise<ReviewItem[]> => {
    const listed = await api<ReviewItem[]>(customer.session, "GET", `${reviewsUrl()}?limit=100`);
    expect(listed.status, listed.text.slice(0, 300)).toBe(200);
    return listed.body;
  };
  const verdictOf = (evaluationId: string): { reviewer_verdict: string | null; evidence: unknown } | undefined =>
    dbRows(`select reviewer_verdict, evidence from assertion_evaluations where id = '${evaluationId}'`)[0] as
      { reviewer_verdict: string | null; evidence: unknown } | undefined;

  const queueItem = (page: Page, name: string) =>
    page.locator("main article").filter({ hasText: name });

  async function openQueue(page: Page): Promise<void> {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("assertions"));
    await expect(page.getByRole("heading", { name: "Clauses to review" })).toBeVisible({ timeout: 30_000 });
  }

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    customer = await enterpriseCustomer("clause");
    const created = await api<{ rule_id: string; node_key: string }>(customer.session, "POST",
      `/workspaces/${customer.wsId}/assertions/clause-checks`, { name: "Notice at least 30 days" });
    expect(created.status, created.text).toBe(201);
    check = created.body;
    const saved = await api(customer.session, "PUT",
      `/workspaces/${customer.wsId}/assertions/rules/${check.rule_id}/nodes/${check.node_key}`,
      { node_key: check.node_key, sentence: SENTENCE, threshold: "0.8" });
    expect(saved.status, saved.text).toBe(200);
    // Four contracts that give too little notice: each lands in the review queue.
    contractDocs = [];
    for (const days of [15, 10, 12, 20]) {
      const name = `notice-${days}d-${runId()}`;
      const id = await uploadPdf(customer, name, contract(days));
      contractDocs.push({ id, name: `${name}` });
    }
    for (const doc of contractDocs) await processed(customer.session, customer.wsId, doc.id);
  });

  test("the queue lists the held clauses; 'It passes' records a PASS and takes the item off the queue", async ({ page }) => {
    await expect.poll(async () => (await pending()).filter((r) => (r.document_name ?? "").startsWith("notice-")).length,
      { timeout: 180_000, intervals: [3_000] }).toBe(4);
    const items = (await pending()).filter((r) => (r.document_name ?? "").startsWith("notice-"));
    const target = items.find((r) => (r.document_name ?? "").startsWith("notice-15d-"))!;

    await openQueue(page);
    await expect(page.getByText("4 waiting")).toBeVisible();
    const item = queueItem(page, target.document_name!);
    await expect(item).toContainText(SENTENCE);
    const resolved = page.waitForResponse((r) => r.url().includes(`/assertions/reviews/${target.evaluation_id}/resolve`) && r.request().method() === "POST");
    await item.getByRole("button", { name: "It passes" }).click();
    const response = await resolved;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toMatchObject({ reviewer_verdict: "PASS", corrected_quote: null });
    await expect(item).toHaveCount(0);
    await expect(page.getByText("3 waiting")).toBeVisible();

    expect((await pending()).some((r) => r.evaluation_id === target.evaluation_id)).toBe(false);
    expect(verdictOf(target.evaluation_id)?.reviewer_verdict).toBe("PASS");
    await page.reload();
    await expect(page.getByText("3 waiting")).toBeVisible();
    await expect(queueItem(page, target.document_name!)).toHaveCount(0);
  });

  test("'It fails' records a FAIL", async ({ page }) => {
    const target = (await pending()).find((r) => (r.document_name ?? "").startsWith("notice-10d-"))!;
    await openQueue(page);
    const item = queueItem(page, target.document_name!);
    const resolved = page.waitForResponse((r) => r.url().includes(`/assertions/reviews/${target.evaluation_id}/resolve`) && r.request().method() === "POST");
    await item.getByRole("button", { name: "It fails" }).click();
    expect((await resolved).request().postDataJSON()).toMatchObject({ reviewer_verdict: "FAIL" });
    await expect(item).toHaveCount(0);
    expect(verdictOf(target.evaluation_id)?.reviewer_verdict).toBe("FAIL");
    expect((await pending()).some((r) => r.evaluation_id === target.evaluation_id)).toBe(false);
  });

  test("'Wrong paragraph' asks for the right paragraph and a verdict, then teaches the engine", async ({ page }) => {
    const target = (await pending()).find((r) => (r.document_name ?? "").startsWith("notice-12d-"))!;
    const paragraph = "Either party may terminate this Agreement by giving 12 days' written notice.";
    const taughtBy = async (): Promise<string[]> => {
      const phrases = await api<Array<{ phrase: string; source: string }>>(customer.session, "GET", `/workspaces/${customer.wsId}/assertions/phrases`);
      expect(phrases.status, phrases.text.slice(0, 200)).toBe(200);
      return phrases.body.filter((p) => p.source === "REVIEWER").map((p) => p.phrase);
    };
    expect(await taughtBy()).toEqual([]);

    await openQueue(page);
    const item = queueItem(page, target.document_name!);
    await item.getByRole("button", { name: "Wrong paragraph" }).click();
    const box = item.getByRole("textbox", { name: /Paste or type the paragraph that should have been read/ });
    await expect(box).toBeVisible();
    // Without the paragraph there is nothing to decide with.
    await expect(item.getByRole("button", { name: "It passes" })).toBeDisabled();
    await expect(item.getByRole("button", { name: "It fails" })).toBeDisabled();
    // Cancel closes the box and nothing was recorded.
    await item.getByRole("button", { name: "Cancel correction" }).click();
    await expect(box).toHaveCount(0);
    expect(verdictOf(target.evaluation_id)?.reviewer_verdict).toBeNull();

    await item.getByRole("button", { name: "Wrong paragraph" }).click();
    await box.fill(paragraph);
    await expect(item.getByRole("button", { name: "It fails" })).toBeEnabled();
    const resolved = page.waitForResponse((r) => r.url().includes(`/assertions/reviews/${target.evaluation_id}/resolve`) && r.request().method() === "POST");
    await item.getByRole("button", { name: "It fails" }).click();
    const response = await resolved;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toMatchObject({ reviewer_verdict: "FAIL", corrected_quote: paragraph });
    await expect(item).toHaveCount(0);

    const stored = verdictOf(target.evaluation_id);
    expect(stored?.reviewer_verdict).toBe("FAIL");
    expect(JSON.stringify(stored?.evidence)).toContain(paragraph);
    expect(JSON.stringify(stored?.evidence)).toContain("REVIEWER");
    // The wording of that paragraph is now something retrieval looks for.
    expect((await taughtBy()).some((phrase) => phrase.includes("terminate"))).toBe(true);
  });

  test("a clause check's On/Off switch and Delete button change the check for real", async ({ page }) => {
    const name = `Throwaway check ${runId()}`;
    const made = await api<{ rule_id: string; node_key: string }>(customer.session, "POST",
      `/workspaces/${customer.wsId}/assertions/clause-checks`, { name });
    expect(made.status, made.text).toBe(201);
    const saved = await api(customer.session, "PUT",
      `/workspaces/${customer.wsId}/assertions/rules/${made.body.rule_id}/nodes/${made.body.node_key}`,
      { node_key: made.body.node_key, sentence: "Payment terms do not exceed Net 45.", threshold: "0.8" });
    expect(saved.status, saved.text).toBe(200);
    const stored = async (): Promise<{ is_active: boolean } | undefined> => {
      const listed = await api<Array<{ rule_id: string; is_active: boolean }>>(customer.session, "GET",
        `/workspaces/${customer.wsId}/assertions/clause-checks`);
      return listed.body.find((c) => c.rule_id === made.body.rule_id);
    };
    expect((await stored())?.is_active).toBe(true);

    await openQueue(page);
    const row = page.getByRole("region", { name: "Clause checks" }).getByRole("listitem").filter({ hasText: name });
    const toggle = row.getByRole("switch");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(toggle).toHaveText("Off");
    await expect.poll(async () => (await stored())?.is_active).toBe(false);
    await page.reload();
    await expect(row.getByRole("switch")).toHaveText("Off");
    await row.getByRole("switch").click();
    await expect(row.getByRole("switch")).toHaveText("On");
    await expect.poll(async () => (await stored())?.is_active).toBe(true);

    await row.getByRole("button", { name: `Delete ${name}` }).click();
    await expect(row).toHaveCount(0);
    await expect.poll(async () => await stored()).toBeUndefined();
    await page.reload();
    await expect(page.getByRole("region", { name: "Clause checks" })).not.toContainText(name);
  });

  test("the simulate endpoint behind 'Test on a document' answers for a document and writes nothing", async () => {
    const before = dbRows(`select count(*)::int as n from assertion_evaluations where workspace_id = '${customer.wsId}'`)[0]!.n;
    const result = await api<{ verdict: string; reason: string; evidence: unknown[] }>(customer.session, "POST",
      `/workspaces/${customer.wsId}/assertions/simulate`,
      { work_item_id: contractDocs[3]!.id, sentence: SENTENCE, threshold: "0.8000" });
    expect(result.status, result.text.slice(0, 400)).toBe(200);
    expect(["PASS", "FAIL", "UNDETERMINED"]).toContain(result.body.verdict);
    expect(dbRows(`select count(*)::int as n from assertion_evaluations where workspace_id = '${customer.wsId}'`)[0]!.n).toBe(before);
  });

  test("a clause's 'Edit clause' panel offers 'Test on a document', which reads a document without saving anything", async ({ page }) => {
    const evaluationsBefore = dbRows(`select count(*)::int as n from assertion_evaluations where workspace_id = '${customer.wsId}'`)[0]!.n;
    await openQueue(page);
    const panel = page.getByRole("region", { name: "Clause checks" });
    await expect(panel).toContainText("Notice at least 30 days");
    await panel.getByRole("button", { name: "Edit clause" }).click();
    const block = panel.getByRole("region", { name: "Check a clause" });
    await expect(block).toBeVisible();
    await expect(block.getByLabel("Assert that")).toHaveValue(SENTENCE);

    // The button the engine's "Test on a document" feature is reached by.
    const test = block.getByRole("button", { name: "Test on a document" });
    await expect(test, "the clause editor must offer 'Test on a document'").toBeVisible();
    await block.getByRole("combobox").selectOption({ index: 0 });
    const simulated = page.waitForResponse((r) => r.url().includes("/assertions/simulate") && r.request().method() === "POST");
    await test.click();
    expect((await simulated).status()).toBe(200);
    await expect(block).toContainText(/PASS|FAIL|UNDETERMINED/);
    expect(dbRows(`select count(*)::int as n from assertion_evaluations where workspace_id = '${customer.wsId}'`)[0]!.n).toBe(evaluationsBefore);
  });
});

/* ================================================================== 3. OBLIGATIONS */

interface ObligationView {
  readonly obligation: { readonly id: string; readonly title: string; readonly state: string };
  readonly events: Array<{ readonly kind: string; readonly detail: { readonly reason?: string } }>;
}
interface FeedRowView { readonly id: string; readonly label: string; readonly revoked_at: string | null; readonly use_count: number }

/** A calendar day `days` from today, as the API wants it (YYYY-MM-DD). */
function dayFromNow(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

test.describe("Obligations: waive with a reason, revoke a calendar feed", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  let customer: Customer;
  let viewer: { email: string; session: ApiSession };

  const obUrl = (id = ""): string => `/workspaces/${customer.wsId}/obligations${id ? `/${id}` : ""}`;
  const feedsUrl = (id = ""): string => `/workspaces/${customer.wsId}/calendar-feeds${id ? `/${id}` : ""}`;

  async function createObligation(title: string): Promise<string> {
    const made = await api<ObligationView>(customer.session, "POST", obUrl(), {
      kind: "NOTICE", title, rule: { kind: "FIXED", date: dayFromNow(45), roll: "NONE" },
    });
    expect(made.status, made.text.slice(0, 400)).toBe(201);
    return made.body.obligation.id;
  }
  const detail = async (id: string): Promise<ObligationView> => {
    const got = await api<ObligationView>(customer.session, "GET", obUrl(id));
    expect(got.status, got.text.slice(0, 300)).toBe(200);
    return got.body;
  };

  test.beforeAll(async () => {
    test.setTimeout(300_000);
    customer = await enterpriseCustomer("oblig");
    viewer = await addMember(customer, "oblig-viewer", "MEMBER", "VIEWER");
  });

  test("Waive needs a reason; with one the obligation is waived, with its reason in the history, and it stays waived", async ({ page, problems }) => {
    const title = `Send renewal notice ${runId()}`;
    const id = await createObligation(title);
    await signInAs(page, customer.email);
    await page.goto(customer.ws(`obligations/${id}`));
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible({ timeout: 30_000 });
    const actions = page.getByRole("region", { name: "Actions" });
    const waive = actions.getByRole("button", { name: "Waive", exact: true });
    const reason = actions.getByRole("textbox", { name: "Waiver reason" });

    // No reason, no waiver: the button stays off for nothing and for blanks.
    await expect(waive).toBeDisabled();
    await reason.fill("   ");
    await expect(waive).toBeDisabled();
    expect((await detail(id)).obligation.state).not.toBe("WAIVED");

    const why = "The customer cancelled the contract, so no notice is owed.";
    await reason.fill(why);
    await expect(waive).toBeEnabled();
    const waived = page.waitForResponse((r) => r.url().includes(`/obligations/${id}/waive`) && r.request().method() === "POST");
    await waive.click();
    const response = await waived;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toEqual({ reason: why });
    await expect(page.getByText("Waived", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("region", { name: "History" })).toContainText(why);
    // A closed obligation offers Reopen, not Waive.
    await expect(actions.getByRole("button", { name: "Reopen" })).toBeVisible();
    await expect(actions.getByRole("button", { name: "Waive", exact: true })).toHaveCount(0);

    const stored = await detail(id);
    expect(stored.obligation.state).toBe("WAIVED");
    expect(stored.events.find((e) => e.kind === "WAIVED")?.detail.reason).toBe(why);

    await page.reload();
    await expect(page.getByRole("region", { name: "History" })).toContainText(why);
    await expect(page.getByRole("region", { name: "Actions" }).getByRole("button", { name: "Reopen" })).toBeVisible();

    // The list files it under "Closed", not "Open".
    await page.goto(customer.ws("obligations"));
    await page.getByRole("button", { name: "Closed" }).click();
    await expect(page.getByRole("link", { name: title })).toBeVisible();
    await page.getByRole("button", { name: "Open", exact: true }).click();
    await expect(page.getByRole("link", { name: title })).toHaveCount(0);

    // The server also refuses a blank reason, and a second waiver.
    problems.allowHttp(/\/obligations\/.*\/waive/, "any", "the API refuses a blank reason and a second waiver on purpose");
    const other = await createObligation(`Blank reason ${runId()}`);
    const blank = await api(customer.session, "POST", obUrl(`${other}/waive`), { reason: "   " });
    expect([400, 422]).toContain(blank.status);
    expect((await detail(other)).obligation.state).not.toBe("WAIVED");
    const again = await api(customer.session, "POST", obUrl(`${id}/waive`), { reason: "again" });
    expect(again.status).toBe(409);
  });

  test("Reopen after a waiver puts the obligation back to work", async ({ page }) => {
    const title = `Waive then reopen ${runId()}`;
    const id = await createObligation(title);
    const done = await api(customer.session, "POST", obUrl(`${id}/waive`), { reason: "Not needed this year." });
    expect(done.status, done.text.slice(0, 300)).toBe(200);
    await signInAs(page, customer.email);
    await page.goto(customer.ws(`obligations/${id}`));
    await page.getByRole("region", { name: "Actions" }).getByRole("button", { name: "Reopen" }).click();
    await expect(page.getByRole("region", { name: "Actions" }).getByRole("button", { name: "Waive", exact: true })).toBeVisible();
    await expect.poll(async () => (await detail(id)).obligation.state).not.toBe("WAIVED");
  });

  test("a viewer sees no Waive button and the API refuses the viewer", async ({ page, problems }) => {
    const title = `Viewer cannot waive ${runId()}`;
    const id = await createObligation(title);
    await signInAs(page, viewer.email);
    await page.goto(customer.ws(`obligations/${id}`));
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Waive", exact: true })).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Waiver reason" })).toHaveCount(0);

    problems.allowHttp(/\/obligations\/.*\/waive/, [403], "a viewer may not waive");
    const refused = await api(viewer.session, "POST", obUrl(`${id}/waive`), { reason: "I would like to" });
    expect(refused.status).toBe(403);
    expect((await detail(id)).obligation.state).not.toBe("WAIVED");
  });

  test("Revoke on a calendar feed ends the link: it worked before, it is refused after", async ({ page }) => {
    const title = `Feed obligation ${runId()}`;
    await createObligation(title);
    const label = `Phone calendar ${runId()}`;
    await signInAs(page, customer.email);
    await page.goto(customer.ws("obligations"));
    await page.getByRole("tab", { name: "Calendar feeds" }).click();
    const form = page.getByRole("form", { name: "New calendar feed" });
    await form.getByLabel("Label").fill(label);
    await form.getByLabel("Covers").selectOption("ALL");
    const issued = page.waitForResponse((r) => r.url().includes("/calendar-feeds") && r.request().method() === "POST");
    await form.getByRole("button", { name: "Create feed link" }).click();
    expect((await issued).status()).toBe(201);

    // The link is shown once; read it off the page the way a person would copy it.
    const notice = page.getByRole("status").filter({ hasText: "shown only once" });
    await expect(notice).toBeVisible();
    const link = (await notice.locator("code").innerText()).trim();
    expect(link).toMatch(/\/public\/calendar-feeds\/[^/]+\.ics$/);

    // 1. The link serves the calendar.
    const before = await fetchOnce(link, { headers: { Accept: "text/calendar" } });
    const calendar = await before.text();
    expect(before.status).toBe(200);
    expect(calendar).toContain("BEGIN:VCALENDAR");
    expect(calendar).toContain(title);

    const row = page.getByRole("listitem").filter({ hasText: label });
    await expect(row).toBeVisible();
    await expect.poll(async () => {
      const listed = await api<{ items: FeedRowView[] }>(customer.session, "GET", feedsUrl());
      return listed.body.items.find((f) => f.label === label)?.use_count ?? 0;
    }).toBeGreaterThan(0);

    // 2. Revoke asks first. "No" leaves the feed alone.
    const question = page.getByRole("alertdialog");
    await row.getByRole("button", { name: "Revoke" }).click();
    await expect(question).toContainText(label);
    await question.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(question).toHaveCount(0);
    await expect(row.getByRole("button", { name: "Revoke" })).toBeVisible();
    expect((await fetchOnce(link, {})).status).toBe(200);

    // 3. "Yes" revokes it.
    const revoked = page.waitForResponse((r) => /\/calendar-feeds\/[0-9a-f-]+$/.test(r.url()) && r.request().method() === "DELETE");
    await row.getByRole("button", { name: "Revoke" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Revoke feed", exact: true }).click();
    expect((await revoked).status()).toBe(204);
    await expect(page.getByText("Feed revoked. Calendars subscribed to it stop updating.")).toBeVisible();
    await expect(row).toContainText("Revoked");
    await expect(row.getByRole("button", { name: "Revoke" })).toHaveCount(0);

    // 4. The old link is dead: the calendar app's next poll gets "not found", and no obligation leaks.
    const after = await fetchOnce(link, {});
    expect(after.status).toBe(404);
    expect(await after.text()).not.toContain(title);
    const listed = await api<{ items: FeedRowView[] }>(customer.session, "GET", feedsUrl());
    expect(listed.body.items.find((f) => f.label === label)?.revoked_at).toBeTruthy();

    // 5. After a reload the feed is still shown as revoked, and a new link is a different one.
    await page.reload();
    await page.getByRole("tab", { name: "Calendar feeds" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: label })).toContainText("Revoked");
    expect((await fetchOnce(link, {})).status).toBe(404);
  });

  test("a member revokes their own feed, and cannot revoke or even see someone else's", async ({ problems }) => {
    const mine = await api<{ feed: FeedRowView; token: string }>(viewer.session, "POST", feedsUrl(), { label: "Viewer feed", scope: "MINE", include_closed: true });
    expect(mine.status, mine.text.slice(0, 300)).toBe(201);
    const owners = await api<{ feed: FeedRowView; token: string }>(customer.session, "POST", feedsUrl(), { label: "Owner feed", scope: "ALL", include_closed: true });
    expect(owners.status, owners.text.slice(0, 300)).toBe(201);

    const seen = await api<{ items: FeedRowView[] }>(viewer.session, "GET", feedsUrl());
    expect(seen.body.items.map((f) => f.label)).toEqual(["Viewer feed"]);

    problems.allowHttp(/\/calendar-feeds\//, [404], "a member cannot revoke another member's feed");
    expect((await api(viewer.session, "DELETE", feedsUrl(owners.body.feed.id))).status).toBe(404);
    expect((await fetchOnce(`${API_BASE}/public/calendar-feeds/${owners.body.token}.ics`, {})).status).toBe(200);
    expect((await api(viewer.session, "DELETE", feedsUrl(mine.body.feed.id))).status).toBe(204);
    expect((await fetchOnce(`${API_BASE}/public/calendar-feeds/${mine.body.token}.ics`, {})).status).toBe(404);
  });
});

/* ================================================================== 4. EXTRACTION MEMORY */

interface MemTemplate { readonly id: string; readonly state: string; readonly document_type: string; readonly exemplar_documents: number; readonly fields: Array<{ field_path: string; corrections: number; confirmations: number }> }
interface MemRule { readonly id: string; readonly state: string; readonly field_path: string; readonly sentence: string }
interface MemTrial { readonly id: string; readonly template_id: string; readonly state: string; readonly decision_reason: string | null }
interface Verification { readonly id: string; readonly work_item_id: string; readonly status: string }

test.describe("Extraction memory: corrections teach it; Reset a layout, Retire a rule", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(420_000);

  const BANKS = ["GB11 TEST 0000 0000 0000 01", "GB11 TEST 0000 0000 0000 02", "GB11 TEST 0000 0000 0000 03",
    "GB11 TEST 0000 0000 0000 04", "GB11 TEST 0000 0000 0000 05"];
  let customer: Customer;
  let viewer: { email: string; session: ApiSession };
  const names: string[] = [];

  const memUrl = (sub: string): string => `/workspaces/${customer.wsId}/extraction-memory/${sub}`;
  const templates = async (as: ApiSession = customer.session): Promise<MemTemplate[]> => {
    const got = await api<MemTemplate[]>(as, "GET", memUrl("templates"));
    expect(got.status, got.text.slice(0, 300)).toBe(200);
    return got.body;
  };
  const rules = async (): Promise<MemRule[]> => {
    const got = await api<MemRule[]>(customer.session, "GET", memUrl("rules"));
    expect(got.status, got.text.slice(0, 300)).toBe(200);
    return got.body;
  };
  const trials = async (): Promise<MemTrial[]> => {
    const got = await api<MemTrial[]>(customer.session, "GET", memUrl("trials"));
    expect(got.status, got.text.slice(0, 300)).toBe(200);
    return got.body;
  };
  const mode = async (): Promise<string> => (await api<{ mode: string }>(customer.session, "GET", memUrl("settings"))).body.mode;

  /** The nightly learning pass (an operator script of the repo), for this workspace only. */
  function sweep(): void {
    const python = process.env.E2E_PYTHON ?? "python3";
    execFileSync(python, ["scripts/sweep_extraction_memory.py", "--apply", "--workspace", customer.wsId],
      { cwd: BACKEND_DIR, encoding: "utf8", timeout: 120_000 });
  }

  const disputedInvoice = (n: number): Buffer => buildPdf([
    DISPUTED_INVOICE_PAGE.map((line) => line.replace("INV-E2E-1002", `INV-MEM-${String(n).padStart(3, "0")}-${runId()}`)),
  ]);

  async function verificationFor(name: string): Promise<Verification> {
    let found: Verification | undefined;
    await expect.poll(async () => {
      const listed = await api<Array<Verification & { original_filename?: string }>>(customer.session, "GET",
        `/workspaces/${customer.wsId}/verifications?status=DISAGREED&limit=100`);
      found = listed.body.find((v) => v.original_filename === name);
      return Boolean(found);
    }, { timeout: 180_000, intervals: [3_000] }).toBe(true);
    return found as Verification;
  }

  test.beforeAll(async () => {
    test.setTimeout(600_000);
    customer = await enterpriseCustomer("memory");
    viewer = await addMember(customer, "memory-viewer", "MEMBER", "VIEWER");
    // Three agents read every document; where they disagree the field goes to a person.
    const enabled = await api(customer.session, "PUT", `/workspaces/${customer.wsId}/document-settings/`,
      { verification_enabled: true, verification_agents: 3 });
    expect(enabled.status, enabled.text.slice(0, 300)).toBe(200);
    // Five invoices of one layout that the model's reading disagrees on (its bank account).
    const uploaded: string[] = [];
    for (let n = 1; n <= 5; n += 1) {
      const filename = `memory-invoice-${n}-${runId()}.pdf`;
      uploaded.push(await uploadNamed(customer, filename, disputedInvoice(n)));
      names.push(filename);
    }
    for (const id of uploaded) await processed(customer.session, customer.wsId, id);
    // Three of the five are corrected through the API, with the same call the review hub makes: every scalar field
    // (no calibration model yet, so a person confirms them all) and the bank account changed by hand.
    for (const n of [2, 3, 4]) {
      const v = await verificationFor(names[n]!);
      const detail = await api<{ fields: Array<{ field_path: string; consensus_value: unknown }> }>(customer.session, "GET",
        `/workspaces/${customer.wsId}/verifications/${v.id}`);
      const values: Record<string, unknown> = {};
      for (const field of detail.body.fields) {
        if (field.consensus_value !== null && typeof field.consensus_value !== "object") values[field.field_path] = field.consensus_value;
      }
      values.vendor_bank_account = BANKS[n]!;
      const resolved = await api(customer.session, "POST", `/workspaces/${customer.wsId}/verifications/${v.id}/resolve`, { values });
      expect(resolved.status, resolved.text.slice(0, 400)).toBe(200);
    }
    // The other two are decided in the browser, in the first test.
  });

  test("a reviewer's corrections in the review hub become memory: a layout with its learned fields", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("verification"));
    await page.getByRole("tab", { name: "Extraction", exact: true }).click();
    const list = page.getByRole("list", { name: "Review items" });

    // Document 0: correct the bank account by hand.
    const first = list.getByRole("listitem").filter({ hasText: names[0]! }).filter({ hasText: "Agents disagreed" });
    await expect(first).toBeVisible({ timeout: 60_000 });
    await first.getByRole("button", { name: /Extracted fields disagree/ }).click();
    await first.getByRole("button", { name: "Edit" }).click();
    await first.getByRole("textbox", { name: "Value for vendor_bank_account" }).fill(BANKS[0]!);
    const sent = page.waitForResponse((r) => /\/verifications\/[^/]+\/resolve/.test(r.url()) && r.request().method() === "POST");
    await first.getByRole("button", { name: "Submit corrections" }).click();
    const response = await sent;
    expect(response.status()).toBe(200);
    const sentValues = (response.request().postDataJSON() as { values: Record<string, unknown> }).values;
    expect(sentValues.vendor_bank_account).toBe(BANKS[0]);
    expect(sentValues.vendor_name).toBe("Acme Industrial Supplies Ltd");
    await expect(first).toHaveCount(0);

    // Document 1: accept the reading as it is.
    const second = list.getByRole("listitem").filter({ hasText: names[1]! }).filter({ hasText: "Agents disagreed" });
    await second.getByRole("button", { name: /Extracted fields disagree/ }).click();
    await second.getByRole("button", { name: "Accept all" }).click();
    await expect(second).toHaveCount(0);

    // Memory has learned from all five: one layout, five reviewed documents, the field that was corrected.
    await expect.poll(async () => (await templates())[0]?.exemplar_documents ?? 0, { timeout: 60_000 }).toBe(5);
    const [layout] = await templates();
    expect(layout?.state).toBe("LEARNING");
    const bank = layout?.fields.find((f) => f.field_path === "vendor_bank_account");
    expect(bank?.corrections, "four of the five bank accounts were changed by a person").toBeGreaterThanOrEqual(4);
    expect((await templates()).length).toBe(1);

    await page.goto(customer.ws("extraction-memory"));
    await expect(page.getByRole("heading", { name: "Extraction memory", level: 1 })).toBeVisible({ timeout: 30_000 });
    const layoutRow = page.getByRole("region", { name: "Layouts" }).getByRole("row").filter({ hasText: "vendor_bank_account" });
    await expect(layoutRow).toBeVisible();
    await expect(layoutRow).toContainText("learning");
    // A layout still being learned has nothing to reset.
    await expect(layoutRow.getByRole("button", { name: "Reset" })).toHaveCount(0);
  });

  test("Automatic mode is chosen on the page; the nightly pass then starts a trial and learns anchor rules", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("extraction-memory"));
    const modes = page.getByRole("radiogroup", { name: "Extraction memory mode" });
    await expect(modes.getByRole("radio", { name: /^Shadow/ })).toHaveAttribute("aria-checked", "true", { timeout: 30_000 });
    const saved = page.waitForResponse((r) => r.url().includes("/extraction-memory/settings") && r.request().method() === "PUT");
    await modes.getByRole("radio", { name: /^Automatic/ }).click();
    expect((await saved).status()).toBe(200);
    await expect(modes.getByRole("radio", { name: /^Automatic/ })).toHaveAttribute("aria-checked", "true");
    expect(await mode()).toBe("AUTO");
    await page.reload();
    await expect(page.getByRole("radiogroup", { name: "Extraction memory mode" }).getByRole("radio", { name: /^Automatic/ }))
      .toHaveAttribute("aria-checked", "true");

    // Five reviewed documents of one layout: the nightly pass starts its trial and learns where each field sits.
    sweep();
    await expect.poll(async () => (await templates())[0]?.state).toBe("TRIAL");
    expect((await rules()).length, "the pass learned anchor rules").toBeGreaterThan(0);
    expect((await rules()).every((r) => r.state === "SHADOW")).toBe(true);
    expect((await trials()).map((t) => t.state)).toEqual(["RUNNING"]);

    await page.reload();
    const layoutRow = page.getByRole("region", { name: "Layouts" }).getByRole("row").filter({ hasText: "vendor_bank_account" });
    await expect(layoutRow).toContainText("trial");
    await expect(layoutRow.getByRole("button", { name: "Reset" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Anchor rules" }).getByRole("button", { name: "Retire" }).first()).toBeVisible();
  });

  test("Retire takes an anchor rule out of use; the page, the API and a reload agree; Return to shadow brings it back for watching", async ({ page }) => {
    const all = await rules();
    const unique = all.find((r) => all.filter((x) => x.sentence === r.sentence).length === 1);
    expect(unique, "a rule with a sentence of its own").toBeTruthy();
    const target = unique!;
    await signInAs(page, customer.email);
    await page.goto(customer.ws("extraction-memory"));
    const rulesList = page.getByRole("region", { name: "Anchor rules" });
    const row = rulesList.getByRole("listitem").filter({ hasText: target.sentence });
    await expect(row).toHaveCount(1, { timeout: 30_000 });
    await expect(row).toContainText("shadow");
    // A rule already in shadow has nothing to "return" to.
    await expect(row.getByRole("button", { name: "Return to shadow" })).toHaveCount(0);

    const others = all.filter((r) => r.id !== target.id).map((r) => `${r.id}:${r.state}`);
    const retired = page.waitForResponse((r) => r.url().includes(`/extraction-memory/rules/${target.id}`) && r.request().method() === "PATCH");
    await row.getByRole("button", { name: "Retire" }).click();
    const response = await retired;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toEqual({ action: "retire" });
    await expect(row).toContainText("retired");
    await expect(row.getByRole("button", { name: "Retire" })).toHaveCount(0);

    const after = await rules();
    expect(after.find((r) => r.id === target.id)?.state).toBe("RETIRED");
    // Only that rule changed.
    expect(after.filter((r) => r.id !== target.id).map((r) => `${r.id}:${r.state}`).sort()).toEqual(others.sort());

    await page.reload();
    const again = page.getByRole("region", { name: "Anchor rules" }).getByRole("listitem").filter({ hasText: target.sentence });
    await expect(again).toContainText("retired");
    await expect(again.getByRole("button", { name: "Retire" })).toHaveCount(0);

    await again.getByRole("button", { name: "Return to shadow" }).click();
    await expect(again).toContainText("shadow");
    await expect.poll(async () => (await rules()).find((r) => r.id === target.id)?.state).toBe("SHADOW");
  });

  test("Reset sends a layout back to learning: its trial is abandoned, what it learned is kept", async ({ page }) => {
    const [layout] = await templates();
    expect(layout?.state).toBe("TRIAL");
    const documentsBefore = layout!.exemplar_documents;
    const rulesBefore = (await rules()).length;
    await signInAs(page, customer.email);
    await page.goto(customer.ws("extraction-memory"));
    const row = page.getByRole("region", { name: "Layouts" }).getByRole("row").filter({ hasText: "vendor_bank_account" });
    await expect(row).toContainText("trial", { timeout: 30_000 });
    const reset = page.waitForResponse((r) => r.url().includes(`/extraction-memory/templates/${layout!.id}`) && r.request().method() === "PATCH");
    await row.getByRole("button", { name: "Reset" }).click();
    const response = await reset;
    expect(response.status()).toBe(200);
    expect(response.request().postDataJSON()).toEqual({ action: "reset" });
    await expect(row).toContainText("learning");
    await expect(row.getByRole("button", { name: "Reset" })).toHaveCount(0);

    const [after] = await templates();
    expect(after?.id).toBe(layout!.id);
    expect(after?.state).toBe("LEARNING");
    expect(after?.exemplar_documents).toBe(documentsBefore);
    expect((await rules()).length).toBe(rulesBefore);
    const trial = (await trials())[0];
    expect(trial?.state).toBe("ABANDONED");
    expect(trial?.decision_reason).toBe("reset by an administrator");

    await page.reload();
    const trialsSection = page.getByRole("region", { name: "Trials" });
    await expect(trialsSection).toContainText("abandoned");
    await expect(trialsSection).toContainText("reset by an administrator");
    await expect(page.getByRole("region", { name: "Layouts" }).getByRole("row").filter({ hasText: "vendor_bank_account" })).toContainText("learning");
  });

  test("a viewer can read the memory but has no Reset, Retire or mode buttons; the API refuses the viewer", async ({ page, problems }) => {
    // Put the layout back on trial so that there is something a viewer could press.
    sweep();
    await expect.poll(async () => (await templates())[0]?.state).toBe("TRIAL");
    const [layout] = await templates();
    const [rule] = await rules();

    await signInAs(page, viewer.email);
    await page.goto(customer.ws("extraction-memory"));
    await expect(page.getByRole("heading", { name: "Extraction memory", level: 1 })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("region", { name: "Layouts" }).getByRole("row").filter({ hasText: "vendor_bank_account" })).toContainText("trial");
    await expect(page.getByRole("button", { name: "Reset" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Retire" })).toHaveCount(0);
    await expect(page.getByRole("radio", { name: /^Shadow/ })).toBeDisabled();
    await expect(page.getByText("Only a workspace administrator can change the mode.")).toBeVisible();

    problems.allowHttp(/\/extraction-memory\//, [403], "a viewer may not change memory");
    expect((await api(viewer.session, "PATCH", memUrl(`templates/${layout!.id}`), { action: "reset" })).status).toBe(403);
    expect((await api(viewer.session, "PATCH", memUrl(`rules/${rule!.id}`), { action: "retire" })).status).toBe(403);
    expect((await api(viewer.session, "PUT", memUrl("settings"), { mode: "OFF" })).status).toBe(403);
    expect((await templates())[0]?.state).toBe("TRIAL");
    expect(await mode()).toBe("AUTO");
  });
});
