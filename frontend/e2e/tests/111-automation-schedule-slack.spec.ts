/**
 * AUTOMATION ON A SCHEDULE THAT POSTS TO SLACK (Session J).
 *
 * The owner has registered a Slack channel (an incoming-webhook URL, a secret) and builds, in the browser, the rule
 * "Every day -> post a message to chat". The clock is played by the suite's job runner: the stand-in queues
 * `automation.sweep` (the hourly job that announces the day to every workspace listening for it) and waits for the
 * worker to finish it. What is proved:
 *
 *   - the Slack URL is a secret: the API shows only its host ("https://hooks.slack.com/…"), the rule holds the endpoint's
 *     id and never the URL, and the token appears in no API answer, no page and no run;
 *   - the sweep announces the day: ONE run of the rule, with one step "chat.post" that queued a message, and a second sweep
 *     on the same day announces nothing again;
 *   - a delivery row for that endpoint exists (event "workflow.triggered"), and its log carries no URL or token;
 *   - Run history shows the run and the step in words.
 *
 * STOOD IN, AND WHAT IS NOT PROVEN HERE. The message is NOT received by a stand-in Slack: the API only posts to hosts it
 * may reach (https, and never a loopback or private address: backend/app/core/ssrf_client.py), and the running stack's
 * environment is fixed. So that nothing leaves the machine for the real hooks.slack.com, the organization switches its
 * egress lockdown on after the rule is saved (spec 99's feature) and the delivery is refused by the organization's own
 * network rules; the log says so in words. Getting the body of the message to a receiver needs a backend change, written
 * in the Session J report (a development-only switch that lets the chat delivery reach a loopback receiver).
 */
import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { runId } from "../support/env";
import { signInAs, standIn, type Customer } from "../support/journey";
import {
  builderOf, cardOf, dbRows, enterpriseCustomer, executionsOf, expectAccessible, listRules, registerSlackChannel,
} from "../support/workflow-helpers";

const RULE = "Good morning, finance";
const TOKEN = `e2eSecretToken${runId().replace(/[^a-zA-Z0-9]/g, "")}`;
const SLACK_URL = `https://hooks.slack.com/services/T0E2E0001/B0E2E0001/${TOKEN}`;

let customer: Customer;
let endpointId = "";
let ruleId = "";

/** A time zone where it is between 09:00 and 20:00 now: the daily announcement waits for 08:00 local time. */
function zoneWhereItIsDaytime(): string {
  for (const zone of ["UTC", "Asia/Kolkata", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Tokyo", "Australia/Sydney", "Pacific/Auckland"]) {
    const hour = Number(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: zone }).format(new Date()));
    if (hour >= 9 && hour <= 20) return zone;
  }
  throw new Error("no time zone is in the daytime");
}

interface Delivery { id: string; event_type: string; status: string; attempts: number; last_error: string | null }
interface Attempt { disposition: string; error: string | null }

const webhooksUrl = (): string => `/organizations/${customer.orgId}/webhooks`;
const deliveries = async (): Promise<Delivery[]> => {
  const listed = await api<Delivery[]>(customer.session, "GET", `${webhooksUrl()}/endpoints/${endpointId}/deliveries`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body;
};

const sweep = (): void => {
  const outcome = standIn("run-job", customer.orgSlug, "--job", "automation.sweep");
  expect(outcome.status, JSON.stringify(outcome)).toBe("SUCCEEDED");
};

test.describe("Automation: a daily rule posts to Slack", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(240_000);
    customer = await enterpriseCustomer("schedule");
    const zone = await api(customer.session, "PATCH", `/workspaces/${customer.wsId}`, { timezone: zoneWhereItIsDaytime() });
    expect(zone.status, zone.text.slice(0, 300)).toBe(200);
  });

  test("the Slack channel is stored as a secret: only its host is ever shown back", async () => {
    // Not a Slack address: refused in words, nothing stored.
    const wrong = await api<{ detail: string }>(customer.session, "POST", `${webhooksUrl()}/endpoints`, {
      kind: "SLACK", url: "https://example.com/services/T/B/x", description: "wrong place",
    });
    expect(wrong.status).toBe(422);
    expect(JSON.stringify(wrong.body)).toContain("incoming-webhook address");

    endpointId = registerSlackChannel(customer, SLACK_URL, "Finance channel");

    const listed = await api<Array<{ id: string; url: string; kind: string }>>(customer.session, "GET", `${webhooksUrl()}/endpoints`);
    expect(listed.text).not.toContain(TOKEN);
    const shown = listed.body.find((e) => e.id === endpointId)!;
    expect(shown.url).toBe("https://hooks.slack.com/…");
    expect(shown.kind).toBe("SLACK");
    const one = await api(customer.session, "GET", `${webhooksUrl()}/endpoints/${endpointId}`);
    expect(one.text).not.toContain(TOKEN);
    // At rest the URL is encrypted: the database column holds no token either.
    const stored = dbRows(`select url, url_encrypted from webhook_endpoints where id = '${endpointId}'`)[0]!;
    expect(stored.url).toBe("https://hooks.slack.com/…");
    expect(JSON.stringify(stored)).not.toContain(TOKEN);
  });

  test("the owner builds the daily rule in the browser: Every day, post to the Slack channel", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await page.getByRole("button", { name: "Create New Rule" }).click();
    const builder = builderOf(page);
    await builder.getByRole("textbox", { name: "Name", exact: true }).fill(RULE);
    await builder.getByTestId("flow-node-trigger").click();
    await builder.getByRole("checkbox", { name: /^Every day/ }).check();

    await builder.getByTestId("flow-node-actions").click();
    await builder.getByRole("combobox", { name: "Add an action" }).first().selectOption("chat.post");
    const channel = builder.getByLabel("Webhook endpoint");
    await expect(channel.locator("option", { hasText: "Slack" })).toHaveCount(1);
    await channel.selectOption({ index: 1 });
    await builder.getByRole("textbox", { name: "Message", exact: true }).fill("Good morning. Today is {{event.local_date}}: the review queue is waiting.");
    await expect(builder.getByRole("complementary", { name: "Rule summary" })).toContainText(/every day/i);
    await expect(builder.getByLabel("Rule status")).toContainText("No blocking issues");
    // The secret URL is nowhere in the builder.
    expect(await builder.innerText()).not.toContain(TOKEN);
    expect(await builder.innerHTML()).not.toContain(TOKEN);

    await expectAccessible(page, testInfo, "builder with a schedule and a chat step", '[role="dialog"]');

    await builder.getByRole("button", { name: "Create rule" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    await expect(cardOf(page, RULE)).toBeVisible();
    await expect(cardOf(page, RULE).getByTestId("rule-sentence")).toContainText(/every day/i);

    const rule = (await listRules(customer)).find((r) => r.name === RULE)!;
    ruleId = rule.id;
    expect(rule.triggers).toEqual(["schedule.daily"]);
    expect(rule.actions).toHaveLength(1);
    expect(rule.actions[0]!.action_type).toBe("chat.post");
    expect(rule.actions[0]!.config.endpoint_id).toBe(endpointId);
    expect(JSON.stringify(await listRules(customer))).not.toContain(TOKEN);
    expect(await page.content()).not.toContain(TOKEN);
  });

  test("the sweep announces the day once: one run, one message queued, none again on a second sweep", async () => {
    // Nothing leaves the machine for the real Slack: the organization's own network rules refuse the delivery.
    const lock = await api(customer.session, "PUT", `/organizations/${customer.orgId}/egress`, { lockdown_enabled: true });
    expect(lock.status, lock.text.slice(0, 300)).toBeLessThan(300);

    sweep();
    await expect.poll(async () => (await executionsOf(customer, `rule_id=${ruleId}`)).length, { timeout: 60_000, intervals: [1_000] }).toBe(1);
    const run = (await executionsOf(customer, `rule_id=${ruleId}`))[0]!;
    await expect.poll(async () => (await executionsOf(customer, `rule_id=${ruleId}`))[0]!.status, { timeout: 60_000, intervals: [1_000] }).toBe("COMPLETED");
    expect(run.work_item_id).toBeNull();                          // a schedule has no document
    const finished = (await executionsOf(customer, `rule_id=${ruleId}`))[0]!;
    expect(finished.actions_executed).toBe(1);

    const nodes = await api<Array<{ action_type: string | null; status: string; outcome: string | null }>>(
      customer.session, "GET", `/workspaces/${customer.wsId}/automation/executions/${run.id}/nodes`);
    expect(nodes.status, nodes.text.slice(0, 300)).toBe(200);
    const step = nodes.body.find((node) => node.action_type === "chat.post")!;
    expect(step.status).toBe("COMPLETED");
    expect(step.outcome).toBe("message queued for Slack");
    expect(nodes.text).not.toContain(TOKEN);

    // The same day, announced again: nothing new.
    sweep();
    await new Promise((resolve) => setTimeout(resolve, 2_000));
    expect(await executionsOf(customer, `rule_id=${ruleId}`)).toHaveLength(1);
  });

  test("a delivery row exists for the channel, its log is truthful and carries no secret", async () => {
    await expect.poll(async () => (await deliveries()).length, { timeout: 30_000, intervals: [1_000] }).toBe(1);
    const row = (await deliveries())[0]!;
    expect(row.event_type).toBe("workflow.triggered");
    // The worker tries it and the organization's egress lockdown refuses: it never reaches Slack.
    await expect.poll(async () => (await deliveries())[0]!.attempts, { timeout: 60_000, intervals: [1_000] }).toBeGreaterThanOrEqual(1);
    const after = (await deliveries())[0]!;
    expect(after.status).not.toBe("DELIVERED");
    expect(JSON.stringify(after)).not.toContain(TOKEN);
    expect(String(after.last_error ?? "")).toMatch(/egress|network rules|lockdown|not allow/i);
    const attempts = await api<Attempt[]>(customer.session, "GET", `${webhooksUrl()}/deliveries/${row.id}/attempts`);
    expect(attempts.status, attempts.text.slice(0, 300)).toBe(200);
    expect(attempts.body.length).toBeGreaterThanOrEqual(1);
    expect(attempts.text).not.toContain(TOKEN);
    expect(attempts.text).not.toContain("T0E2E0001/B0E2E0001");

    // What was queued for Slack is the message the rule wrote, formatted for Slack, with today's date filled in.
    const queued = dbRows(`select payload from webhook_deliveries where id = '${row.id}'`)[0]!;
    const payload = queued.payload as { chat: { text: string }; rule_id: string };
    expect(payload.rule_id).toBe(ruleId);
    expect(payload.chat.text).toMatch(/^\*Good morning, finance\*\nGood morning\. Today is \d[^:]*: the review queue is waiting\.$/);
    expect(JSON.stringify(queued)).not.toContain(TOKEN);
  });

  test("Run history shows the daily run in words, with no secret on the page", async ({ page }, testInfo) => {
    const run = (await executionsOf(customer, `rule_id=${ruleId}`))[0]!;
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation/timeline"));
    const chain = page.locator("main").getByRole("button", { name: new RegExp(`chain ${run.correlation_id.slice(0, 8)}`) });
    await expect(chain).toBeVisible({ timeout: 30_000 });
    await chain.click();
    const item = page.locator(`#execution-${run.id}`);
    await expect(item).toContainText(RULE);
    await expect(item).toContainText("1 actions");
    await expect(item.getByRole("link", { name: "Open the document" })).toHaveCount(0);    // a schedule has none
    await item.getByRole("button", { name: "Show steps" }).click();
    await expect(item.getByRole("list", { name: "Steps of this run" })).toContainText("chat.post");
    await expect(item.getByRole("list", { name: "Steps of this run" })).toContainText("message queued for Slack");
    await settle(page);
    expect(await page.content()).not.toContain(TOKEN);
    await expectAccessible(page, testInfo, "run history of the daily run");
  });
});
