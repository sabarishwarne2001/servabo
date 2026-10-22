/**
 * WHAT THE PLAN LOCKS IN WORKFLOWS (Session J): triggers, recipes, the server, and the run itself.
 *
 * A Developer customer of its own (the plan is "bought" through the stand-in Dodo, as every journey does):
 *   1. the builder lists the GST and TruthMesh triggers as "Not in your plan", their checkboxes disabled; "Upgrade to use
 *      the trigger" opens the existing upgrade dialog, naming the feature and the plans that include it;
 *   2. the recipe gallery shows the GST recipe locked, with an "Upgrade to use the recipe" button that opens the same
 *      dialog; every other recipe is open exactly when the server says so;
 *   3. the server refuses to store a rule with such a trigger (422, in words) or such a step, and nothing is stored;
 *   4. the owner buys the GST Credit add-on at the stand-in's checkout page: the GST triggers and the GST recipe unlock
 *      (the recipe fills the builder and saves), TruthMesh stays locked;
 *   5. the plan is asked again when a rule RUNS: the add-on is cancelled and its grace ends; the stored GST rule is not
 *      announced by the hourly sweep any more, and a by-hand run of a stored rule with the reminder step fails in words
 *      ("... is not included in your plan any more") without sending anything.
 * Accessibility is scanned in both themes on the locked builder, the upgrade dialog and the locked gallery.
 *
 * Stood in: the gateway's hosted checkout page and its cancellation (the stand-in Dodo's) and the clock (the invoices are
 * aged in the database, as 115 does).
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { BACKEND_DIR, DODO_ORIGIN, GATEWAY, MAIL_DIR } from "../support/env";
import { gstin, gstr2b } from "../support/gst";
import { newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

const BUYER = gstin("27", "AAACG1234F");
const SUPPLIER = gstin("27", "AABCS5555K");
const REPORTED = gstin("27", "AABFR8841M");
const PERIOD = "2026-09";
const GST_TRIGGER = "Invoice waiting for its supplier";
const GST_RECIPE = "Remind a supplier whose invoice is missing from GSTR-2B";
const TRUTHMESH_TRIGGER = "TruthMesh conflict opened";
const FREE_RECIPE = "Hold invoices above ₹10 lakh for review";
const ORGANIZATION = "Locked Triggers Ltd";

let owner: Customer;
const documentOf: Record<string, string> = {};

interface CatalogTrigger { readonly key: string; readonly label: string; readonly available: boolean }
interface Recipe { readonly id: string; readonly title: string; readonly available: boolean; readonly locked_feature: string | null }

const rulesUrl = (): string => `/workspaces/${owner.wsId}/automation/rules`;
const catalog = async (): Promise<CatalogTrigger[]> =>
  (await api<{ triggers: CatalogTrigger[] }>(owner.session, "GET", `/workspaces/${owner.wsId}/automation/catalog`)).body.triggers;
const recipes = async (): Promise<Recipe[]> =>
  (await api<{ recipes: Recipe[] }>(owner.session, "GET", `/workspaces/${owner.wsId}/automation/recipes`)).body.recipes;
const ruleNames = async (): Promise<string[]> =>
  (await api<Array<{ name: string }>>(owner.session, "GET", rulesUrl())).body.map((rule) => rule.name);

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

/** Supplier reminders (they say "not in our GSTR-2B") that name this organization in the mail catcher. */
const remindersSent = (): number => {
  if (!fs.existsSync(MAIL_DIR)) return 0;
  return fs.readdirSync(MAIL_DIR).filter((name) => name.endsWith(".json"))
    .map((name) => (JSON.parse(fs.readFileSync(path.join(MAIL_DIR, name), "utf8")) as { raw: string }).raw.replace(/=\r?\n/g, ""))
    .filter((raw) => raw.includes(ORGANIZATION) && /not in our GSTR-2B/.test(raw)).length;
};

const addonState = async (): Promise<string | undefined> => {
  const session = await apiLogin(owner.email);
  const body = (await api<{ addons: Array<{ addon_key: string; state: string }> }>(session, "GET", `/organizations/${owner.orgId}/entitlements`)).body;
  return body.addons.find((a) => a.addon_key === "addon.gst_credit")?.state;
};

const gstRule = (name: string, triggers: string[], extra: Record<string, unknown> = {}) => ({
  name, priority: 100, triggers, condition_groups: [], groups_operator: "AND", else_actions: [], on_error: "HALT", is_active: true,
  actions: [{ action_type: "gst.remind_supplier", config: {} }], ...extra,
});

/**
 * The gateway sends the buyer back to the address the API was started with (FRONTEND_URL, port 3000 by default). When the
 * web app under test listens elsewhere (E2E_WEB_PORT), send that return trip to where the app really is.
 */
async function returnToThisApp(page: Page, appOrigin: string): Promise<void> {
  await page.route((url) => url.origin === DODO_ORIGIN && url.pathname.startsWith("/checkout/"), async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const response = await route.fetch({ maxRedirects: 0 });
    const location = response.headers()["location"];
    if (!location) {
      await route.fulfill({ response });
      return;
    }
    const back = new URL(location, DODO_ORIGIN);
    await route.fulfill({ response, headers: { ...response.headers(), location: `${appOrigin}${back.pathname}${back.search}` } });
  });
}

const openBuilder = async (page: Page) => {
  await page.goto(owner.ws("automation"));
  await page.getByRole("button", { name: "Create New Rule" }).click();
  const builder = page.getByRole("dialog", { name: /New automation/ });
  await expect(builder).toBeVisible();
  return builder;
};

/** A trigger's checkbox in the builder, found by its label. */
const triggerBox = (page: Page, label: string) =>
  page.getByRole("dialog", { name: /New automation/ }).getByRole("checkbox", { name: new RegExp(`^${label}`) });

const searchTriggers = async (page: Page, words: string): Promise<void> => {
  await page.getByRole("dialog", { name: /New automation/ }).getByLabel("Search triggers").fill(words);
};

const expectUpgradeDialog = async (page: Page, feature: string) => {
  const dialog = page.getByRole("alertdialog", { name: `${feature} isn't included in your plan` });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(`${feature} is included on`);
  return dialog;
};

const axe = async (page: Page, testInfo: import("@playwright/test").TestInfo, what: string): Promise<void> => {
  await settle(page, 300);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${what}: ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
    testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${what}: ${v.id} (${v.nodes.length})` });
  }
  expect(found, `${what} with serious or critical accessibility violations`).toEqual([]);
};

test.describe("What the plan locks in Workflows", () => {
  test.skip(GATEWAY !== "dodo", "the add-on is sold through the stand-in Dodo");
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(600_000);
    owner = await newCustomer("locks", ORGANIZATION);
    standIn("dodo-catalogue", null);
    standIn("subscribe", owner.orgSlug, "--plan", "developer", "--seats", "3");
    // Two purchase invoices that no supplier has reported: the GST clock has something to announce (figures are open on
    // every plan, so the statement imports on Developer).
    for (const [number, date, taxable] of [["B-2002", "2026-09-10", 500], ["C-3003", "2026-09-12", 700]] as const) {
      const half = Math.round(taxable * 0.09 * 100) / 100;
      const pdf = buildPdf([[
        "TAX INVOICE", "Vendor: Sahyadri Packaging", `Vendor GSTIN: ${SUPPLIER}`, `Bill To: ${ORGANIZATION}`, `Buyer GSTIN: ${BUYER}`,
        `Invoice Number: ${number}`, `Invoice Date: ${date}`, "Currency: INR", `Taxable value: ${taxable.toFixed(2)}`,
        `CGST: ${half.toFixed(2)}`, `SGST: ${half.toFixed(2)}`, `Total Amount Due: INR ${(taxable + half * 2).toFixed(2)}`,
      ]]);
      const form = new FormData();
      form.append("file", new Blob([new Uint8Array(pdf)], { type: "application/pdf" }), `${number}.pdf`);
      const sent = await api<{ id: string }>(owner.session, "POST", `/workspaces/${owner.wsId}/work-items`, form);
      expect(sent.status, sent.text.slice(0, 300)).toBe(201);
      documentOf[number] = sent.body.id;
    }
    const form = new FormData();
    form.append("file", new Blob([gstr2b(BUYER, PERIOD, [
      { gstin: REPORTED, name: "Rajput Hardware Stores", docs: [{ number: "X-9", date: "2026-09-18", taxable: 300 }] },
    ])], { type: "application/json" }), "GSTR2B_092026.json");
    const imported = await api(owner.session, "POST", `/workspaces/${owner.wsId}/gst/returns`, form);
    expect(imported.status, imported.text.slice(0, 300)).toBe(200);
    // The lists are locked on Developer (402), so the worker's settling is read from the database.
    await expect.poll(() => Object.fromEntries(
      sql(`select doc_number, status from gst_matches where workspace_id = '${owner.wsId}'`).map((r) => [String(r.doc_number), String(r.status)])),
    { timeout: 240_000, intervals: [3_000, 5_000] }).toMatchObject({ "B-2002": "WAITING_FOR_SUPPLIER", "C-3003": "WAITING_FOR_SUPPLIER" });
  });

  /* ------------------------------------------------------------------ 1. the builder */

  test("Developer: the GST and TruthMesh triggers are 'Not in your plan' with disabled checkboxes", async ({ page }) => {
    await signInAs(page, owner.email);
    const builder = await openBuilder(page);
    await searchTriggers(page, "GST");
    for (const label of ["GSTR-2B imported", GST_TRIGGER, "GST credit at risk of reversal"]) {
      const box = triggerBox(page, label);
      await expect(box, label).toBeDisabled();
      await expect(box.locator("xpath=ancestor::label")).toContainText("Not in your plan");
      await expect(builder.getByRole("button", { name: `Upgrade to use the trigger: ${label}` })).toBeVisible();
    }
    await expect(builder.getByRole("button", { name: `Upgrade to use the trigger: ${GST_TRIGGER}` }))
      .toContainText("Needs the GST Credit add-on or a plan that includes GST Credit.");
    await searchTriggers(page, "TruthMesh");
    await expect(triggerBox(page, TRUTHMESH_TRIGGER)).toBeDisabled();
    await expect(builder.getByRole("button", { name: `Upgrade to use the trigger: ${TRUTHMESH_TRIGGER}` })).toBeVisible();

    // A trigger the plan does include is open.
    await searchTriggers(page, "Document uploaded");
    await expect(triggerBox(page, "Document uploaded")).toBeEnabled();
    await expectHealthyPage(page);
  });

  test("'Upgrade to use the trigger' opens the existing upgrade dialog, naming the feature; 'Not now' leaves the builder as it was", async ({ page }) => {
    await signInAs(page, owner.email);
    const builder = await openBuilder(page);
    for (const [words, label, plans] of [
      ["GST", GST_TRIGGER, /Business and Enterprise plans/],
      ["TruthMesh", TRUTHMESH_TRIGGER, /plan/],
    ] as const) {
      await searchTriggers(page, words);
      await builder.getByRole("button", { name: `Upgrade to use the trigger: ${label}` }).click();
      const dialog = await expectUpgradeDialog(page, label);
      await expect(dialog).toContainText(plans);
      await expect(dialog.getByRole("button", { name: "View plans" })).toBeVisible();
      await dialog.getByRole("button", { name: "Not now" }).click();
      await expect(dialog).toHaveCount(0);
      await expect(builder).toBeVisible();
      await expect(triggerBox(page, label)).not.toBeChecked();
    }
    // "View plans" takes the owner to the billing page.
    await searchTriggers(page, "GST");
    await builder.getByRole("button", { name: `Upgrade to use the trigger: ${GST_TRIGGER}` }).click();
    await (await expectUpgradeDialog(page, GST_TRIGGER)).getByRole("button", { name: "View plans" }).click();
    await expect(page).toHaveURL(new RegExp(`${owner.org("billing").replace(/\//g, "\\/")}$`));
  });

  /* ------------------------------------------------------------------ 2. the recipes */

  test("the recipe gallery: the GST recipe is locked with an Upgrade button on the same dialog; the others are open as the server says", async ({ page }) => {
    const served = await recipes();
    expect(served.find((r) => r.title === GST_RECIPE)?.available).toBe(false);
    expect(served.find((r) => r.title === FREE_RECIPE)?.available).toBe(true);
    await signInAs(page, owner.email);
    await page.goto(owner.ws("automation"));
    await page.getByRole("button", { name: "Start from a recipe" }).click();
    const gallery = page.getByRole("dialog", { name: "Start from a recipe" });
    await expect(gallery).toBeVisible();
    for (const recipe of served) {
      const card = gallery.getByTestId(`recipe-${recipe.id}`);
      if (recipe.available) {
        await expect(card.getByRole("button", { name: `Use the recipe: ${recipe.title}`, exact: true }), recipe.title).toBeVisible();
        await expect(card.getByRole("button", { name: `Upgrade to use the recipe: ${recipe.title}`, exact: true })).toHaveCount(0);
      } else {
        await expect(card.getByRole("button", { name: `Upgrade to use the recipe: ${recipe.title}`, exact: true }), recipe.title).toBeVisible();
        await expect(card.getByRole("button", { name: `Use the recipe: ${recipe.title}`, exact: true })).toHaveCount(0);
      }
    }
    const locked = gallery.getByTestId("recipe-gst-chase-supplier");
    await expect(locked).toContainText("Needs the GST Credit add-on or a plan that includes GST Credit.");
    await locked.getByRole("button", { name: `Upgrade to use the recipe: ${GST_RECIPE}`, exact: true }).click();
    const dialog = await expectUpgradeDialog(page, GST_TRIGGER);
    await dialog.getByRole("button", { name: "Not now" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(gallery).toBeVisible();
    expect(await ruleNames()).toEqual([]);
    await expectHealthyPage(page);
  });

  /* ------------------------------------------------------------------ 3. the server */

  test("the server refuses to store a rule with a locked trigger or a locked step, in words, and stores nothing", async () => {
    const before = await ruleNames();
    const locked = await api<{ detail: Array<{ msg: string; loc: unknown[] }> }>(owner.session, "POST", rulesUrl(), gstRule("Locked GST trigger", ["gst.waiting_for_supplier"]));
    expect([402, 403, 422]).toContain(locked.status);
    expect(locked.status).toBe(422);
    const words = JSON.stringify(locked.body.detail);
    expect(words).toContain(`${GST_TRIGGER} is not included in your plan.`);
    expect(words).toContain("Remind a GST supplier is not included in your plan");

    const truthmesh = await api<{ detail: Array<{ msg: string }> }>(owner.session, "POST", rulesUrl(),
      gstRule("Locked TruthMesh trigger", ["truthmesh.conflict_opened"], { actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: "x", message: "y" } }] }));
    expect(truthmesh.status).toBe(422);
    expect(JSON.stringify(truthmesh.body.detail)).toContain(`${TRUTHMESH_TRIGGER} is not included in your plan.`);

    // An open trigger with a locked step is refused too.
    const step = await api(owner.session, "POST", rulesUrl(), gstRule("Locked GST step", ["document.created"]));
    expect(step.status).toBe(422);
    expect(step.text).toContain("Remind a GST supplier is not included in your plan");

    // Changing a stored rule onto a locked trigger is refused, and the rule keeps its trigger.
    const open = await api<{ id: string; triggers: string[] }>(owner.session, "POST", rulesUrl(), {
      name: "Open rule", priority: 100, triggers: ["document.created"], condition_groups: [], groups_operator: "AND", else_actions: [], on_error: "HALT",
      is_active: true, actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: "x", message: "y" } }],
    });
    expect(open.status, open.text.slice(0, 300)).toBe(201);
    const moved = await api(owner.session, "PATCH", `${rulesUrl()}/${open.body.id}`, { triggers: ["gst.waiting_for_supplier"] });
    expect(moved.status).toBe(422);
    const kept = await api<{ triggers: string[] }>(owner.session, "GET", `${rulesUrl()}/${open.body.id}`);
    expect(kept.body.triggers).toEqual(["document.created"]);

    expect(await ruleNames()).toEqual([...before, "Open rule"]);
  });

  /* ------------------------------------------------------------------ accessibility */

  for (const scheme of ["light", "dark"] as const) {
    test(`the locked builder, the upgrade dialog and the locked gallery have no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      const builder = await openBuilder(page);
      await searchTriggers(page, "GST");
      await expect(triggerBox(page, GST_TRIGGER)).toBeDisabled();
      await axe(page, testInfo, "the builder with locked triggers");
      await builder.getByRole("button", { name: `Upgrade to use the trigger: ${GST_TRIGGER}` }).click();
      const dialog = await expectUpgradeDialog(page, GST_TRIGGER);
      await axe(page, testInfo, "the upgrade dialog over the builder");
      await dialog.getByRole("button", { name: "Not now" }).click();
      await builder.getByRole("button", { name: "Close the flow builder" }).click();
      await expect(builder).toHaveCount(0);

      await page.getByRole("button", { name: "Start from a recipe" }).click();
      await expect(page.getByTestId("recipe-gst-chase-supplier").getByRole("button", { name: `Upgrade to use the recipe: ${GST_RECIPE}`, exact: true })).toBeVisible();
      await axe(page, testInfo, "the recipe gallery with locked recipes");
    });
  }

  /* ------------------------------------------------------------------ 4. the add-on */

  test("the owner buys GST Credit at the checkout page: the GST triggers and the GST recipe unlock, TruthMesh stays locked", async ({ page }) => {
    expect(await addonState()).toBe("NOT_GRANTED");
    await signInAs(page, owner.email);
    const checkout = await api<{ url: string }>(owner.session, "POST", `/organizations/${owner.orgId}/billing/addons/addon.gst_credit/checkout-session`, {});
    expect(checkout.status, checkout.text).toBe(201);
    await returnToThisApp(page, new URL(String(test.info().project.use.baseURL)).origin);
    await page.goto(checkout.body.url);
    await expect(page).toHaveURL(new RegExp(`^${DODO_ORIGIN.replace(/\./g, "\\.")}/checkout/`));
    await expect(page.locator("body")).toContainText("GST Credit × 1: USD 49.00 per month");
    await page.getByRole("button", { name: "Pay", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${owner.org("billing").replace(/\//g, "\\/")}\\?addon=success`), { timeout: 20_000 });
    await expect(page.getByTestId("addon-status-addon.gst_credit")).toHaveText("Active", { timeout: 60_000 });
    expect(await addonState()).toBe("ACTIVE");

    // The catalog the builder reads, then the builder itself.
    await expect.poll(async () => (await catalog()).filter((t) => t.key.startsWith("gst.")).every((t) => t.available)).toBe(true);
    expect((await catalog()).find((t) => t.key === "truthmesh.conflict_opened")?.available).toBe(false);
    const builder = await openBuilder(page);
    await searchTriggers(page, "GST");
    for (const label of ["GSTR-2B imported", GST_TRIGGER, "GST credit at risk of reversal"]) {
      await expect(triggerBox(page, label), label).toBeEnabled();
      await expect(builder.getByRole("button", { name: `Upgrade to use the trigger: ${label}` })).toHaveCount(0);
    }
    await expect(builder.getByText("Not in your plan")).toHaveCount(0);
    await searchTriggers(page, "TruthMesh");
    await expect(triggerBox(page, TRUTHMESH_TRIGGER)).toBeDisabled();
    await expect(builder.getByRole("button", { name: `Upgrade to use the trigger: ${TRUTHMESH_TRIGGER}` })).toBeVisible();
    await builder.getByRole("button", { name: "Close the flow builder" }).click();
    await expect(builder).toHaveCount(0);

    // The recipe unlocks, fills the builder and saves.
    await page.getByRole("button", { name: "Start from a recipe" }).click();
    const card = page.getByTestId("recipe-gst-chase-supplier");
    await expect(card.getByRole("button", { name: `Use the recipe: ${GST_RECIPE}`, exact: true })).toBeVisible();
    await expect(card.getByRole("button", { name: `Upgrade to use the recipe: ${GST_RECIPE}`, exact: true })).toHaveCount(0);
    expect((await recipes()).find((r) => r.id === "gst-chase-supplier")?.available).toBe(true);
    await card.getByRole("button", { name: `Use the recipe: ${GST_RECIPE}`, exact: true }).click();
    const filled = page.getByRole("dialog", { name: /New automation/ });
    await expect(filled).toBeVisible();
    await expect(triggerBox(page, GST_TRIGGER)).toBeChecked();
    await filled.getByRole("button", { name: "Create rule" }).click();
    await expect(filled).toHaveCount(0);
    const stored = await api<Array<{ name: string; triggers: string[]; actions: Array<{ action_type: string }> }>>(owner.session, "GET", rulesUrl());
    const rule = stored.body.find((r) => r.triggers?.includes("gst.waiting_for_supplier"));
    expect(rule?.actions.map((a) => a.action_type)).toEqual(["gst.remind_supplier"]);
    await expectHealthyPage(page);
  });

  /* ------------------------------------------------------------------ 5. the plan is asked again when a rule runs */

  test("while the add-on is active the hourly sweep announces an aged invoice and the stored rule runs", async () => {
    sql(`update work_items set created_at = created_at - interval '12 days' where id = '${documentOf["B-2002"]}'`);
    const limit = await api(owner.session, "PATCH", `/workspaces/${owner.wsId}/gst/settings`, { waiting_notice_days: 1 });
    expect(limit.status, limit.text).toBe(200);
    // A rule that can be run by hand, with the same step, stored while the add-on is active.
    const manual = await api(owner.session, "POST", rulesUrl(), gstRule("GST reminder by hand", ["manual"]));
    expect(manual.status, manual.text.slice(0, 300)).toBe(201);

    const swept = standIn("run-job", owner.orgSlug, "--job", "automation.sweep");
    expect(swept.status, JSON.stringify(swept)).toBe("SUCCEEDED");
    await expect.poll(async () => {
      const runs = await api<{ items: Array<{ work_item_id: string; status: string }> }>(owner.session, "GET", `/workspaces/${owner.wsId}/automation/executions?limit=100`);
      return runs.body.items.filter((e) => e.work_item_id === documentOf["B-2002"] && e.status === "COMPLETED").length;
    }, { timeout: 120_000, intervals: [2_000] }).toBe(1);
  });

  test("after the add-on is cancelled and its grace ends, the sweep no longer announces the stored GST rule's invoice", async () => {
    standIn("cancel-addon", owner.orgSlug, "--addon", "addon.gst_credit");
    await expect.poll(addonState, { timeout: 60_000 }).toBe("GRACE");
    standIn("addon-grace-ends", owner.orgSlug, "--addon", "addon.gst_credit");
    await expect.poll(addonState, { timeout: 60_000 }).toBe("LAPSED");

    // The stored rule is still there (a downgrade deletes nothing) ...
    const stored = await api<Array<{ name: string; triggers: string[] }>>(owner.session, "GET", rulesUrl());
    expect(stored.body.some((r) => r.triggers?.includes("gst.waiting_for_supplier"))).toBe(true);
    // ... a second invoice has now waited just as long ...
    sql(`update work_items set created_at = created_at - interval '12 days' where id = '${documentOf["C-3003"]}'`);
    const swept = standIn("run-job", owner.orgSlug, "--job", "automation.sweep");
    expect(swept.status, JSON.stringify(swept)).toBe("SUCCEEDED");
    await new Promise((resolve) => setTimeout(resolve, 8_000));
    const runs = await api<{ items: Array<{ work_item_id: string }> }>(owner.session, "GET", `/workspaces/${owner.wsId}/automation/executions?limit=100`);
    // ... and is not announced, because the organization's plan no longer includes GST Credit.
    expect(runs.body.items.filter((e) => e.work_item_id === documentOf["C-3003"])).toHaveLength(0);
    expect(remindersSent(), "nothing was sent").toBe(0);
  });

  test("a by-hand run of the stored rule fails in words, the builder shows the trigger locked again, and nothing is sent", async ({ page }) => {
    const rules = await api<Array<{ id: string; name: string }>>(owner.session, "GET", rulesUrl());
    const manual = rules.body.find((r) => r.name === "GST reminder by hand")!;
    const run = await api(owner.session, "POST", `${rulesUrl()}/${manual.id}/run`, { work_item_id: documentOf["C-3003"] });
    expect(run.status, run.text).toBe(202);
    let failure = "";
    await expect.poll(async () => {
      const runs = await api<{ items: Array<{ id: string; rule_id: string; status: string; error: string | null }> }>(owner.session, "GET", `/workspaces/${owner.wsId}/automation/executions?rule_id=${manual.id}&limit=10`);
      const mine = runs.body.items[0];
      failure = `${mine?.status ?? "none"}|${mine?.error ?? ""}`;
      return mine?.status ?? "none";
    }, { timeout: 120_000, intervals: [1_000, 2_000] }).toBe("FAILED");
    expect(failure).toContain("Remind a GST supplier is not included in your plan any more.");
    expect(remindersSent(), "nothing was sent").toBe(0);

    // Run history says it in words.
    await signInAs(page, owner.email);
    await page.goto(owner.ws("automation/timeline"));
    await expect(page.getByRole("heading", { name: "Run history", level: 1 })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("main")).toContainText("GST reminder by hand", { timeout: 30_000 });
    const chain = page.locator("main").getByRole("button", { name: /chain [0-9a-f]{8}/ }).first();
    await chain.click();
    await expect(page.locator("li[id^='execution-']").filter({ hasText: "GST reminder by hand" }))
      .toContainText("Remind a GST supplier is not included in your plan any more.");

    // And the builder is locked again for new rules.
    const builder = await openBuilder(page);
    await searchTriggers(page, "GST");
    await expect(triggerBox(page, GST_TRIGGER)).toBeDisabled();
    await expect(builder.getByRole("button", { name: `Upgrade to use the trigger: ${GST_TRIGGER}` })).toBeVisible();
    const again = await api(owner.session, "POST", rulesUrl(), gstRule("After the add-on ended", ["gst.waiting_for_supplier"]));
    expect(again.status).toBe(422);
    expect(await ruleNames()).not.toContain("After the add-on ended");
  });
});
