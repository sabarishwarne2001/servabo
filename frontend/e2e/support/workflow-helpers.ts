/**
 * Shared helpers for the Workspace Automation (Workflows) browser specs 109-113 (Session J).
 *
 * Each spec runs on a customer of its own (newCustomer) so nothing shared changes. The helpers set up
 * through the real API, wait for the worker, read what the engine did, and run the accessibility scan
 * the way spec 108 does (serious and critical violations fail, the rest are listed as annotations).
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page, type TestInfo } from "@playwright/test";

import { api, fetchOnce, type ApiSession } from "./api";
import { API_BASE, BACKEND_DIR, runId } from "./env";
import { newCustomer, standIn, type Customer } from "./journey";
import { buildPdf } from "./sample-docs";

/** A customer of its own on the Enterprise plan (every trigger, action and recipe is open). */
export async function enterpriseCustomer(label: string): Promise<Customer> {
  const customer = await newCustomer(label, `${label} Ltd`);
  standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "5");
  return customer;
}

export const rulesUrl = (c: Customer): string => `/workspaces/${c.wsId}/automation/rules`;

export interface RuleRow {
  readonly id: string;
  readonly name: string;
  readonly is_active: boolean;
  readonly priority: number;
  readonly max_runs_per_hour?: number | null;
  readonly cooldown_hours?: number | null;
  readonly triggers?: string[];
  readonly condition_groups?: Array<{ conditions: Array<{ field: string; operator: string; value: unknown; currency?: string | null }> }>;
  readonly actions: Array<{ action_type: string; config: Record<string, unknown> }>;
}

export async function listRules(c: Customer, session: ApiSession = c.session): Promise<RuleRow[]> {
  const listed = await api<RuleRow[]>(session, "GET", rulesUrl(c));
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body;
}

export async function ruleNamed(c: Customer, name: string): Promise<RuleRow | undefined> {
  return (await listRules(c)).find((rule) => rule.name === name);
}

/** Create a rule through the API in the flow shape the builder saves. */
export async function createRuleViaApi(c: Customer, body: Record<string, unknown>): Promise<RuleRow> {
  const created = await api<RuleRow>(c.session, "POST", rulesUrl(c), {
    priority: 100,
    triggers: ["document.completed"],
    condition_groups: [],
    groups_operator: "AND",
    actions: [],
    else_actions: [],
    on_error: "CONTINUE",
    is_active: true,
    ...body,
  });
  expect(created.status, created.text.slice(0, 500)).toBe(201);
  return created.body;
}

export interface ExecutionRow {
  readonly id: string;
  readonly rule_id: string;
  readonly work_item_id: string | null;
  readonly status: string;
  readonly actions_executed: number;
  readonly correlation_id: string;
  readonly error?: string | null;
  readonly details?: Record<string, unknown>;
}

export async function executionsOf(c: Customer, query: string): Promise<ExecutionRow[]> {
  const listed = await api<{ items: ExecutionRow[] }>(c.session, "GET", `/workspaces/${c.wsId}/automation/executions?${query}&limit=200`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
}

/** A one-page PDF with exactly these text lines, uploaded as the customer; returns the document id. */
export async function uploadLines(c: Customer, label: string, lines: readonly string[], session: ApiSession = c.session): Promise<string> {
  const form = new FormData();
  const bytes = buildPdf([[...lines, `Reference: ${label}-${runId()}`]]);
  form.append("file", new Blob([new Uint8Array(bytes)], { type: "application/pdf" }), `${label}-${runId()}.pdf`);
  const response = await fetchOnce(`${API_BASE}/workspaces/${c.wsId}/work-items`, {
    method: "POST", headers: { Authorization: `Bearer ${session.accessToken}` }, body: form,
  });
  expect(response.status, await response.clone().text()).toBe(201);
  return String(((await response.json()) as { id: string }).id);
}

/** An invoice that reads as: INR, this vendor, this total, this invoice date. */
export function invoiceLines(options: { number: string; total: string; invoiceDate?: string; vendor?: string; due?: string }): string[] {
  return [
    "INVOICE",
    `Vendor: ${options.vendor ?? "Sahyadri Packaging Pvt Ltd"}`,
    "Bill To: Konkan Traders Pvt Ltd",
    `Invoice Number: ${options.number}`,
    ...(options.invoiceDate ? [`Invoice Date: ${options.invoiceDate}`] : []),
    ...(options.due ? [`Due Date: ${options.due}`] : []),
    "Currency: INR",
    `Total Amount Due: ${options.total} INR`,
  ];
}

const TERMINAL = /^(COMPLETED|FAILED|NEEDS_REVIEW|REVIEW|DONE|ERROR)/;

/** Wait until the worker has finished reading a document (its fields are in). */
export async function processed(c: Customer, id: string, session: ApiSession = c.session): Promise<Record<string, unknown>> {
  let item: Record<string, unknown> = {};
  await expect.poll(async () => {
    const got = await api<Record<string, unknown>>(session, "GET", `/workspaces/${c.wsId}/work-items/${id}`);
    item = got.body;
    return String(got.body.status ?? "");
  }, { timeout: 180_000, intervals: [1_500], message: `document ${id} was not processed` }).toMatch(TERMINAL);
  return item;
}

/** Wait until at least `count` runs of the rule exist and none is queued or running. */
export async function runsSettled(c: Customer, ruleId: string, count: number): Promise<ExecutionRow[]> {
  let rows: ExecutionRow[] = [];
  await expect.poll(async () => {
    rows = await executionsOf(c, `rule_id=${ruleId}`);
    const open = rows.filter((row) => /^(QUEUED|RUNNING)$/.test(row.status)).length;
    return open === 0 ? rows.length : -1;
  }, { timeout: 180_000, intervals: [1_500], message: `expected ${count} runs of the rule` }).toBeGreaterThanOrEqual(count);
  return rows;
}

export const builderOf = (page: Page): Locator => page.getByRole("dialog", { name: /New automation|Edit automation/i });

/** The rule card (an <article>) with this name on the Automation page. */
export const cardOf = (page: Page, name: string): Locator =>
  page.locator("main article").filter({ has: page.getByRole("heading", { name, exact: true }) });

/**
 * Light and dark accessibility scan of what is on the page now. `where` names the screen in the message.
 * Serious and critical violations fail; the rest are annotations (spec 108's pattern).
 */
export async function expectAccessible(page: Page, testInfo: TestInfo, where: string, scope?: string): Promise<void> {
  const found: string[] = [];
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.waitForTimeout(250);
    let axe = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
    if (scope) axe = axe.include(scope);
    const results = await axe.analyze();
    for (const v of results.violations) {
      const line = `${where} (${scheme}) ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`;
      if (v.impact === "serious" || v.impact === "critical") found.push(line);
      else testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${where} (${scheme}): ${v.id} (${v.nodes.length})` });
    }
  }
  await page.emulateMedia({ colorScheme: "light" });
  expect(found, `${where}: serious or critical accessibility violations`).toEqual([]);
}

/** A small PDF on disk (for the upload tray). */
export function pdfOnDisk(label: string, lines: readonly string[]): string {
  const dir = path.join(os.tmpdir(), "servabo-e2e-workflows");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${label}-${runId()}.pdf`);
  fs.writeFileSync(file, buildPdf([[...lines]]));
  return file;
}

function python(): string {
  return process.env.E2E_PYTHON ?? "python3";
}

/** Read straight from the database what the API does not return (an encrypted column, a stored message body). */
export function dbRows(sql: string): Array<Record<string, unknown>> {
  const code = [
    "import json, sys",
    "from sqlalchemy import text",
    "from app.db.session import SessionLocal",
    "with SessionLocal() as db:",
    "    rows = [dict(r._mapping) for r in db.execute(text(sys.argv[1]))]",
    "print(json.dumps(rows, default=str))",
  ].join("\n");
  const out = execFileSync(python(), ["-c", code, sql], { cwd: BACKEND_DIR, encoding: "utf8", timeout: 60_000 });
  const lines = out.trim().split("\n");
  return JSON.parse(lines[lines.length - 1] ?? "[]") as Array<Record<string, unknown>>;
}

/**
 * Register a Slack channel through the product's own `register_chat_endpoint` (the host check, the encryption of the URL, the
 * masking), with ONE step stood in: the DNS look-up of hooks.slack.com, which a sandbox without outside DNS cannot do.
 * The API route runs the same function after that look-up; its refusal of a non-Slack address is tested through the API.
 */
export function registerSlackChannel(c: Customer, url: string, description: string): string {
  const code = [
    "import json, sys, uuid",
    "from app.db.session import SessionLocal",
    "from app.services import webhook_service as w",
    "w._preflight_check_url = lambda url: None",
    "with SessionLocal() as db:",
    "    endpoint, _secret = w.register_chat_endpoint(db, organization_id=uuid.UUID(sys.argv[1]), kind='SLACK', url=sys.argv[2],",
    "        created_by_user_id=uuid.UUID(sys.argv[3]), description=sys.argv[4])",
    "    db.commit()",
    "    print(json.dumps({'id': str(endpoint.id)}))",
  ].join("\n");
  const userId = String((c.session.me as { id?: string }).id ?? "");
  const out = execFileSync(python(), ["-c", code, c.orgId, url, userId, description], { cwd: BACKEND_DIR, encoding: "utf8", timeout: 60_000 });
  const lines = out.trim().split("\n");
  return String((JSON.parse(lines[lines.length - 1] ?? "{}") as { id?: string }).id);
}
