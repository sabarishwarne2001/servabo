/**
 * AUTOMATION THAT STAYS SAFE WHEN MANY DOCUMENTS ARRIVE: THE HOURLY LIMIT AND THE PAUSE SWITCH (Session J).
 *
 * The owner builds a rule in the browser: when a document has been read, put the tag "seen-by-rule" on it, and "At most
 * this many runs an hour" = 2 (Advanced tab). Four documents arrive together. What is proved, in the browser and through
 * the API:
 *
 *   - two runs did the work and two were HELD BACK, not lost: Run history, filtered to "Skipped", lists them as "Skipped —
 *     over the limit" with the reason in words (limit of 2 an hour), and the other two documents carry no tag;
 *   - the rule's card says "2 held back by the limit";
 *   - the owner got ONE notice, "Automation held back: <rule>", although two runs were held back (a notice at most
 *     once a day), on the Notifications page, with the unread badge on the bell;
 *   - "Pause all automations" asks first (a dialog of the product's own, never a browser one); once confirmed, the amber
 *     banner shows, every rule card says "Paused", and a document that arrives is a run "Skipped — paused" (no tag);
 *   - "Resume automations" lifts it; with the limit raised in the builder, the next document runs and is tagged.
 *
 * Accessibility is scanned in both themes on the builder's Advanced tab, the filtered Run history, the paused page, and
 * the pause dialog. Stood in: the model that reads the documents (support/llm-mock.mjs); the engine is the real one.
 */
import type { Page } from "@playwright/test";

import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { signInAs, type Customer } from "../support/journey";
import {
  builderOf, cardOf, dbRows, enterpriseCustomer, executionsOf, expectAccessible, invoiceLines, listRules, processed, runsSettled, uploadLines,
  type ExecutionRow,
} from "../support/workflow-helpers";

const RULE = "Tag every invoice";
const TAG = "seen-by-rule";

let customer: Customer;
let ruleId = "";
const documentIds: string[] = [];

/** The tags on a document, read from the database (the document's API answer does not list them). */
const tagsOf = async (id: string): Promise<string[]> =>
  dbRows(`select tag from work_item_tags where work_item_id = '${id}'`).map((row) => String(row.tag));

const uploadInvoice = async (label: string): Promise<string> => {
  const id = await uploadLines(customer, label, invoiceLines({ number: `${label.toUpperCase()}-1`, total: "1,000.00" }));
  documentIds.push(id);
  return id;
};

const openAutomation = async (page: Page): Promise<void> => {
  await page.goto(customer.ws("automation"));
  await expect(page.getByRole("button", { name: "Create New Rule" })).toBeVisible({ timeout: 30_000 });
  await expect(cardOf(page, RULE)).toBeVisible();
};

const pausedNow = async (): Promise<boolean> =>
  (await api<{ paused: boolean }>(customer.session, "GET", `/workspaces/${customer.wsId}/automation/pause`)).body.paused;

test.describe("Automation: the hourly limit and the pause switch", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);

  test.beforeAll(async () => {
    test.setTimeout(240_000);
    customer = await enterpriseCustomer("volume");
  });

  test("the owner builds the rule with a limit of 2 runs an hour on the Advanced tab", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await page.getByRole("button", { name: "Create New Rule" }).click();
    const builder = builderOf(page);
    await builder.getByRole("textbox", { name: "Name", exact: true }).fill(RULE);
    await builder.getByTestId("flow-node-trigger").click();
    await builder.getByRole("checkbox", { name: /^Document pipeline completed/ }).check();
    await builder.getByTestId("flow-node-actions").click();
    await builder.getByRole("combobox", { name: "Add an action" }).first().selectOption("document.tag");
    const tags = builder.getByRole("textbox", { name: "Tags to add" });
    await tags.fill(TAG);
    await tags.press("Enter");

    await builder.getByRole("tab", { name: "Advanced" }).click();
    const limit = builder.getByRole("spinbutton", { name: "At most this many runs an hour" });
    await expect(limit).toHaveValue("");
    await expect(limit).toHaveAttribute("placeholder", "200");          // the workspace default, shown when empty
    await limit.fill("2");
    await expect(builder.getByRole("spinbutton", { name: "Run at most once per document every (hours)" })).toBeVisible();
    await expect(builder.getByLabel("Rule status")).toContainText("No blocking issues");
    await expectAccessible(page, testInfo, "builder, Advanced tab", '[role="dialog"]');

    await builder.getByRole("button", { name: "Create rule" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    await expect(cardOf(page, RULE)).toContainText("Up to 2 runs an hour");
    const rule = (await listRules(customer)).find((r) => r.name === RULE)!;
    ruleId = rule.id;
    expect(rule.max_runs_per_hour).toBe(2);
    expect(rule.actions[0]!.action_type).toBe("document.tag");
  });

  test("four documents arrive together: two runs do the work, two are held back and nothing is lost", async () => {
    for (const label of ["one", "two", "three", "four"]) await uploadInvoice(label);
    for (const id of documentIds) await processed(customer, id);
    const runs = await runsSettled(customer, ruleId, 4);
    expect(runs).toHaveLength(4);
    const done = runs.filter((r) => r.status === "COMPLETED");
    const held = runs.filter((r) => r.status === "SKIPPED_THROTTLED");
    expect(done).toHaveLength(2);
    expect(held).toHaveLength(2);
    for (const run of done) expect(run.actions_executed).toBe(1);
    for (const run of held) {
      expect(run.actions_executed).toBe(0);
      expect(String(run.error ?? JSON.stringify(run.details))).toContain("limit of 2 an hour");
    }
    // The tag went onto exactly the two documents whose runs did the work.
    const tagged = new Set(done.map((r) => r.work_item_id));
    for (const id of documentIds) {
      expect((await tagsOf(id)).includes(TAG), `document ${id}`).toBe(tagged.has(id));
    }
    expect(new Set(runs.map((r) => r.work_item_id)).size).toBe(4);       // every document has its run row
  });

  test("Run history, filtered to Skipped, lists the held-back runs with the reason in words", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation/timeline"));
    await expect(page.getByRole("heading", { name: "Run history", level: 1 })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("group", { name: "Show runs" }).getByRole("button", { name: "Skipped", exact: true }).click();
    const list = page.locator("main");
    const chains = list.getByRole("button", { name: /chain [0-9a-f]{8}/ });
    await expect(chains).toHaveCount(2, { timeout: 30_000 });
    // One chain is open at a time: read each held-back run in turn.
    for (let i = 0; i < 2; i += 1) {
      await chains.nth(i).click();
      await expect(chains.nth(i)).toHaveAttribute("aria-expanded", "true");
      await expect(list.getByText("Skipped — over the limit", { exact: true })).toHaveCount(1);
      await expect(list.getByText(/already run 2 times in the last hour, which is its limit of 2 an hour/)).toHaveCount(1);
      await expect(list.getByText(/held back, not lost/).first()).toBeVisible();
    }
    // The runs that did the work are not in this view; "All runs" brings them back.
    await expect(list.getByText("Skipped — over the limit", { exact: true }).first()).toBeVisible();
    await page.getByRole("group", { name: "Show runs" }).getByRole("button", { name: "All runs" }).click();
    await expect(list.getByRole("button", { name: /chain [0-9a-f]{8}/ })).toHaveCount(4);
    await page.getByRole("group", { name: "Show runs" }).getByRole("button", { name: "Skipped", exact: true }).click();
    await expectAccessible(page, testInfo, "run history, Skipped");
  });

  test("the rule card says some runs were held back, and the owner got ONE notice", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await openAutomation(page);
    await expect(cardOf(page, RULE).getByTestId("rule-health")).toContainText("2 held back by the limit");
    await expect(cardOf(page, RULE).getByTestId("rule-health")).toContainText("2 runs in 7 days");

    const title = `Automation held back: ${RULE}`;
    const listed = await api<Array<{ title: string; message: string }>>(customer.session, "GET", `/workspaces/${customer.wsId}/notifications`);
    expect(listed.status).toBe(200);
    expect(listed.body.filter((n) => n.title === title)).toHaveLength(1);       // two runs held back, one notice
    expect(listed.body.find((n) => n.title === title)!.message).toContain("limit of 2 runs an hour");

    await page.goto(customer.ws("notifications"));
    await settle(page);
    await expect(page.getByRole("article", { name: `Notification: ${title}` })).toHaveCount(1);
    await expect(page.getByRole("article", { name: `Notification: ${title}` })).toContainText("Run history as Skipped");
    await expect(page.getByRole("button", { name: "Open Notifications Center" })).toBeVisible();
    await expect(page.getByLabel(/\d+ unread alerts/)).toBeVisible();
    await expectAccessible(page, testInfo, "notifications");
  });

  test("Pause all automations asks first; confirmed, the banner shows and the cards say Paused", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await openAutomation(page);
    expect(await pausedNow()).toBe(false);
    await page.getByRole("button", { name: "Pause all automations" }).click();
    const ask = page.getByRole("alertdialog", { name: "Pause all automations?" });
    await expect(ask).toBeVisible();
    await expect(ask).toContainText("Nothing is lost");
    await expectAccessible(page, testInfo, "pause dialog", '[role="alertdialog"]');
    // Cancelled: nothing changes.
    await ask.getByRole("button", { name: /Cancel|Keep/ }).click();
    await expect(ask).toHaveCount(0);
    expect(await pausedNow()).toBe(false);
    await expect(page.getByText("Automations are paused.")).toHaveCount(0);

    await page.getByRole("button", { name: "Pause all automations" }).click();
    await page.getByRole("alertdialog", { name: "Pause all automations?" }).getByRole("button", { name: "Pause automations" }).click();
    const banner = page.getByRole("status").filter({ hasText: "Automations are paused." });
    await expect(banner).toBeVisible();
    await expect(page.getByRole("button", { name: "Resume automations" })).toBeVisible();
    await expect(cardOf(page, RULE)).toContainText("Paused");
    expect(await pausedNow()).toBe(true);
    await page.reload();
    await expect(page.getByRole("status").filter({ hasText: "Automations are paused." })).toBeVisible();
    await expectAccessible(page, testInfo, "automation page while paused");
  });

  test("while paused a document is a run Skipped — paused, and its tag is not applied", async ({ page }) => {
    const id = await uploadInvoice("paused");
    await processed(customer, id);
    await expect.poll(async () => (await executionsOf(customer, `rule_id=${ruleId}&work_item_id=${id}`)).length, { timeout: 60_000 }).toBe(1);
    const run = (await executionsOf(customer, `rule_id=${ruleId}&work_item_id=${id}`))[0] as ExecutionRow;
    expect(run.status).toBe("SKIPPED_PAUSED");
    expect(run.actions_executed).toBe(0);
    expect(await tagsOf(id)).not.toContain(TAG);

    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation/timeline"));
    await page.getByRole("group", { name: "Show runs" }).getByRole("button", { name: "Skipped", exact: true }).click();
    const chain = page.locator("main").getByRole("button", { name: new RegExp(`chain ${run.correlation_id.slice(0, 8)}`) });
    await expect(chain).toBeVisible({ timeout: 30_000 });
    await chain.click();
    await expect(page.locator(`#execution-${run.id}`)).toContainText("Skipped — paused");
    await expect(page.locator(`#execution-${run.id}`)).toContainText("automations are paused");
    await page.goto(customer.ws("automation"));
    await expect(cardOf(page, RULE).getByTestId("rule-health")).toContainText("1 skipped while paused");
  });

  test("Resume automations lifts it; with the limit raised, the next document runs and is tagged", async ({ page }) => {
    await signInAs(page, customer.email);
    await openAutomation(page);
    await page.getByRole("button", { name: "Resume automations" }).click();
    await expect(page.getByText("Automations are paused.")).toHaveCount(0);
    await expect(cardOf(page, RULE)).not.toContainText("Paused");
    expect(await pausedNow()).toBe(false);

    // The notice said to raise the limit if it is too low: do that in the builder.
    await page.getByRole("button", { name: `Edit rule ${RULE}` }).click();
    const builder = builderOf(page);
    await expect(builder.getByRole("heading", { name: "Edit automation" })).toBeVisible();
    await builder.getByRole("tab", { name: "Advanced" }).click();
    const limit = builder.getByRole("spinbutton", { name: "At most this many runs an hour" });
    await expect(limit).toHaveValue("2");
    await limit.fill("5");
    await builder.getByRole("button", { name: "Save changes" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    await expect(cardOf(page, RULE)).toContainText("Up to 5 runs an hour");

    const id = await uploadInvoice("resumed");
    await processed(customer, id);
    await expect.poll(async () => (await executionsOf(customer, `rule_id=${ruleId}&work_item_id=${id}`))[0]?.status, { timeout: 60_000 }).toBe("COMPLETED");
    const run = (await executionsOf(customer, `rule_id=${ruleId}&work_item_id=${id}`))[0]!;
    expect(run.actions_executed).toBe(1);
    expect(await tagsOf(id)).toContain(TAG);
    // Nothing from before changed: still 2 held back by the limit, 1 skipped while paused, 3 that ran.
    const all = await executionsOf(customer, `rule_id=${ruleId}`);
    expect(all.filter((r) => r.status === "SKIPPED_THROTTLED")).toHaveLength(2);
    expect(all.filter((r) => r.status === "SKIPPED_PAUSED")).toHaveLength(1);
    expect(all.filter((r) => r.status === "COMPLETED")).toHaveLength(3);
  });
});
