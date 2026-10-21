/**
 * A GST RULE THAT REMINDS A SUPPLIER (Session J): "Invoice waiting for its supplier" -> "Remind a GST supplier".
 *
 * A Business customer of its own (GST Credit is part of the plan) has two purchase invoices that its suppliers have not
 * reported in their GSTR-2B:
 *   B-2002 from Sahyadri Packaging, whose invoice carries an email address (Helm learns it as the supplier's contact);
 *   C-3003 from Deccan Plastics, for which no email address is known anywhere.
 * The owner builds the rule in the browser. The hourly job (`automation.sweep`, played here by the stand-in's run-job)
 * announces each invoice that has waited longer than the workspace's limit, and the rule runs for each:
 *   - Sahyadri: the reminder goes to the known contact's address, to nobody else;
 *   - Deccan: nothing is sent, and the run says why in words.
 * Run history shows both outcomes in words. A second sweep announces nothing again and sends nothing again.
 *
 * Stood in: the clock. An invoice that was entered today has not "waited" yet, so the set-up ages the two uploaded
 * documents by twelve days in the database (and shortens the workspace's limit to one day), which is what time would do.
 * The mail goes to the tests' own catcher (support/smtp-sink.mjs).
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { BACKEND_DIR, MAIL_DIR, runId } from "../support/env";
import { gstin, gstr2b } from "../support/gst";
import { newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { waitForMail } from "../support/mail";
import { buildPdf } from "../support/sample-docs";

const BUYER = gstin("27", "AAACG1234F");
const KNOWN = gstin("27", "AABCS5555K");
const UNKNOWN = gstin("29", "AAGCD7777P");
const REPORTED = gstin("27", "AABFR8841M");
const PERIOD = "2026-09";
// Set per run in beforeAll: the mail catcher is shared, so the organization and the contact must be this run's own.
let ORGANIZATION = "";
let CONTACT = "";
const RULE = "Remind suppliers who have not reported";

interface Invoice { readonly vendor: string; readonly gstin: string; readonly number: string; readonly date: string; readonly taxable: number; readonly hasEmail?: boolean }
const INVOICES: readonly Invoice[] = [
  { vendor: "Sahyadri Packaging", gstin: KNOWN, number: "A-1001", date: "2026-09-05", taxable: 1000, hasEmail: true },
  { vendor: "Sahyadri Packaging", gstin: KNOWN, number: "B-2002", date: "2026-09-10", taxable: 500, hasEmail: true },
  { vendor: "Deccan Plastics", gstin: UNKNOWN, number: "C-3003", date: "2026-09-12", taxable: 700 },
];

let owner: Customer;
const documentOf: Record<string, string> = {};
let startedAt = 0;
let taxIdAfterHelmSync = "";

/** Run one statement against the test database and return its rows (the clock's stand-in: it ages documents). */
function sql(statement: string): Array<Record<string, unknown>> {
  const python = process.env.E2E_PYTHON ?? "python3";
  const code = [
    "import json, sys",
    "from sqlalchemy import text",
    "from app.db.session import SessionLocal",
    "with SessionLocal() as db:",
    "    result = db.execute(text(sys.argv[1]))",
    "    rows = [dict(r._mapping) for r in result] if result.returns_rows else []",
    "    db.commit()",
    "print(json.dumps(rows, default=str))",
  ].join("\n");
  const out = execFileSync(python, ["-c", code, statement], { cwd: BACKEND_DIR, encoding: "utf8", timeout: 60_000 });
  const lines = out.trim().split("\n");
  return JSON.parse(lines[lines.length - 1] ?? "[]") as Array<Record<string, unknown>>;
}

const pdf = (invoice: Invoice): Buffer => {
  const half = Math.round(invoice.taxable * 0.09 * 100) / 100;
  const total = (invoice.taxable + half * 2).toFixed(2);
  return buildPdf([[
    "TAX INVOICE", `Vendor: ${invoice.vendor}`, `Vendor GSTIN: ${invoice.gstin}`,
    ...(invoice.hasEmail ? [`Vendor Email: ${CONTACT}`] : []),
    `Bill To: ${ORGANIZATION}`, `Buyer GSTIN: ${BUYER}`, `Invoice Number: ${invoice.number}`, `Invoice Date: ${invoice.date}`,
    "Currency: INR", `Taxable value: ${invoice.taxable.toFixed(2)}`, `CGST: ${half.toFixed(2)}`, `SGST: ${half.toFixed(2)}`,
    `Total Amount Due: INR ${total}`,
  ]]);
};

const statement = (): string =>
  gstr2b(BUYER, PERIOD, [
    { gstin: KNOWN, name: "Sahyadri Packaging", docs: [{ number: "A-1001", date: "2026-09-05", taxable: 1000 }] },
    { gstin: REPORTED, name: "Rajput Hardware Stores", docs: [{ number: "X-9", date: "2026-09-18", taxable: 300 }] },
  ]);

interface Execution { readonly id: string; readonly work_item_id: string; readonly correlation_id: string; readonly status: string; readonly rule_id: string }
const executions = async (): Promise<Execution[]> => {
  const listed = await api<{ items: Execution[] }>(owner.session, "GET", `/workspaces/${owner.wsId}/automation/executions?limit=100`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
};
const outcomeOf = async (execution: Execution): Promise<string> => {
  const nodes = await api<Array<{ action_type: string | null; status: string; outcome: string | null }>>(
    owner.session, "GET", `/workspaces/${owner.wsId}/automation/executions/${execution.id}/nodes`);
  expect(nodes.status, nodes.text.slice(0, 300)).toBe(200);
  const step = nodes.body.find((node) => node.action_type === "gst.remind_supplier");
  return `${step?.status ?? "no step"}: ${step?.outcome ?? ""}`;
};
const forDocument = async (invoice: string): Promise<Execution[]> =>
  (await executions()).filter((execution) => execution.work_item_id === documentOf[invoice]);

/** Every supplier reminder the catcher holds for this organization (they name it and say "not in our GSTR-2B") since the test began. */
function reminderMails(): Array<{ to: string[]; text: string }> {
  if (!fs.existsSync(MAIL_DIR)) return [];
  return fs.readdirSync(MAIL_DIR).filter((name) => name.endsWith(".json")).sort()
    .map((name) => JSON.parse(fs.readFileSync(path.join(MAIL_DIR, name), "utf8")) as { to: string[]; receivedAt: string; raw: string })
    .filter((mail) => Date.parse(mail.receivedAt) >= startedAt)
    .map((mail) => ({ to: mail.to, text: mail.raw.replace(/=\r?\n/g, "") }))     // undo quoted-printable soft line breaks
    .filter((mail) => mail.text.includes(ORGANIZATION) && /not in our GSTR-2B/.test(mail.text));
}

const sweep = (): Record<string, unknown> => {
  const outcome = standIn("run-job", owner.orgSlug, "--job", "automation.sweep");
  expect(outcome.status, JSON.stringify(outcome)).toBe("SUCCEEDED");
  return outcome;
};

const openHistory = async (page: Page): Promise<void> => {
  await signInAs(page, owner.email);
  await page.goto(owner.ws("automation/timeline"));
  await expect(page.getByRole("heading", { name: "Run history", level: 1 })).toBeVisible({ timeout: 30_000 });
};

test.describe("A rule that reminds a GST supplier", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(600_000);
    startedAt = Date.now() - 1_000;
    const stamp = runId();
    ORGANIZATION = `GST Reminder Traders ${stamp} Ltd`;
    CONTACT = `accounts-${stamp}@sahyadri-packaging.example.com`;
    owner = await newCustomer("gstremind", ORGANIZATION);
    standIn("subscribe", owner.orgSlug, "--plan", "business", "--seats", "4");
    for (const invoice of INVOICES) {
      const form = new FormData();
      form.append("file", new Blob([new Uint8Array(pdf(invoice))], { type: "application/pdf" }), `${invoice.number}.pdf`);
      const sent = await api<{ id: string }>(owner.session, "POST", `/workspaces/${owner.wsId}/work-items`, form);
      expect(sent.status, sent.text.slice(0, 300)).toBe(201);
      documentOf[invoice.number] = sent.body.id;
    }
    const form = new FormData();
    form.append("file", new Blob([statement()], { type: "application/json" }), "GSTR2B_092026.json");
    const imported = await api(owner.session, "POST", `/workspaces/${owner.wsId}/gst/returns`, form);
    expect(imported.status, imported.text.slice(0, 300)).toBe(200);
    // The worker reads the invoices and the books settle: two are waiting for their supplier.
    await expect.poll(async () => {
      const session = await apiLogin(owner.email);
      const rows = await api<{ items: Array<{ number: string; status: string }> }>(session, "GET", `/workspaces/${owner.wsId}/gst/records?limit=100`);
      return Object.fromEntries(rows.body.items.map((row) => [row.number, row.status]));
    }, { timeout: 420_000, intervals: [3_000, 5_000] }).toMatchObject({
      "A-1001": "MATCHED", "B-2002": "WAITING_FOR_SUPPLIER", "C-3003": "WAITING_FOR_SUPPLIER",
    });
    // Helm learns the supplier's contact from the invoice.
    const book = await api<{ id: string }>(owner.session, "POST", `/organizations/${owner.orgId}/helm/books`, { workspace_id: owner.wsId });
    expect(book.status, book.text.slice(0, 300)).toBe(201);
    const planned = await api(owner.session, "POST", `/organizations/${owner.orgId}/helm/books/${book.body.id}/plan`, {});
    expect(planned.status, planned.text.slice(0, 300)).toBeLessThan(300);
    const people = await api<{ counterparties: Array<{ name: string; contact_email: string | null }> }>(
      owner.session, "GET", `/organizations/${owner.orgId}/helm/books/${book.body.id}/counterparties`);
    expect(people.status, people.text.slice(0, 300)).toBe(200);
    const contacts = Object.fromEntries(people.body.counterparties.map((c) => [c.name, c.contact_email]));
    expect(contacts["Sahyadri Packaging"], JSON.stringify(contacts)).toBe(CONTACT);
    expect(contacts["Deccan Plastics"] ?? null).toBeNull();
    // Nothing is written by hand: Helm's own sync records the supplier's GSTIN (F-545), which is how the reminder finds its contact.
    const rows = sql(`select display_name, tax_id from helm_counterparties where organization_id = '${owner.orgId}'`);
    taxIdAfterHelmSync = String(rows.find((r) => r.display_name === "Sahyadri Packaging")?.tax_id ?? "");

    // The clock: the workspace's limit is one day, and the invoices were entered twelve days ago.
    const limit = await api(owner.session, "PATCH", `/workspaces/${owner.wsId}/gst/settings`, { waiting_notice_days: 1 });
    expect(limit.status, limit.text).toBe(200);
    sql(`update work_items set created_at = created_at - interval '12 days' where workspace_id = '${owner.wsId}'`);
  });

  // F-545: Helm's sync did not record the supplier's GSTIN and the reminder looks a contact up by it, so no supplier was ever "known".
  test("Helm's sync records the supplier's GSTIN, so that a known contact can be found", async () => {
    expect(taxIdAfterHelmSync).toBe(KNOWN);
  });

  test("the owner builds the rule in the browser: an unlocked GST trigger and the reminder step", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.ws("automation"));
    await page.getByRole("button", { name: "Create New Rule" }).click();
    const builder = page.getByRole("dialog", { name: /New automation/ });
    await expect(builder).toBeVisible();
    await builder.getByRole("textbox", { name: "Name", exact: true }).fill(RULE);
    // The plan includes GST Credit: the trigger is open (no badge, no upgrade button).
    const trigger = builder.getByRole("checkbox", { name: /^Invoice waiting for its supplier/ });
    await expect(trigger).toBeEnabled();
    await expect(builder.getByRole("button", { name: "Upgrade to use the trigger: Invoice waiting for its supplier" })).toHaveCount(0);
    await trigger.check();
    await builder.getByTestId("flow-node-actions").click();
    await builder.getByRole("combobox", { name: "Add an action" }).first().selectOption("gst.remind_supplier");
    await expect(builder.getByText("Remind a GST supplier").first()).toBeVisible();
    await builder.getByRole("button", { name: "Create rule" }).click();
    await expect(builder).toHaveCount(0);
    await expect(page.locator("main article").filter({ has: page.getByRole("heading", { name: RULE, exact: true }) })).toBeVisible();

    const rules = await api<Array<{ name: string; triggers?: string[]; is_active: boolean; actions: Array<{ action_type: string }> }>>(
      owner.session, "GET", `/workspaces/${owner.wsId}/automation/rules`);
    const made = rules.body.find((rule) => rule.name === RULE);
    expect(made?.triggers).toEqual(["gst.waiting_for_supplier"]);
    expect(made?.actions.map((a) => a.action_type)).toEqual(["gst.remind_supplier"]);
    expect(made?.is_active).toBe(true);
    await expectHealthyPage(page);
  });

  test("the hourly sweep announces both invoices; the known contact is reminded, the unknown one is refused in words", async () => {
    expect(await executions(), "nothing has run before the sweep").toHaveLength(0);
    const swept = sweep();
    expect(JSON.stringify(swept)).toContain("waiting");

    await expect.poll(async () => (await forDocument("B-2002")).length + (await forDocument("C-3003")).length,
      { timeout: 120_000, intervals: [2_000] }).toBe(2);
    const known = (await forDocument("B-2002"))[0]!;
    const unknown = (await forDocument("C-3003"))[0]!;
    await expect.poll(async () => (await executions()).filter((e) => /QUEUED|RUNNING/.test(e.status)).length,
      { timeout: 120_000, intervals: [2_000] }).toBe(0);
    expect(await outcomeOf(known)).toBe("COMPLETED: reminder sent to the supplier's known contact (1 invoices)");
    expect(await outcomeOf(unknown)).toBe("COMPLETED: not sent: no email contact is known for this supplier");
    expect((await forDocument("A-1001")), "a reported invoice is not announced").toHaveLength(0);
  });

  test("the reminder reached the known contact's address and no other; the unknown supplier was sent nothing", async () => {
    const mail = await waitForMail(CONTACT, /B-2002/, startedAt);
    expect(mail.to).toEqual([CONTACT]);
    expect(mail.text).toContain(ORGANIZATION);
    expect(mail.text).toContain("Sahyadri Packaging");
    expect(mail.text).not.toContain("C-3003");        // the other supplier's invoice is not in this supplier's letter
    const all = reminderMails();
    expect(all, "exactly one reminder left the building").toHaveLength(1);
    expect(all[0]?.to).toEqual([CONTACT]);
    expect(all.some((m) => m.text.includes("Deccan Plastics") || m.text.includes("C-3003"))).toBe(false);
  });

  test("Run history shows both outcomes in words", async ({ page }) => {
    await openHistory(page);
    for (const [invoice, words] of [
      ["B-2002", "reminder sent to the supplier's known contact (1 invoices)"],
      ["C-3003", "not sent: no email contact is known for this supplier"],
    ] as const) {
      const chain = (await forDocument(invoice))[0]!.correlation_id.slice(0, 8);
      const row = page.locator("main").getByRole("button", { name: new RegExp(`chain ${chain}`) });
      await expect(row).toBeVisible({ timeout: 30_000 });
      await row.click();
      const step = page.locator("li[id^='execution-']").filter({ hasText: RULE });
      await step.getByRole("button", { name: "Show steps" }).first().click();
      await expect(step.getByRole("list", { name: "Steps of this run" })).toContainText(words);
      await row.click();
    }
    await expectHealthyPage(page);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`Run history with the steps open has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await openHistory(page);
      const chain = (await forDocument("C-3003"))[0]!.correlation_id.slice(0, 8);
      const row = page.locator("main").getByRole("button", { name: new RegExp(`chain ${chain}`) });
      await row.click();
      await page.locator("li[id^='execution-']").filter({ hasText: RULE }).getByRole("button", { name: "Show steps" }).first().click();
      await expect(page.getByRole("list", { name: "Steps of this run" })).toContainText("not sent: no email contact is known");
      await settle(page);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
        testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${v.id} (${v.nodes.length})` });
      }
      expect(found, "Run history with serious or critical accessibility violations").toEqual([]);
    });
  }

  test("a second sweep announces nothing again and sends nothing again", async () => {
    const before = (await executions()).length;
    expect(before).toBe(2);
    sweep();
    sweep();
    // Give the worker time to run anything the sweeps announced, then count.
    await new Promise((resolve) => setTimeout(resolve, 8_000));
    expect((await executions()).length, "no new run").toBe(2);
    expect(reminderMails(), "no second letter").toHaveLength(1);
    expect((await forDocument("B-2002"))).toHaveLength(1);
  });
});
