/**
 * AUTOMATION, FROM A RECIPE TO A REAL HOLD (Session J).
 *
 * A new customer (Enterprise, a tenant of its own) opens "Start from a recipe", uses "Hold invoices above ₹10 lakh for
 * review", reads the rule the builder opened for them and switches it on. Then two invoices arrive, both in INR: one for
 * ₹12,50,000 and one for ₹4,50,000. The worker reads them and the engine runs:
 *
 *   - the big invoice has a run in Run history whose steps, opened with "Show steps", say in words why it matched
 *     ("greater than"), and the document is held: a review row exists (API) and it shows in the review hub;
 *   - the small invoice's run took no step (actions_executed 0), its trace says why not, and nothing was held for it.
 *
 * The money is compared in rupees, never in micros: the rule stores "1000000" and currency INR (checked through the API).
 * Accessibility is scanned in both themes on the gallery, the builder and Run history.
 *
 * Stood in: the model that reads the documents (support/llm-mock.mjs) and nothing else; the rule engine is the real one.
 */
import type { Page } from "@playwright/test";

import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { signInAs, type Customer } from "../support/journey";
import {
  builderOf, cardOf, enterpriseCustomer, executionsOf, expectAccessible, invoiceLines, listRules, processed, runsSettled, uploadLines,
} from "../support/workflow-helpers";

const RECIPE_TITLE = "Hold invoices above ₹10 lakh for review";

let customer: Customer;

interface Verification { id: string; status: string; work_item_id: string }

const verificationsOf = async (): Promise<Verification[]> => {
  const listed = await api<Verification[]>(customer.session, "GET", `/workspaces/${customer.wsId}/verifications?limit=100`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body;
};

const openGallery = async (page: Page): Promise<void> => {
  await page.goto(customer.ws("automation"));
  await page.getByRole("button", { name: "Start from a recipe" }).click();
  await expect(page.getByRole("dialog", { name: "Start from a recipe" })).toBeVisible();
};

test.describe("Automation: a recipe becomes a real hold", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  let bigDocument = "";
  let smallDocument = "";
  let ruleId = "";
  let bigName = "";
  let smallName = "";

  test.beforeAll(async () => {
    test.setTimeout(240_000);
    customer = await enterpriseCustomer("recipe");
  });

  test("the gallery lists the recipes, filters them and has no serious accessibility violation", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await openGallery(page);
    const gallery = page.getByRole("dialog", { name: "Start from a recipe" });
    await expect(gallery.getByTestId("recipe-hold-big-invoices")).toContainText(RECIPE_TITLE);
    await expect(gallery.getByTestId("recipe-hold-big-invoices")).toContainText("Any invoice over ₹10,00,000 waits for a person");
    const all = await gallery.getByRole("listitem").count();
    expect(all).toBeGreaterThanOrEqual(10);

    // Search narrows the list; a category does too; nothing found says so.
    await gallery.getByRole("searchbox", { name: "Search recipes" }).fill("lakh");
    await expect(gallery.getByTestId("recipe-hold-big-invoices")).toBeVisible();
    await expect(gallery.getByTestId("recipe-weekly-digest")).toHaveCount(0);
    await gallery.getByRole("searchbox", { name: "Search recipes" }).fill("zzz-no-such-recipe");
    await expect(gallery.getByText("No recipe matches")).toBeVisible();
    await gallery.getByRole("searchbox", { name: "Search recipes" }).fill("");
    await gallery.getByRole("group", { name: "Recipe category" }).getByRole("button", { name: "GST", exact: true }).click();
    await expect(gallery.getByTestId("recipe-gst-chase-supplier")).toBeVisible();
    await expect(gallery.getByTestId("recipe-hold-big-invoices")).toHaveCount(0);
    await gallery.getByRole("group", { name: "Recipe category" }).getByRole("button", { name: "All", exact: true }).click();
    await expect(gallery.getByTestId("recipe-hold-big-invoices")).toBeVisible();

    // A recipe that needs an answer asks for it first and will not open without it.
    await gallery.getByRole("button", { name: "Use the recipe: Email the CFO about invoices above ₹25 lakh" }).click();
    // The dialog is now titled by the recipe chosen.
    const form = page.getByRole("dialog", { name: "Email the CFO about invoices above ₹25 lakh" });
    await expect(form.getByLabel("Who to email")).toBeVisible();
    await expect(form.getByRole("button", { name: "Open in the builder" })).toBeDisabled();
    await form.getByRole("button", { name: "Back to all recipes" }).click();
    await expect(gallery.getByTestId("recipe-hold-big-invoices")).toBeVisible();

    await expectAccessible(page, testInfo, "recipe gallery", '[role="dialog"]');
  });

  test("using the recipe opens the builder filled in; creating it switches the rule on", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await openGallery(page);
    await page.getByRole("button", { name: `Use the recipe: ${RECIPE_TITLE}` }).click();

    const builder = builderOf(page);
    await expect(builder).toBeVisible();
    await expect(builder.getByRole("heading", { name: "New automation from a recipe" })).toBeVisible();
    await expect(builder.getByRole("textbox", { name: "Name", exact: true })).toHaveValue(RECIPE_TITLE);
    await expect(builder.getByRole("checkbox", { name: "Active" })).toBeChecked();

    // The rule reads as one plain sentence, with nothing left to fix.
    const summary = builder.getByRole("complementary", { name: "Rule summary" });
    await expect(summary).toContainText("greater than");
    await expect(summary).toContainText("10,00,000 INR");
    await expect(builder.getByLabel("Rule status")).toContainText("No blocking issues");

    // The "Only if" box carries the money condition in rupees, with its currency.
    await builder.getByTestId("flow-node-conditions").click();
    await expect(builder.getByRole("combobox", { name: "Currency" })).toHaveValue("INR");
    await expect(builder.getByRole("textbox", { name: "Value" }).first()).toHaveValue(/^(1000000|10,00,000)$/);
    // The "Then" box holds the one step: put the document in the review queue.
    await builder.getByTestId("flow-node-actions").click();
    await expect(builder.getByRole("button", { name: /^Step 1 of Then:/ })).toBeVisible();

    await expectAccessible(page, testInfo, "builder from a recipe", '[role="dialog"]');

    await builder.getByRole("button", { name: "Create rule" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    const card = cardOf(page, RECIPE_TITLE);
    await expect(card).toBeVisible();
    await expect(card.getByRole("switch", { name: `Toggle rule ${RECIPE_TITLE}` })).toBeChecked();
    await expect(card.getByTestId("rule-sentence")).toContainText("greater than");

    // The server stored rupees, not micros, with the currency.
    const rules = await listRules(customer);
    expect(rules).toHaveLength(1);
    const rule = rules[0]!;
    ruleId = rule.id;
    expect(rule.is_active).toBe(true);
    expect(rule.triggers).toEqual(["document.completed"]);
    expect(rule.actions.map((a) => a.action_type)).toEqual(["review.escalate"]);
    const money = rule.condition_groups?.flatMap((g) => g.conditions).find((c) => c.field === "total_amount");
    expect(money, JSON.stringify(rule.condition_groups)).toBeTruthy();
    expect(String(money!.value)).toBe("1000000");
    expect(money!.currency).toBe("INR");
    expect(money!.operator).toBe("GREATER_THAN");
  });

  test("a big and a small invoice arrive and are read", async () => {
    bigDocument = await uploadLines(customer, "big", invoiceLines({ number: "BIG-1250000", total: "12,50,000.00" }));
    smallDocument = await uploadLines(customer, "small", invoiceLines({ number: "SMALL-450000", total: "4,50,000.00" }));
    const big = await processed(customer, bigDocument);
    const small = await processed(customer, smallDocument);
    bigName = String(big.original_filename);
    smallName = String(small.original_filename);
    // The model stand-in read the totals as rupees.
    expect(JSON.stringify(big.extracted_entities)).toMatch(/1250000/);
    expect(JSON.stringify(small.extracted_entities)).toMatch(/450000/);
    const runs = await runsSettled(customer, ruleId, 2);
    expect(runs.map((r) => r.work_item_id).sort()).toEqual([bigDocument, smallDocument].sort());
  });

  test("Run history explains both runs in words, and only the big invoice was held", async ({ page }, testInfo) => {
    const bigRun = (await executionsOf(customer, `rule_id=${ruleId}&work_item_id=${bigDocument}`))[0]!;
    const smallRun = (await executionsOf(customer, `rule_id=${ruleId}&work_item_id=${smallDocument}`))[0]!;
    expect(bigRun.actions_executed).toBe(1);
    expect(bigRun.status).toBe("COMPLETED");
    expect(smallRun.actions_executed).toBe(0);

    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation/timeline"));
    const bigChain = page.locator("main").getByRole("button", { name: new RegExp(`chain ${bigRun.correlation_id.slice(0, 8)}`) });
    await expect(bigChain).toBeVisible({ timeout: 30_000 });
    await bigChain.click();
    await expect(bigChain).toHaveAttribute("aria-expanded", "true");
    const bigItem = page.locator(`#execution-${bigRun.id}`);
    await expect(bigItem).toContainText(RECIPE_TITLE);
    await expect(bigItem).toContainText("1 actions");
    await bigItem.getByRole("button", { name: "Show steps" }).click();
    const decided = bigItem.getByRole("list", { name: "What each condition decided" });
    await expect(decided).toBeVisible();
    await expect(decided).toContainText("✓");
    await expect(decided).toContainText("greater than");
    await expect(decided.getByRole("listitem").filter({ hasText: "Total amount" })).toContainText("Total amount (INR 12,50,000.00) is greater than INR 10,00,000.00");
    await expect(bigItem.getByRole("list", { name: "Steps of this run" })).toContainText("review.escalate");
    await expect(bigItem.getByRole("link", { name: "Open the document" })).toBeVisible();

    // The small invoice's run took no step, and says why: the amount is not greater than the limit.
    const smallChain = page.locator("main").getByRole("button", { name: new RegExp(`chain ${smallRun.correlation_id.slice(0, 8)}`) });
    await smallChain.click();
    const smallItem = page.locator(`#execution-${smallRun.id}`);
    await expect(smallItem).toBeVisible();
    await expect(smallItem).not.toContainText("1 actions");
    await smallItem.getByRole("button", { name: "Show steps" }).click();
    const notMet = smallItem.getByRole("list", { name: "What each condition decided" });
    await expect(notMet).toContainText("✗");
    await expect(notMet).toContainText("Total amount (INR 4,50,000.00)");

    await expectAccessible(page, testInfo, "run history with steps");
  });

  test("the big invoice is held for review (API and review hub); the small one is not", async ({ page }) => {
    const verifications = await verificationsOf();
    const open = verifications.filter((v) => v.status === "DISAGREED");
    expect(open.map((v) => v.work_item_id)).toContain(bigDocument);
    expect(open.map((v) => v.work_item_id)).not.toContain(smallDocument);
    const held = verifications.find((v) => v.work_item_id === bigDocument && v.status === "DISAGREED")!;
    const detail = await api<{ details?: { escalation?: { reason?: string; rule_id?: string } } }>(
      customer.session, "GET", `/workspaces/${customer.wsId}/verifications/${held.id}`);
    expect(detail.body.details?.escalation?.rule_id).toBe(ruleId);
    expect(detail.body.details?.escalation?.reason).toContain("above ₹10 lakh");

    // The review hub lists the big invoice's file, and not the small one's.
    expect(bigName).toMatch(/^big-/);
    await signInAs(page, customer.email);
    await page.goto(customer.ws("verification"));
    await settle(page);
    await expect(page.getByRole("list", { name: "Review items" }).getByRole("listitem").filter({ hasText: bigName }).first())
      .toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("list", { name: "Review items" }).getByText(smallName)).toHaveCount(0);
  });
});
