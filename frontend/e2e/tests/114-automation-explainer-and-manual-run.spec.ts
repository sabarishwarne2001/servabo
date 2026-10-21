/**
 * "WHY DIDN'T MY RULE RUN?" AND "RUN BY HAND" (Session J): the Automation tab on a document.
 *
 * A new Enterprise customer of its own (so nothing shared changes) makes four rules and uploads one invoice that the
 * worker really processes:
 *   - "Met": runs when a document is processed and the total is above 100          -> the invoice meets it, so it runs;
 *   - "Missed": the same trigger, but the total must be above 9,999,999             -> its trigger fires, its condition fails;
 *   - "Off": a rule that is switched off                                            -> says it is switched off;
 *   - "By hand": the "Run by hand on one document" trigger                          -> not triggered until a person runs it.
 * The document's Automation tab must say each of those in words, show the failing check with the document's own value
 * ("Show the checks"), and let an administrator run the manual rule: "Run now" queues a run that Run history lists for this
 * document, and the explainer then says it ran. A viewer is refused by the server (403) and the tab says so politely.
 *
 * Accessibility is scanned in both themes on the tab with its rows open and the run-by-hand form showing.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, type ApiSession } from "../support/api";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

const STAMP = runId();
const RULE = {
  met: `Met ${STAMP}`,
  missed: `Missed ${STAMP}`,
  off: `Off ${STAMP}`,
  byHand: `By hand ${STAMP}`,
};
const TOTAL = "4200.00";

let owner: Customer;
let viewer: { email: string; session: ApiSession };
let documentId = "";
const ruleIds: Record<keyof typeof RULE, string> = { met: "", missed: "", off: "", byHand: "" };

const rulesUrl = (): string => `/workspaces/${owner.wsId}/automation/rules`;

async function makeRule(name: string, extra: Record<string, unknown>): Promise<string> {
  const created = await api<{ id: string }>(owner.session, "POST", rulesUrl(), {
    name,
    priority: 100,
    triggers: ["document.ready"],
    condition_groups: [],
    groups_operator: "AND",
    actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: `Fired: ${name}`, message: "A document was processed." } }],
    else_actions: [],
    on_error: "HALT",
    is_active: true,
    ...extra,
  });
  expect(created.status, created.text.slice(0, 400)).toBe(201);
  return created.body.id;
}

const total = (operator: string, value: string) => [
  { logic_operator: "AND", conditions: [{ field: "total_amount", operator, value }] },
];

interface Explained {
  readonly rules: Array<{ rule_name: string; outcome: string; verdict: string }>;
}
const explained = async (session: ApiSession, name: string): Promise<{ outcome: string; verdict: string } | undefined> => {
  const result = await api<Explained>(session, "GET", `/workspaces/${owner.wsId}/automation/documents/${documentId}/explain`);
  expect(result.status, result.text.slice(0, 300)).toBe(200);
  return result.body.rules.find((rule) => rule.rule_name === name);
};

const executionsOf = async (ruleId: string): Promise<Array<{ id: string; work_item_id: string; correlation_id: string; status: string }>> => {
  const listed = await api<{ items: Array<{ id: string; work_item_id: string; correlation_id: string; status: string }> }>(
    owner.session, "GET", `/workspaces/${owner.wsId}/automation/executions?rule_id=${ruleId}&limit=100`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
};

const documentPage = async (page: Page, email: string): Promise<void> => {
  await signInAs(page, email);
  await page.goto(owner.ws(`work-items/${documentId}`));
  await page.getByRole("button", { name: "Automation", exact: true }).click();
};

const row = (page: Page, name: string) =>
  page.getByRole("region", { name: "Automation on this document" }).getByTestId("explain-rule").filter({ has: page.getByRole("heading", { name, exact: true }) });

test.describe("Why didn't my rule run? and Run by hand", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    owner = await newCustomer("explain", "Explainer Traders Ltd");
    standIn("subscribe", owner.orgSlug, "--plan", "enterprise", "--seats", "4");
    viewer = await addMember(owner, "explain-viewer", "MEMBER", "VIEWER");

    // The rules exist BEFORE the invoice arrives: a rule is run by what happens after it is made.
    ruleIds.met = await makeRule(RULE.met, { condition_groups: total("GREATER_THAN", "100") });
    ruleIds.missed = await makeRule(RULE.missed, { condition_groups: total("GREATER_THAN", "9999999") });
    ruleIds.off = await makeRule(RULE.off, { is_active: false });
    ruleIds.byHand = await makeRule(RULE.byHand, { triggers: ["manual"] });

    const dir = path.join(os.tmpdir(), "servabo-e2e-journeys");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `explain-${STAMP}.pdf`);
    fs.writeFileSync(file, buildPdf([[
      "TAX INVOICE", `Invoice Number: INV-EXPLAIN-${STAMP}`, "Vendor: Acme Industrial Supplies Ltd",
      "Currency: USD", `Total Amount Due: ${TOTAL} USD`,
    ]]));
    const form = new FormData();
    form.append("file", new Blob([fs.readFileSync(file)], { type: "application/pdf" }), path.basename(file));
    const uploaded = await api<{ id: string }>(owner.session, "POST", `/workspaces/${owner.wsId}/work-items`, form);
    expect(uploaded.status, uploaded.text).toBe(201);
    documentId = uploaded.body.id;

    // The worker processes it and the "Met" rule runs: that is the moment the explainer has something to say.
    await expect.poll(async () => (await executionsOf(ruleIds.met)).filter((e) => e.work_item_id === documentId).length,
      { timeout: 180_000, intervals: [2_000], message: "the rule that this invoice meets never ran" }).toBeGreaterThan(0);
  });

  test("the first row says the rule ran, the second says its conditions were not met and shows the failing check", async ({ page }) => {
    await documentPage(page, owner.email);
    const section = page.getByRole("region", { name: "Automation on this document" });
    await expect(section).toBeVisible({ timeout: 30_000 });
    await expect(section.getByTestId("explain-rule")).toHaveCount(4);

    const met = row(page, RULE.met);
    await expect(met).toContainText("Ran");
    await expect(met).toContainText("It ran on this document and took 1 step.");

    const missed = row(page, RULE.missed);
    await expect(missed).toContainText("Conditions not met");
    await expect(missed).toContainText("Its trigger fired, but the conditions were not met.");
    // The checks are folded away until asked for, then they name the document's own value next to what the rule wanted.
    await expect(missed.getByRole("list", { name: `Checks for ${RULE.missed}` })).toHaveCount(0);
    await missed.getByRole("button", { name: "Show the checks" }).click();
    const checks = missed.getByRole("list", { name: `Checks for ${RULE.missed}` });
    await expect(checks).toBeVisible();
    await expect(checks).toContainText("✗");
    await expect(checks).toContainText(/4,?200/);
    await expect(missed.getByRole("button", { name: "Hide the checks" })).toBeVisible();

    // The rule that passes shows a tick for its check, with the same value.
    await met.getByRole("button", { name: "Show the checks" }).click();
    const passing = met.getByRole("list", { name: `Checks for ${RULE.met}` });
    await expect(passing).toContainText("✓");
    await expect(passing).toContainText(/4,?200/);

    // The server's words and the page's words agree.
    const server = await explained(owner.session, RULE.missed);
    expect(server?.outcome).toBe("conditions_not_met");
    expect(server?.verdict).toContain("Its trigger fired, but the conditions were not met.");
    await expectHealthyPage(page);
  });

  test("a switched-off rule says it is switched off, and a by-hand rule says it has not been run", async ({ page }) => {
    await documentPage(page, owner.email);
    const off = row(page, RULE.off);
    await expect(off).toContainText("Switched off");
    await expect(off).toContainText("This rule is switched off.");

    const byHand = row(page, RULE.byHand);
    await expect(byHand).toContainText("Not triggered");
    await expect(byHand).toContainText("When: Run by hand on one document");
    await expect(byHand).toContainText("Its trigger has not fired for this document");
    // Nothing ran for it, and nothing but a person can make it.
    expect((await executionsOf(ruleIds.byHand)).filter((e) => e.work_item_id === documentId)).toHaveLength(0);
    expect((await executionsOf(ruleIds.off)).filter((e) => e.work_item_id === documentId)).toHaveLength(0);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the tab has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await documentPage(page, owner.email);
      await expect(row(page, RULE.missed)).toBeVisible({ timeout: 30_000 });
      await row(page, RULE.missed).getByRole("button", { name: "Show the checks" }).click();
      await expect(page.getByLabel("Run a rule on this document")).toBeVisible();
      await settle(page);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
      for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
        testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${v.id} (${v.nodes.length})` });
      }
      expect(found, "the document's Automation tab with serious or critical accessibility violations").toEqual([]);
    });
  }

  test("Run a rule on this document: only the by-hand rule is offered; Run now queues a run that Run history lists, and the explainer then says it ran", async ({ page }) => {
    await documentPage(page, owner.email);
    const chooser = page.getByLabel("Run a rule on this document");
    await expect(chooser).toBeVisible({ timeout: 30_000 });
    // Only a switched-on rule with the by-hand trigger is offered (not "Met", not "Off").
    await expect(chooser.locator("option")).toHaveText(["Choose a rule…", RULE.byHand]);
    const runNow = page.getByRole("button", { name: "Run now" });
    await expect(runNow).toBeDisabled();
    await chooser.selectOption({ label: RULE.byHand });
    await expect(runNow).toBeEnabled();

    const queued = page.waitForResponse((r) => r.url().includes(`/automation/rules/${ruleIds.byHand}/run`) && r.request().method() === "POST");
    await runNow.click();
    const response = await queued;
    expect(response.status()).toBe(202);
    expect(((await response.json()) as { work_item_id: string }).work_item_id).toBe(documentId);
    await expect(page.getByText("Queued. It appears in Run history within a few seconds.")).toBeVisible();
    await expect(chooser).toHaveValue("");

    // The worker runs it: the run is listed for this document and this rule.
    let chain = "";
    await expect.poll(async () => {
      const mine = (await executionsOf(ruleIds.byHand)).filter((e) => e.work_item_id === documentId);
      chain = mine[0]?.correlation_id ?? "";
      return mine.length;
    }, { timeout: 120_000, intervals: [1_000, 2_000], message: "the by-hand run never appeared" }).toBe(1);

    // Run history shows it, with this rule's name and a way back to the document.
    await page.goto(owner.ws("automation/timeline"));
    const chainRow = page.locator("main").getByRole("button", { name: new RegExp(`chain ${chain.slice(0, 8)}`) });
    await expect(chainRow).toBeVisible({ timeout: 30_000 });
    await chainRow.click();
    await expect(chainRow).toHaveAttribute("aria-expanded", "true");
    const step = page.locator(`li[id^="execution-"]`).filter({ hasText: RULE.byHand });
    await expect(step).toBeVisible();
    await expect(step.getByRole("link", { name: "Open the document" })).toHaveAttribute("href", new RegExp(`/work-items/${documentId}$`));
    await step.getByRole("link", { name: "Open the document" }).click();
    await expect(page).toHaveURL(new RegExp(`/work-items/${documentId}$`));

    // And the explainer on that document now says it ran.
    await page.getByRole("button", { name: "Automation", exact: true }).click();
    const byHand = row(page, RULE.byHand);
    await expect(byHand).toContainText("Ran", { timeout: 30_000 });
    await expect(byHand).toContainText("It ran on this document and took 1 step.");
    expect((await explained(owner.session, RULE.byHand))?.outcome).toBe("ran");
    await expectHealthyPage(page);
  });

  test("the server refuses a run of a rule that has no by-hand trigger", async () => {
    const refused = await api(owner.session, "POST", `/workspaces/${owner.wsId}/automation/rules/${ruleIds.met}/run`, { work_item_id: documentId });
    expect(refused.status).toBe(409);
    expect(refused.text).toContain("not set to run by hand");
    const switchedOff = await api(owner.session, "POST", `/workspaces/${owner.wsId}/automation/rules/${ruleIds.off}/run`, { work_item_id: documentId });
    expect(switchedOff.status).toBe(409);
  });

  test("a viewer: the server refuses the explainer (403) and the tab says so politely, with nothing to run", async ({ page, problems }) => {
    problems.allowHttp(/\/automation\/documents\/[^/]+\/explain$/, [403], "a viewer may not see how the automation treats a document");
    const refused = await api(viewer.session, "GET", `/workspaces/${owner.wsId}/automation/documents/${documentId}/explain`);
    expect(refused.status).toBe(403);
    const cannotRun = await api(viewer.session, "POST", `/workspaces/${owner.wsId}/automation/rules/${ruleIds.byHand}/run`, { work_item_id: documentId });
    expect(cannotRun.status).toBe(403);

    await signInAs(page, viewer.email);
    await page.goto(owner.ws(`work-items/${documentId}`));
    await page.getByRole("button", { name: "Automation", exact: true }).click();
    await expect(page.getByText("Only people who can edit documents here can see how the automation rules treat this one.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Automation on this document" })).toHaveCount(0);
    await expect(page.getByLabel("Run a rule on this document")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Run now" })).toHaveCount(0);
    await expectHealthyPage(page);
  });
});
