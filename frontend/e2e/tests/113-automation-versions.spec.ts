/**
 * A RULE'S HISTORY AND RESTORE (Session J).
 *
 * The owner creates a rule, then edits it twice in the builder (a condition value; then a limit and a new name). The
 * card's "History of rule …" lists every version with what changed in plain words. "Restore version 1" asks first, and
 * once confirmed the rule goes back (the card and the API agree) while history only GROWS: a fourth version records the
 * restore, and versions 1 to 3 are exactly as they were. A person with the contributor role sees the history but has no
 * Restore button, and the server refuses the call too.
 *
 * Accessibility is scanned in both themes on the history dialog and on the restore confirmation.
 */
import { test, expect } from "../support/fixtures";
import { api, apiLogin } from "../support/api";
import { addMember, signInAs, type Customer } from "../support/journey";
import { builderOf, cardOf, createRuleViaApi, enterpriseCustomer, expectAccessible, listRules, type RuleRow } from "../support/workflow-helpers";

const FIRST = "Big invoices";
const SECOND = "Large invoices";

interface Version { version: number; note: string; changes: string[]; restored_from_version: number | null }

let customer: Customer;
let contributor: { email: string };
let ruleId = "";

const versionsOf = async (): Promise<Version[]> => {
  const listed = await api<{ items: Version[]; total: number }>(customer.session, "GET", `/workspaces/${customer.wsId}/automation/rules/${ruleId}/versions`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
};
const currentRule = async (): Promise<RuleRow> => (await listRules(customer)).find((r) => r.id === ruleId)!;
const moneyValue = (rule: RuleRow): string =>
  String(rule.condition_groups!.flatMap((g) => g.conditions).find((c) => c.field === "total_amount")!.value);

test.describe("Automation: version history and restore", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(300_000);
    customer = await enterpriseCustomer("history");
    contributor = await addMember(customer, "history-contributor", "MEMBER", "CONTRIBUTOR");
    const created = await createRuleViaApi(customer, {
      name: FIRST,
      condition_groups: [{ logic_operator: "AND", conditions: [{ field: "total_amount", operator: "GREATER_THAN", value: "500000", currency: "INR" }] }],
      actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: "Big invoice", message: "A big invoice was read." } }],
    });
    ruleId = created.id;
  });

  test("two edits in the builder: the condition value; then a limit and a new name", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await expect(cardOf(page, FIRST)).toBeVisible({ timeout: 30_000 });

    // Edit 1: raise the bar, with a note for the history.
    await page.getByRole("button", { name: `Edit rule ${FIRST}` }).click();
    let builder = builderOf(page);
    await expect(builder.getByRole("heading", { name: "Edit automation" })).toBeVisible();
    await builder.getByTestId("flow-node-conditions").click();
    const value = builder.getByRole("textbox", { name: "Value" });
    await expect(value).toHaveValue("500000");
    await value.fill("1000000");
    await builder.getByRole("tab", { name: "Advanced" }).click();
    await builder.getByRole("textbox", { name: "Note for the history (optional)" }).fill("Raised the bar after month end");
    await builder.getByRole("button", { name: "Save changes" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    await expect(cardOf(page, FIRST).getByTestId("rule-sentence")).toContainText("10,00,000 INR");

    // Edit 2: a limit of 20 runs an hour, and a new name.
    await page.getByRole("button", { name: `Edit rule ${FIRST}` }).click();
    builder = builderOf(page);
    await builder.getByRole("textbox", { name: "Name", exact: true }).fill(SECOND);
    await builder.getByTestId("flow-node-actions").click();
    await builder.getByRole("tab", { name: "Advanced" }).click();
    await builder.getByRole("spinbutton", { name: "At most this many runs an hour" }).fill("20");
    await builder.getByRole("button", { name: "Save changes" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    await expect(cardOf(page, SECOND)).toBeVisible();
    await expect(cardOf(page, SECOND)).toContainText("Up to 20 runs an hour");
    await expect(cardOf(page, FIRST)).toHaveCount(0);

    const rule = await currentRule();
    expect(rule.name).toBe(SECOND);
    expect(rule.max_runs_per_hour).toBe(20);
    expect(moneyValue(rule)).toBe("1000000");
  });

  test("the history lists each version with its changes in plain words", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await page.getByRole("button", { name: `History of rule ${SECOND}` }).click();
    const history = page.getByRole("dialog", { name: `History of “${SECOND}”` });
    await expect(history).toBeVisible();
    const versions = history.getByRole("listitem").filter({ has: page.getByText(/^Version \d/) });
    await expect(versions).toHaveCount(3);

    // Newest first: version 3 is current, and has no Restore button of its own.
    const v3 = versions.nth(0);
    await expect(v3).toContainText("Version 3");
    await expect(v3).toContainText("Current");
    await expect(v3).toContainText(`Renamed the rule from “${FIRST}” to “${SECOND}”`);
    await expect(v3).toContainText("Set a limit of 20 runs an hour");
    await expect(v3.getByRole("button", { name: /Restore/ })).toHaveCount(0);

    const v2 = versions.nth(1);
    await expect(v2).toContainText("Version 2");
    await expect(v2).toContainText("Removed condition: Total amount is greater than 500000 INR");
    await expect(v2).toContainText("Added condition: Total amount is greater than 1000000 INR");
    await expect(v2).toContainText("Raised the bar after month end");          // the note the owner left

    const v1 = versions.nth(2);
    await expect(v1).toContainText("Version 1");
    await expect(v1).toContainText("Created the rule");
    await expect(v1.getByRole("button", { name: "Restore version 1" })).toBeVisible();

    await expectAccessible(page, testInfo, "version history", '[role="dialog"]');
  });

  test("Restore version 1 asks first; confirmed, the rule goes back and a fourth version records it", async ({ page }, testInfo) => {
    const before = await versionsOf();
    expect(before.map((v) => v.version)).toEqual([3, 2, 1]);

    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await page.getByRole("button", { name: `History of rule ${SECOND}` }).click();
    const history = page.getByRole("dialog", { name: `History of “${SECOND}”` });
    await history.getByRole("button", { name: "Restore version 1" }).click();
    const ask = page.getByRole("alertdialog", { name: "Restore version 1?" });
    await expect(ask).toContainText("saved as a new version, so nothing is lost");
    await expectAccessible(page, testInfo, "restore confirmation", '[role="alertdialog"]');

    // Keep the current one: nothing changes.
    await ask.getByRole("button", { name: "Keep the current one" }).click();
    await expect(ask).toHaveCount(0);
    expect((await currentRule()).name).toBe(SECOND);
    expect(await versionsOf()).toHaveLength(3);

    await history.getByRole("button", { name: "Restore version 1" }).click();
    await page.getByRole("alertdialog", { name: "Restore version 1?" }).getByRole("button", { name: "Restore this version" }).click();

    // The dialog now lists four versions; the new one is current and says where it came from.
    const versions = history.getByRole("listitem").filter({ has: page.getByText(/^Version \d/) });
    await expect(versions).toHaveCount(4, { timeout: 20_000 });
    const v4 = versions.nth(0);
    await expect(v4).toContainText("Version 4");
    await expect(v4).toContainText("Current");
    await expect(v4).toContainText(`Renamed the rule from “${SECOND}” to “${FIRST}”`);
    await expect(v4).toContainText("Removed condition: Total amount is greater than 1000000 INR");
    await expect(v4).toContainText("Added condition: Total amount is greater than 500000 INR");
    await expect(v4).toContainText("Went back to the workspace's default runs-per-hour limit");

    // The rule itself: the card, then the server.
    await history.getByRole("button", { name: "Close the history" }).click();
    await expect(cardOf(page, FIRST)).toBeVisible();
    await expect(cardOf(page, FIRST)).not.toContainText("Up to 20 runs an hour");
    await expect(cardOf(page, FIRST).getByTestId("rule-sentence")).toContainText("5,00,000 INR");
    await expect(cardOf(page, SECOND)).toHaveCount(0);

    const rule = await currentRule();
    expect(rule.name).toBe(FIRST);
    expect(rule.max_runs_per_hour ?? null).toBeNull();
    expect(moneyValue(rule)).toBe("500000");
    expect(rule.is_active).toBe(true);

    // Nothing was lost: versions 1 to 3 read exactly as before, and the fourth points back at version 1.
    const after = await versionsOf();
    expect(after.map((v) => v.version)).toEqual([4, 3, 2, 1]);
    for (const old of before) {
      const same = after.find((v) => v.version === old.version)!;
      expect(same.changes, `version ${old.version}`).toEqual(old.changes);
      expect(same.note).toBe(old.note);
    }
    expect(after[0]!.restored_from_version).toBe(1);
  });

  test("a contributor has no History or Restore button on the page, and the server refuses the restore", async ({ page, problems }) => {
    problems.allowHttp(/\/automation\/rules\/.*\/versions\/\d+\/restore/, [403], "a contributor may not restore a version");
    await signInAs(page, contributor.email);
    await page.goto(customer.ws("automation"));
    await expect(cardOf(page, FIRST)).toBeVisible({ timeout: 30_000 });
    // The rule is there to read, but the page offers no way to open its history or change it.
    await expect(page.getByRole("button", { name: `History of rule ${FIRST}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Edit rule ${FIRST}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Restore version/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Pause all automations" })).toHaveCount(0);

    // The server agrees. Reading the history is allowed; restoring is not.
    const contributorSession = await apiLogin(contributor.email);
    const read = await api<{ items: Version[] }>(contributorSession, "GET", `/workspaces/${customer.wsId}/automation/rules/${ruleId}/versions`);
    expect(read.status).toBe(200);
    expect(read.body.items).toHaveLength(4);
    const refused = await api(contributorSession, "POST", `/workspaces/${customer.wsId}/automation/rules/${ruleId}/versions/1/restore`, {});
    expect(refused.status).toBe(403);
    expect(await versionsOf()).toHaveLength(4);                      // nothing was added
    expect((await currentRule()).name).toBe(FIRST);
  });
});
