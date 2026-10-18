/**
 * THE EXCEPTION AGENT, THE PARTNER MARKETPLACE AND ENTERPRISE IDENTITY CREDENTIALS
 * (campaign Session C, long tail: buttons no browser test had pressed).
 *
 * Process agent (Process intelligence → Exception agent), on an Enterprise tenant of its own:
 *  - "Save policy" stores the autonomy policy (propose, apply themselves, which decisions, the hold) and it
 *    survives a reload; a hold outside 5 to 1440 minutes cannot be saved; a contributor is shown no button
 *    and the server refuses them.
 *  - A proposal raised by the agent from a real disputed invoice (three verification agents disagree, the
 *    worker settles it, the sweep plans it): "Reject" takes a reason, can be cancelled, and the agent does not
 *    raise the same proposal again.
 *  - An automatic resolution: with the organization's reviewed history and its error limit saved, the policy
 *    "apply themselves" makes the agent SCHEDULE the resolution; "Undo" cancels it before it takes effect and
 *    nothing is applied to the document.
 *
 * Partner marketplace: a partner owner registers an Ed25519 public key, creates a catalog item, computes the
 * digest, signs it with the private key (here, in the test, as a partner would offline), publishes the
 * manifest and lists the item; another organization in the partner's book reviews it in the marketplace,
 * installs it (an automation rule is created, disabled) and removes it. A withdrawn item and a revoked key
 * stop an install. There is no platform approval step and no screen for creating a partner: the platform
 * administrator creates the partner and the book entry through the API (see the report).
 *
 * Enterprise identity credentials: the SCIM token is issued, rotated (the old one keeps working for the
 * overlap, the new one works; rotating again ends the first) and revoked (every token stops), checked against
 * the real SCIM endpoint. Only the organization's owner has the buttons.
 */
import crypto from "node:crypto";

import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, fetchOnce, loginAs } from "../support/api";
import { API_ORIGIN, runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, uploadViaApi, type Customer } from "../support/journey";
import { seedReviewedHistory } from "../support/process-agent";
import { buildPdf, DISPUTED_INVOICE_PAGE } from "../support/sample-docs";

async function enterprise(label: string, name: string): Promise<Customer> {
  const customer = await newCustomer(label, name);
  standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "5");
  return customer;
}

// ---------------------------------------------------------------------------------------------
// Process agent
// ---------------------------------------------------------------------------------------------

interface Policy {
  planning_enabled: boolean;
  auto_apply_enabled: boolean;
  auto_apply_kinds: string[];
  hold_minutes: number;
  enabled_at: string | null;
}

interface Proposal {
  id: string;
  status: string;
  proposal_kind: string;
  reject_reason: string | null;
  holds: string[];
  subject_id: string;
  apply_after: string | null;
}

const KIND = "extraction.approve_consensus";
const KIND_LABEL = "Accept the extractors' majority reading";

const processPath = (customer: Customer): string => customer.ws("process");
const policyOf = async (customer: Customer): Promise<Policy> => {
  const read = await api<Policy>(customer.session, "GET", `/workspaces/${customer.wsId}/process/agent/policy`);
  expect(read.status, read.text).toBe(200);
  return read.body;
};
const proposalsOf = async (customer: Customer, query = ""): Promise<Proposal[]> => {
  const listed = await api<{ items: Proposal[] }>(customer.session, "GET",
    `/workspaces/${customer.wsId}/process/agent/proposals${query}`);
  expect(listed.status, listed.text).toBe(200);
  return listed.body.items;
};
const sweep = async (customer: Customer): Promise<void> => {
  const swept = await api(customer.session, "POST", `/workspaces/${customer.wsId}/process/sweep`);
  expect(swept.status, swept.text).toBe(200);
};

async function uploadPdf(customer: Customer, name: string, body: Buffer): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([new Uint8Array(body)], { type: "application/pdf" }), `${name}-${runId()}.pdf`);
  const response = await api<{ id: string }>(customer.session, "POST", `/workspaces/${customer.wsId}/work-items`, form);
  expect(response.status, response.text).toBe(201);
  return response.body.id;
}

async function settled(customer: Customer, id: string): Promise<void> {
  await expect.poll(async () => {
    const item = await api<{ status?: string }>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${id}`);
    return String(item.body.status ?? "");
  }, { timeout: 180_000, intervals: [2_000] }).not.toMatch(/^(PENDING|QUEUED|PROCESSING|UPLOADED|)$/);
}

const agentTab = async (page: Page, customer: Customer): Promise<void> => {
  await page.goto(processPath(customer));
  await settle(page);
  await page.getByRole("tab", { name: /^Exception agent/ }).click();
};

test.describe("Process agent", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);
  let customer: Customer;

  test.beforeAll(async () => {
    customer = await enterprise("agent", "Agent Review Ltd");
    // Three verification agents, so a disputed invoice reaches the review queue for the agent to plan.
    const settings = await api(customer.session, "PUT", `/workspaces/${customer.wsId}/document-settings/`,
      { verification_enabled: true, verification_agents: 3 });
    expect(settings.status, settings.text).toBe(200);
  });

  test("Save policy stores the policy and it survives a reload; a bad hold cannot be saved; a contributor cannot", async ({ page }) => {
    const contributor = await addMember(customer, "agent-contrib", "MEMBER", "CONTRIBUTOR");
    const before = await policyOf(customer);
    expect(before.auto_apply_enabled).toBe(false);

    await signInAs(page, customer.email);
    await agentTab(page, customer);
    const policy = page.getByRole("region", { name: "The agent's policy" });
    const propose = policy.getByRole("checkbox", { name: /Propose resolutions/ });
    const apply = policy.getByRole("checkbox", { name: /Let bounded decisions apply themselves/ });
    const kinds = policy.getByRole("group", { name: "Which decisions" });
    const hold = policy.getByRole("spinbutton", { name: /Hold before applying/ });
    const save = policy.getByRole("button", { name: "Save policy" });

    // Applying themselves is off, and the decisions under it cannot be chosen until it is switched on.
    await expect(propose).toBeChecked();
    await expect(apply).not.toBeChecked();
    await expect(kinds.getByRole("checkbox", { name: KIND_LABEL })).toBeDisabled();
    await propose.uncheck();
    await apply.check();
    await expect(kinds.getByRole("checkbox", { name: KIND_LABEL })).toBeEnabled();
    await kinds.getByRole("checkbox", { name: KIND_LABEL }).check();

    // A hold outside 5 to 1440 minutes is refused by the page before it asks the server.
    await hold.fill("3");
    await expect(hold).toHaveAttribute("aria-invalid", "true");
    await expect(save).toBeDisabled();
    await hold.fill("2000");
    await expect(save).toBeDisabled();
    await hold.fill("45");
    await expect(save).toBeEnabled();
    expect(await policyOf(customer), "nothing is stored before Save").toMatchObject({ auto_apply_enabled: false });

    await save.click();
    await expect(page.getByText("Saved.", { exact: true })).toBeVisible();
    await expect.poll(() => policyOf(customer)).toMatchObject({
      planning_enabled: false, auto_apply_enabled: true, auto_apply_kinds: [KIND], hold_minutes: 45,
    });
    expect((await policyOf(customer)).enabled_at, "switching it on is recorded").not.toBeNull();
    await expect(policy).toContainText("Automatic resolution was switched on");

    // After a reload the page shows what was stored.
    await page.reload();
    await settle(page);
    await page.getByRole("tab", { name: /^Exception agent/ }).click();
    await expect(propose).not.toBeChecked();
    await expect(apply).toBeChecked();
    await expect(kinds.getByRole("checkbox", { name: KIND_LABEL })).toBeChecked();
    await expect(hold).toHaveValue("45");

    // Back to planning on, applying themselves off: saved the same way.
    await propose.check();
    await apply.uncheck();
    await save.click();
    await expect.poll(() => policyOf(customer)).toMatchObject({ planning_enabled: true, auto_apply_enabled: false });

    // The server refuses a bad hold even when the page is bypassed.
    const refused = await api(customer.session, "PUT", `/workspaces/${customer.wsId}/process/agent/policy`,
      { planning_enabled: true, auto_apply_enabled: false, auto_apply_kinds: [], hold_minutes: 3 });
    expect(refused.status, refused.text).toBe(422);

    // A contributor reads the policy but has no button, and the server refuses them.
    const second = await page.context().browser()!.newContext();
    try {
      const other = await second.newPage();
      await signInAs(other, contributor.email);
      await other.goto(processPath(customer));
      await other.getByRole("tab", { name: /^Exception agent/ }).click();
      await expect(other.getByText("A workspace admin sets the policy.")).toBeVisible();
      await expect(other.getByRole("button", { name: "Save policy" })).toHaveCount(0);
    } finally {
      await second.close();
    }
    const denied = await api(contributor.session, "PUT", `/workspaces/${customer.wsId}/process/agent/policy`,
      { planning_enabled: false });
    expect(denied.status, denied.text).toBe(403);
    expect((await policyOf(customer)).planning_enabled, "the contributor changed nothing").toBe(true);
    await expectHealthyPage(page);
  });

  test("Reject: cancel keeps the proposal, rejecting records the reason and the agent does not propose it again", async ({ page }) => {
    const disputed = await uploadPdf(customer, "disputed-reject", buildPdf([DISPUTED_INVOICE_PAGE]));
    await settled(customer, disputed);
    // The three agents' disagreement reaches the review queue a little after the document settles; each
    // sweep reads the queue as it is, so sweep until the agent has proposed something.
    let proposal: Proposal | undefined;
    await expect.poll(async () => {
      await sweep(customer);
      proposal = (await proposalsOf(customer)).find((item) => item.status === "PROPOSED");
      return Boolean(proposal);
    }, { timeout: 120_000, intervals: [3_000] }).toBe(true);
    const id = proposal!.id;

    await signInAs(page, customer.email);
    await page.goto(customer.ws(`process/proposals/${id}`));
    const panel = page.getByRole("region", { name: "Proposal" });
    await expect(panel.getByRole("button", { name: /^Approve/ })).toBeVisible({ timeout: 20_000 });

    // Reject opens the reason list; Cancel closes it and nothing is stored.
    await panel.getByRole("button", { name: "Reject" }).click();
    await expect(panel.getByRole("combobox", { name: "Why" })).toHaveValue("WRONG_DECISION");
    await panel.getByRole("button", { name: "Cancel" }).click();
    await expect(panel.getByRole("combobox", { name: "Why" })).toHaveCount(0);
    expect((await proposalsOf(customer, "?status=PROPOSED")).map((p) => p.id)).toContain(id);

    // Reject with a reason.
    await panel.getByRole("button", { name: "Reject" }).click();
    await panel.getByRole("combobox", { name: "Why" }).selectOption({ label: "It needs context the agent cannot see" });
    await panel.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByText("Rejected. The agent will not propose this again until the item changes.")).toBeVisible();
    await expect(panel).toContainText("Rejected: It needs context the agent cannot see");
    await expect(panel.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Reject" })).toHaveCount(0);

    const stored = await api<{ proposal: Proposal }>(customer.session, "GET",
      `/workspaces/${customer.wsId}/process/agent/proposals/${id}`);
    expect(stored.body.proposal).toMatchObject({ status: "REJECTED", reject_reason: "NEEDS_CONTEXT" });

    // The agent keeps its word: sweeping again raises nothing new for that item.
    const subject = stored.body.proposal.subject_id;
    await sweep(customer);
    await sweep(customer);
    expect((await proposalsOf(customer, `?subject_id=${subject}`)).filter((p) => p.status === "PROPOSED")).toHaveLength(0);

    // The inbox files it under "Rejected or undone", and after a reload it is still rejected.
    await page.goto(processPath(customer));
    await page.getByRole("tab", { name: /^Exception agent/ }).click();
    await page.getByRole("button", { name: /^Rejected or undone/ }).click();
    await expect(page.getByRole("list", { name: "Proposals" })).toContainText("Rejected");
    await page.reload();
    await settle(page);
    await page.getByRole("tab", { name: /^Exception agent/ }).click();
    await page.getByRole("button", { name: /^Rejected or undone/ }).click();
    await expect(page.getByRole("list", { name: "Proposals" }).getByRole("listitem")).not.toHaveCount(0);

    // The server refuses to reject it twice.
    const again = await api(customer.session, "POST", `/workspaces/${customer.wsId}/process/agent/proposals/${id}/reject`,
      { reason: "OTHER" });
    expect(again.status, again.text).toBe(409);
    await expectHealthyPage(page);
  });
});

test.describe("Process agent: an automatic resolution can be undone", () => {
  test.setTimeout(420_000);

  test("Undo cancels a scheduled automatic resolution before it takes effect", async ({ page }) => {
    const owner = await enterprise("agent-auto", "Agent Auto Ltd");
    expect((await api(owner.session, "PUT", `/workspaces/${owner.wsId}/document-settings/`,
      { verification_enabled: true, verification_agents: 3 })).status).toBe(200);
    // Nothing is planned while the documents arrive (a scheduled sweep would otherwise plan them early).
    expect((await api(owner.session, "PUT", `/workspaces/${owner.wsId}/process/agent/policy`,
      { planning_enabled: false })).status).toBe(200);

    // Invoices the three agents read the same way. With no fitted model yet, calibration holds each for a person.
    // Three of them, so that the 1 % audit draw (a random check that sends an automatic resolution to a person
    // anyway) cannot leave the test without a scheduled one.
    const documentIds: string[] = [];
    for (const name of ["auto-undo-a", "auto-undo-b", "auto-undo-c"]) documentIds.push(await uploadViaApi(owner, name));
    for (const id of documentIds) await settled(owner, id);
    const openReviews = async (): Promise<number> => {
      const queue = await api<{ items?: Array<{ work_item_id?: string }>; total?: number }>(owner.session, "GET",
        `/workspaces/${owner.wsId}/review?status=OPEN`);
      expect(queue.status, queue.text.slice(0, 300)).toBe(200);
      return (queue.body.items ?? []).filter((item) => documentIds.includes(String(item.work_item_id))).length;
    };
    await expect.poll(openReviews, { timeout: 120_000, intervals: [3_000] }).toBe(3);

    // The organization's reviewed history, and the error limit saved through the product: the model is fitted.
    seedReviewedHistory(owner.orgId);
    const fitted = await api<{ ok: boolean; entry: { threshold: string | null } }>(owner.session, "PUT",
      `/organizations/${owner.orgId}/autonomy/verification.document`, { target_error_rate: "0.15", audit_sample_rate: "0.01" });
    expect(fitted.status, fitted.text).toBe(200);
    expect(fitted.body.entry.threshold, "a model was fitted").not.toBeNull();

    // The owner lets that decision apply itself, in the browser, and asks the agent to sweep.
    await signInAs(page, owner.email);
    await agentTab(page, owner);
    const policy = page.getByRole("region", { name: "The agent's policy" });
    await policy.getByRole("checkbox", { name: /Propose resolutions/ }).check();
    await policy.getByRole("checkbox", { name: /Let bounded decisions apply themselves/ }).check();
    await policy.getByRole("group", { name: "Which decisions" }).getByRole("checkbox", { name: KIND_LABEL }).check();
    await policy.getByRole("button", { name: "Save policy" }).click();
    await expect(page.getByText("Saved.", { exact: true })).toBeVisible();
    await expect.poll(() => policyOf(owner)).toMatchObject({ planning_enabled: true, auto_apply_enabled: true, auto_apply_kinds: [KIND] });
    await page.getByRole("button", { name: "Sweep now" }).click();
    await expect(page.getByText("The log is up to date, the models refitted and the queue planned.")).toBeVisible({ timeout: 60_000 });
    await expect.poll(async () => (await proposalsOf(owner, "?status=AUTO_SCHEDULED")).length, { timeout: 60_000 }).toBeGreaterThan(0);
    const scheduled = await proposalsOf(owner, "?status=AUTO_SCHEDULED");
    const target = scheduled[0]!;
    expect(target).toMatchObject({ proposal_kind: KIND, holds: [] });
    expect(target.apply_after, "it applies itself after the hold").not.toBeNull();

    // The proposal shows that it will apply itself unless someone undoes it.
    await page.reload();
    await settle(page);
    await page.getByRole("tab", { name: /^Exception agent/ }).click();
    await page.getByRole("button", { name: /^Applies itself soon/ }).click();
    await page.getByRole("list", { name: "Proposals" }).getByRole("listitem").first().getByRole("link").first().click();
    const panel = page.getByRole("region", { name: "Proposal" });
    await expect(panel).toContainText("unless someone undoes it", { timeout: 20_000 });
    const openedId = new URL(page.url()).pathname.split("/").pop()!;
    expect(scheduled.map((p) => p.id)).toContain(openedId);
    await expect(panel.getByRole("button", { name: "Apply now" })).toBeVisible();

    await panel.getByRole("button", { name: "Undo" }).click();
    await expect(page.getByText("Undone. Nothing was applied; the item waits for a person.")).toBeVisible();
    await expect(panel).toContainText("Undone");
    await expect(panel.getByRole("button", { name: "Undo" })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Apply now" })).toHaveCount(0);

    // The server agrees: that proposal is UNDONE, the others are still scheduled, nothing was applied.
    const undone = await api<{ proposal: Proposal & { work_item_id: string } }>(owner.session, "GET",
      `/workspaces/${owner.wsId}/process/agent/proposals/${openedId}`);
    expect(undone.body.proposal.status).toBe("UNDONE");
    expect(await openReviews(), "the undone item still waits for a person").toBe(3);
    const stillScheduled = (await proposalsOf(owner, "?status=AUTO_SCHEDULED")).map((p) => p.id);
    expect(stillScheduled).not.toContain(openedId);
    expect(stillScheduled.length).toBe(scheduled.length - 1);
    expect(await proposalsOf(owner, "?status=APPLIED,AUTO_APPLIED")).toHaveLength(0);

    // The agent keeps its word: another sweep does not schedule that item again.
    await sweep(owner);
    expect((await proposalsOf(owner, `?subject_id=${undone.body.proposal.subject_id}`)).filter((p) => p.id !== openedId
      && ["PROPOSED", "AUTO_SCHEDULED"].includes(p.status))).toHaveLength(0);

    // Undo again is refused by the server: only a scheduled resolution can be undone.
    const twice = await api(owner.session, "POST", `/workspaces/${owner.wsId}/process/agent/proposals/${openedId}/undo`);
    expect(twice.status, twice.text).toBe(409);
    await page.reload();
    await settle(page);
    await page.getByRole("tab", { name: /^Exception agent/ }).click();
    await page.getByRole("button", { name: /^Rejected or undone/ }).click();
    await expect(page.getByRole("list", { name: "Proposals" })).toContainText("Undone");
    await expectHealthyPage(page);
  });
});

// ---------------------------------------------------------------------------------------------
// Partner manifest → marketplace
// ---------------------------------------------------------------------------------------------

interface CatalogEntry { id: string; name: string; installed: boolean; latest_manifest_id: string | null; latest_version: string | null }
interface Installation { id: string; item_name: string | null; status: string; automation_rule_id: string | null }

test.describe("Partner marketplace: manifest, listing, install, remove", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let partnerOwner: Customer;
  let client: Customer;
  let partnerId: string;
  const tag = runId();
  const ITEM = `Invoice triage ${tag}`;
  const SLUG = `invoice-triage-${tag}`.toLowerCase();
  const KEY_ID = `release-${tag}`.toLowerCase();
  const keys = crypto.generateKeyPairSync("ed25519");
  const publicPem = keys.publicKey.export({ type: "spki", format: "pem" }).toString();
  const signText = (text: string): string => crypto.sign(null, Buffer.from(text), keys.privateKey).toString("base64");

  const catalogOf = async (): Promise<CatalogEntry[]> => {
    const listed = await api<CatalogEntry[]>(client.session, "GET", `/organizations/${client.orgId}/marketplace/catalog`);
    expect(listed.status, listed.text).toBe(200);
    return listed.body.filter((entry) => entry.name === ITEM);
  };
  const installationsOf = async (): Promise<Installation[]> => {
    const listed = await api<Installation[]>(client.session, "GET", `/organizations/${client.orgId}/marketplace/installations`);
    expect(listed.status, listed.text).toBe(200);
    return listed.body.filter((entry) => entry.item_name === ITEM);
  };
  const rulesOf = async (): Promise<Array<{ id: string; is_active: boolean }>> => {
    const listed = await api<Array<{ id: string; is_active: boolean }> | { items: Array<{ id: string; is_active: boolean }> }>(
      client.session, "GET", `/workspaces/${client.wsId}/automation/rules`);
    expect(listed.status, listed.text.slice(0, 300)).toBe(200);
    return Array.isArray(listed.body) ? listed.body : listed.body.items;
  };
  /** A workflow the automation engine accepts: a trigger and a notify action (an action names its type). */
  const GRAPH = JSON.stringify({
    nodes: [
      { node_key: "start", node_type: "trigger", config: { event: "document.processed" } },
      { node_key: "notify", node_type: "action", config: { action_type: "notify", recipient: "ap@example.com" } },
    ],
    edges: [{ from_node_key: "start", to_node_key: "notify", branch: "default" }],
  }, null, 2);
  const openManifests = async (page: Page): Promise<void> => {
    await page.goto("/partners");
    await settle(page);
    await page.getByRole("button", { name: "Workflow manifests" }).click();
  };
  const itemRow = (page: Page) => page.getByRole("row").filter({ hasText: SLUG });

  test.beforeAll(async () => {
    // The partner: an organization of its own whose owner the platform administrator seats as the partner's owner
    // (there is no screen for creating a partner), and a client organization on a plan with automations that the
    // partner holds in its book (no screen for that either).
    partnerOwner = await newCustomer("partner-owner", "Partner Owner Ltd");
    client = await enterprise("partner-client", "Partner Client Ltd");
    const operator = await loginAs("P.superadmin");
    const created = await api<{ id: string }>(operator, "POST", "/partners", {
      slug: `e2e-partner-${tag}`.toLowerCase(), name: `E2E Partner ${tag}`,
      owner_organization_id: partnerOwner.orgId, owner_user_id: String(partnerOwner.session.me.id),
    });
    expect(created.status, created.text).toBe(201);
    partnerId = created.body.id;
    const assigned = await api(partnerOwner.session, "POST", `/partners/${partnerId}/book`, { organization_id: client.orgId });
    expect(assigned.status, assigned.text).toBe(201);
  });

  test.afterAll(async () => {
    // The client leaves the partner's book again; the item is withdrawn by the tests.
    if (partnerId && client) await api(partnerOwner.session, "DELETE", `/partners/${partnerId}/book/${client.orgId}`);
  });

  test("the partner registers a key, creates an item, signs and publishes a manifest, which lists it", async ({ page, problems }) => {
    problems.allowHttp(/\/partners\/[^/]+\/(signing-keys|catalog)/, [400, 409, 422], "a wrong signature and a duplicate are refused");
    await signInAs(page, partnerOwner.email);
    await openManifests(page);
    const register = page.getByRole("button", { name: "Register public key" });
    await expect(register).toBeDisabled();

    // The public key: registered, active, with its fingerprint.
    await page.getByLabel("Key id").fill(KEY_ID);
    await page.getByLabel("Public key (PEM)").fill(publicPem);
    await expect(register).toBeEnabled();
    await register.click();
    await expect(page.getByText("Signing key registered.")).toBeVisible();
    const keyRow = page.getByRole("row").filter({ hasText: KEY_ID });
    await expect(keyRow).toContainText("ACTIVE");
    const registered = await api<Array<{ key_id: string; status: string; fingerprint: string }>>(partnerOwner.session, "GET",
      `/partners/${partnerId}/signing-keys`);
    expect(registered.body.find((k) => k.key_id === KEY_ID)).toMatchObject({ status: "ACTIVE" });

    // The catalog item: created partner-only, visible only to the partner's book.
    await page.getByRole("textbox", { name: "Name", exact: true }).fill(ITEM);
    await page.getByRole("textbox", { name: "Slug" }).fill(SLUG);
    await page.getByRole("textbox", { name: "Summary" }).fill("Routes new invoices to a person");
    await page.getByRole("button", { name: "Create catalog item" }).click();
    await expect(page.getByText(`${ITEM} created.`)).toBeVisible();
    await expect(itemRow(page)).toContainText("DRAFT");
    await expect(itemRow(page)).toContainText("PARTNER_ONLY");
    const manifests = page.getByRole("region", { name: `${ITEM} — manifests` });
    await expect(manifests).toContainText("No manifest published for this item yet.");
    expect(await catalogOf(), "a draft is not in the marketplace").toHaveLength(0);

    // Visibility can be switched while it is a draft (nothing is listed yet).
    await manifests.getByRole("button", { name: "Make public" }).click();
    await expect(itemRow(page)).toContainText("PUBLIC");
    await manifests.getByRole("button", { name: "Make partner-only" }).click();
    await expect(itemRow(page)).toContainText("PARTNER_ONLY");

    // Publishing needs the digest first, an active key and a signature.
    const publish = manifests.getByRole("button", { name: "3. Verify signature and publish" });
    await expect(publish).toBeDisabled();
    await manifests.getByLabel("Signing key").selectOption(KEY_ID);
    await manifests.getByLabel("Workflow graph (JSON)").fill(GRAPH);
    await manifests.getByRole("button", { name: "1. Compute the digest to sign" }).click();
    const signingInput = (await manifests.getByText(/Sign exactly this text/).locator("xpath=following-sibling::code[1]").innerText()).trim();
    expect(signingInput.length).toBeGreaterThan(10);

    // A signature that does not belong to this manifest is refused, and nothing is published.
    await manifests.getByLabel("2. Signature (base64)").fill(signText("some other text"));
    await expect(publish).toBeEnabled();
    await publish.click();
    await expect(page.getByText(/signature|verif/i).first()).toBeVisible();
    await expect(manifests).toContainText("No manifest published for this item yet.");

    // The right signature publishes version 1.0.0.
    await manifests.getByLabel("2. Signature (base64)").fill(signText(signingInput));
    await publish.click();
    await expect(page.getByText("Version 1.0.0 published and signature verified.")).toBeVisible();
    await expect(manifests.getByRole("row").filter({ hasText: "1.0.0" })).toContainText("PUBLISHED");
    await expect(manifests.getByRole("row").filter({ hasText: "1.0.0" })).toContainText("2 nodes · 1 edges");
    await expect(itemRow(page)).toContainText("1.0.0");

    // Publishing the first manifest lists the item (as the toast on creating it says): the partner's client sees it,
    // and it is private to the partner's book.
    await expect(itemRow(page)).toContainText("PUBLISHED");
    const listed = await catalogOf();
    expect(listed).toHaveLength(1);
    expect(listed[0]).toMatchObject({ latest_version: "1.0.0", installed: false });
    await page.reload();
    await settle(page);
    await page.getByRole("button", { name: "Workflow manifests" }).click();
    await expect(itemRow(page)).toContainText("PUBLISHED");
    await expectHealthyPage(page);
  });

  test("the client reviews the signed workflow, installs it (created disabled) and removes it", async ({ page }) => {
    await signInAs(page, client.email);
    await page.goto(client.org("marketplace"));
    await settle(page);
    const card = page.getByRole("article").filter({ hasText: ITEM });
    await expect(card).toContainText("Private to your partner");
    await card.getByRole("button", { name: "Review & install" }).click();

    // What it does is shown before anything is admitted, and its signature is verified against the live key.
    const dialog = page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: ITEM }) });
    await expect(dialog.getByText("Signature verified against an active publisher key.")).toBeVisible({ timeout: 20_000 });
    await expect(dialog).toContainText("What this workflow does");
    await expect(dialog).toContainText("ap@example.com");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    expect(await installationsOf(), "Cancel installs nothing").toHaveLength(0);

    await card.getByRole("button", { name: "Review & install" }).click();
    await expect(dialog.getByText("Signature verified against an active publisher key.")).toBeVisible({ timeout: 20_000 });
    await dialog.getByRole("button", { name: "Install", exact: true }).click();
    await expect(page.getByText("Installed. The workflow is created but not enabled")).toBeVisible();

    const installed = page.getByRole("row").filter({ hasText: ITEM });
    await expect(installed).toContainText("1.0.0");
    await expect(card.getByRole("button", { name: "Installed" })).toBeDisabled();
    const [installation] = await installationsOf();
    expect(installation).toMatchObject({ status: "INSTALLED" });
    const rule = (await rulesOf()).find((r) => r.id === installation!.automation_rule_id);
    expect(rule, "an automation rule was created").toBeTruthy();
    expect(rule!.is_active, "it is created disabled").toBe(false);
    expect((await catalogOf())[0]).toMatchObject({ installed: true });

    // After a reload it is still installed.
    await page.reload();
    await settle(page);
    await expect(page.getByRole("row").filter({ hasText: ITEM })).toContainText("1.0.0");

    // Remove: the installation ends and the rule is deactivated, not deleted.
    await page.getByRole("row").filter({ hasText: ITEM }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Removed. The automation rule was deactivated, not deleted.")).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: ITEM })).toHaveCount(0);
    await expect(card.getByRole("button", { name: "Review & install" })).toBeEnabled();
    expect(await installationsOf()).toHaveLength(0);
    expect((await catalogOf())[0]).toMatchObject({ installed: false });
    expect((await rulesOf()).find((r) => r.id === installation!.automation_rule_id), "the rule is kept").toBeTruthy();
    await expectHealthyPage(page);
  });

  test("Deprecate and Withdraw take it out of the marketplace; a revoked key stops an install", async ({ page, problems }) => {
    problems.allowHttp(/\/marketplace\/installations/, [400, 403, 409, 422], "installing a manifest whose key was revoked is refused");
    await signInAs(page, partnerOwner.email);
    await openManifests(page);
    await itemRow(page).getByRole("button", { name: "Manage manifests" }).click();
    const manifests = page.getByRole("region", { name: `${ITEM} — manifests` });

    // Deprecate: the client no longer sees it. List it again and it is back.
    await manifests.getByRole("button", { name: "Deprecate" }).click();
    await expect(itemRow(page)).toContainText("DEPRECATED");
    expect(await catalogOf()).toHaveLength(0);
    await manifests.getByRole("button", { name: "List in marketplace" }).click();
    await expect(itemRow(page)).toContainText("PUBLISHED");
    expect(await catalogOf()).toHaveLength(1);

    // Revoke the signing key (a reason is required): manifests it signed no longer verify.
    const keyRow = page.getByRole("row").filter({ hasText: KEY_ID });
    await keyRow.getByRole("button", { name: "Revoke" }).click();
    const confirm = keyRow.getByRole("button", { name: "Confirm revoke" });
    await expect(confirm).toBeDisabled();
    await keyRow.getByRole("button", { name: "Cancel" }).click();
    await expect(keyRow).toContainText("ACTIVE");
    await keyRow.getByRole("button", { name: "Revoke" }).click();
    await keyRow.getByLabel("Reason for revoking").fill("Key retired in the e2e run");
    await confirm.click();
    await expect(page.getByText("Signing key revoked. Manifests it signed no longer verify.")).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: KEY_ID })).toContainText(/REVOKED/);
    const afterRevoke = await api<Array<{ key_id: string; status: string }>>(partnerOwner.session, "GET", `/partners/${partnerId}/signing-keys`);
    expect(afterRevoke.body.find((k) => k.key_id === KEY_ID)?.status).toBe("REVOKED");
    await expect(manifests.getByLabel("Signing key").locator("option", { hasText: KEY_ID })).toHaveCount(0);

    // The client is told the signature does not verify, Install is off, and the server refuses it too.
    const clientPage = await page.context().browser()!.newContext();
    try {
      const other = await clientPage.newPage();
      await signInAs(other, client.email);
      await other.goto(client.org("marketplace"));
      const card = other.getByRole("article").filter({ hasText: ITEM });
      await card.getByRole("button", { name: "Review & install" }).click();
      const dialog = other.locator("div.fixed").filter({ has: other.getByRole("heading", { name: ITEM }) });
      await expect(dialog.getByText("Signature does not verify. This workflow cannot be installed.")).toBeVisible({ timeout: 20_000 });
      await expect(dialog.getByRole("button", { name: "Install", exact: true })).toBeDisabled();
    } finally {
      await clientPage.close();
    }
    const [entry] = await catalogOf();
    const refused = await api(client.session, "POST", `/organizations/${client.orgId}/marketplace/installations`,
      { manifest_id: entry!.latest_manifest_id, workspace_id: client.wsId });
    expect(refused.status, refused.text).toBeGreaterThanOrEqual(400);
    expect(await installationsOf()).toHaveLength(0);

    // Withdraw takes it out of the marketplace for good; the button is gone afterwards.
    await manifests.getByRole("button", { name: "Withdraw" }).click();
    await expect(itemRow(page)).toContainText("WITHDRAWN");
    await expect(manifests.getByRole("button", { name: "Withdraw" })).toHaveCount(0);
    expect(await catalogOf()).toHaveLength(0);
    await page.reload();
    await settle(page);
    await page.getByRole("button", { name: "Workflow manifests" }).click();
    await expect(itemRow(page)).toContainText("WITHDRAWN");
    await expectHealthyPage(page);
  });

  test("the sample workflow the console offers, published as it is, can be installed", async ({ page }) => {
    // The console's textarea starts with a sample workflow. A partner who signs and publishes it unchanged is told
    // "published and signature verified"; the client then must be able to install it.
    const sampleKeys = crypto.generateKeyPairSync("ed25519");
    const sampleKeyId = `sample-${tag}`.toLowerCase();
    const sampleName = `Sample flow ${tag}`;
    const sampleSlug = `sample-flow-${tag}`.toLowerCase();
    let itemId: string | undefined;
    try {
      await signInAs(page, partnerOwner.email);
      await openManifests(page);
      await page.getByLabel("Key id").fill(sampleKeyId);
      await page.getByLabel("Public key (PEM)").fill(sampleKeys.publicKey.export({ type: "spki", format: "pem" }).toString());
      await page.getByRole("button", { name: "Register public key" }).click();
      await expect(page.getByText("Signing key registered.")).toBeVisible();
      await page.getByRole("textbox", { name: "Name", exact: true }).fill(sampleName);
      await page.getByRole("textbox", { name: "Slug" }).fill(sampleSlug);
      await page.getByRole("button", { name: "Create catalog item" }).click();
      await expect(page.getByText(`${sampleName} created.`)).toBeVisible();
      const manifests = page.getByRole("region", { name: `${sampleName} — manifests` });
      await manifests.getByLabel("Signing key").selectOption(sampleKeyId);
      await manifests.getByRole("button", { name: "1. Compute the digest to sign" }).click();
      const signingInput = (await manifests.getByText(/Sign exactly this text/).locator("xpath=following-sibling::code[1]").innerText()).trim();
      await manifests.getByLabel("2. Signature (base64)").fill(crypto.sign(null, Buffer.from(signingInput), sampleKeys.privateKey).toString("base64"));
      await manifests.getByRole("button", { name: "3. Verify signature and publish" }).click();
      await expect(page.getByText("Version 1.0.0 published and signature verified.")).toBeVisible();
      const catalog = await api<Array<{ id: string; name: string }>>(partnerOwner.session, "GET", `/partners/${partnerId}/catalog`);
      itemId = catalog.body.find((entry) => entry.name === sampleName)?.id;

      const clientContext = await page.context().browser()!.newContext();
      try {
        const other = await clientContext.newPage();
        await signInAs(other, client.email);
        await other.goto(client.org("marketplace"));
        await other.getByRole("article").filter({ hasText: sampleName }).getByRole("button", { name: "Review & install" }).click();
        const dialog = other.locator("div.fixed").filter({ has: other.getByRole("heading", { name: sampleName }) });
        await expect(dialog.getByText("Signature verified against an active publisher key.")).toBeVisible({ timeout: 20_000 });
        await dialog.getByRole("button", { name: "Install", exact: true }).click();
        await expect(other.getByText("Installed. The workflow is created but not enabled")).toBeVisible();
        await expect(other.getByRole("row").filter({ hasText: sampleName })).toContainText("1.0.0");
      } finally {
        await clientContext.close();
      }
    } finally {
      // Leave nothing listed: remove an installation if there is one, then withdraw the item.
      const installed = await api<Installation[]>(client.session, "GET", `/organizations/${client.orgId}/marketplace/installations`);
      for (const entry of installed.body.filter((row) => row.item_name === sampleName))
        await api(client.session, "DELETE", `/organizations/${client.orgId}/marketplace/installations/${entry.id}`);
      if (itemId) await api(partnerOwner.session, "PATCH", `/partners/${partnerId}/catalog/${itemId}`, { status: "WITHDRAWN" });
    }
  });
});

// ---------------------------------------------------------------------------------------------
// Enterprise identity credentials: the SCIM token
// ---------------------------------------------------------------------------------------------

/** What the real SCIM endpoint (the identity provider's side) says to a bearer token. */
async function scimStatus(token: string): Promise<number> {
  const response = await fetchOnce(`${API_ORIGIN}/scim/v2/Users?count=1`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/scim+json" },
  });
  await response.text();
  return response.status;
}

test.describe("Identity credentials: the SCIM token", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let owner: Customer;
  const CONNECTION = "Directory sign-in";

  test.beforeAll(async () => {
    owner = await enterprise("scim-owner", "Scim Rotation Ltd");
    // A verified domain bound to single sign-on and a SAML connection: what a SCIM token is issued for.
    const domain = `scim-${runId()}.example.com`;
    const base = `/organizations/${owner.orgId}/identity`;
    const claimed = await api<{ id: string; expected_txt_record: string }>(owner.session, "POST", `${base}/domains`, { domain });
    expect(claimed.status, claimed.text).toBe(201);
    standIn("dns-publish", null, "--name", domain, "--value", claimed.body.expected_txt_record);
    expect((await api(owner.session, "POST", `${base}/domains/${claimed.body.id}/verify`, {})).status).toBe(200);
    expect((await api(owner.session, "POST", `${base}/domains/${claimed.body.id}/bind-sso`, {})).status).toBe(200);
    const idp = standIn("saml-idp", null, "--domain", domain) as { entity_id: string; sso_url: string };
    const created = await api(owner.session, "POST", `${base}/idp-configs`, {
      verified_domain_id: claimed.body.id, protocol: "SAML2", display_name: CONNECTION,
      idp_entity_id: idp.entity_id, idp_sso_url: idp.sso_url,
    });
    expect(created.status, created.text).toBe(201);
  });

  const keysOf = async (): Promise<Array<{ id: string; revoked_at: string | null; previous_secret_expires_at: string | null; last_used_at: string | null }>> => {
    const listed = await api<Array<{ id: string; revoked_at: string | null; previous_secret_expires_at: string | null; last_used_at: string | null }>>(
      owner.session, "GET", `/organizations/${owner.orgId}/identity/scim-keys`);
    expect(listed.status, listed.text).toBe(200);
    return listed.body;
  };
  const readToken = async (page: Page): Promise<string> => {
    const dialog = page.getByRole("dialog", { name: "Copy this token now" });
    await expect(dialog).toBeVisible();
    const token = (await dialog.locator("code").innerText()).trim();
    const done = dialog.getByRole("button", { name: "Done" });
    await expect(done).toBeDisabled();                       // not until the token is acknowledged as stored
    await dialog.getByRole("checkbox", { name: "I have stored this token somewhere safe." }).check();
    await done.click();
    await expect(dialog).toHaveCount(0);
    return token;
  };

  test("Issue, Rotate and Revoke: each token is checked against the real SCIM endpoint", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.org("identity?tab=scim"));
    await settle(page);
    await expect(page.getByText("No SCIM tokens yet.")).toBeVisible();

    // Issue: needs a provider; the token is shown once and works.
    const issue = page.getByRole("button", { name: "Issue token" });
    await expect(issue).toBeDisabled();
    await page.getByLabel("Identity provider for new token").selectOption({ label: CONNECTION });
    await issue.click();
    const first = await readToken(page);
    expect(await scimStatus(first), "the issued token opens the directory").toBe(200);
    expect(await scimStatus(`${first}x`), "a token that is not one is refused").toBeGreaterThanOrEqual(401);
    const [key] = await keysOf();
    expect(key!.revoked_at).toBeNull();
    await expect(page.getByText("The previous secret still works")).toHaveCount(0);

    // Rotate: a new token, shown once. The old one keeps working for the overlap the page announces.
    await page.getByRole("button", { name: "Rotate", exact: true }).click();
    const second = await readToken(page);
    expect(second).not.toBe(first);
    expect(await scimStatus(second), "the new token opens the directory").toBe(200);
    expect(await scimStatus(first), "the previous token still works during the overlap").toBe(200);
    await expect(page.getByText("The previous secret still works")).toBeVisible();
    expect((await keysOf())[0]!.previous_secret_expires_at).not.toBeNull();
    await page.reload();
    await settle(page);
    await expect(page.getByText("The previous secret still works")).toBeVisible();
    await expect(page.locator("main")).not.toContainText(second);   // a token is never shown again

    // Rotate again: the first token is now gone for good; the one before the newest stays for the overlap.
    await page.getByRole("button", { name: "Rotate", exact: true }).click();
    const third = await readToken(page);
    expect(new Set([first, second, third]).size).toBe(3);
    expect(await scimStatus(third), "the newest token works").toBe(200);
    expect(await scimStatus(second), "the one before it works during the overlap").toBe(200);
    expect(await scimStatus(first), "the first token stopped working").toBeGreaterThanOrEqual(401);

    // Revoke asks first: Cancel keeps the token.
    await page.getByRole("button", { name: "Revoke SCIM" }).click();
    const confirm = page.getByRole("dialog", { name: "Revoke this token?" });
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toHaveCount(0);
    expect(await scimStatus(third)).toBe(200);
    expect((await keysOf())[0]!.revoked_at).toBeNull();

    // Revoke: every token of the key stops at once, including the overlap token, and the row says so.
    await page.getByRole("button", { name: "Revoke SCIM" }).click();
    await confirm.getByRole("button", { name: "Revoke", exact: true }).click();
    await expect(page.getByText("SCIM token revoked. Your identity provider can no longer use it.")).toBeVisible();
    await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Rotate", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Revoke SCIM" })).toHaveCount(0);
    expect(await scimStatus(third), "the newest token stopped").toBeGreaterThanOrEqual(401);
    expect(await scimStatus(second), "revoking ends the overlap token too").toBeGreaterThanOrEqual(401);
    expect((await keysOf())[0]!.revoked_at).not.toBeNull();
    await page.reload();
    await settle(page);
    await expect(page.getByText("Revoked", { exact: true })).toBeVisible();

    // A revoked token cannot be rotated back to life.
    const rotated = await api(owner.session, "POST", `/organizations/${owner.orgId}/identity/scim-keys/${key!.id}/rotate`);
    if (rotated.status === 200 || rotated.status === 201) {
      const body = rotated.body as { token?: string };
      expect(await scimStatus(String(body.token)), "a revoked key must stay revoked after Rotate").toBeGreaterThanOrEqual(401);
    }
    await expectHealthyPage(page);
  });

  test("only the organization's owner has the buttons, and the server refuses an admin", async ({ page }) => {
    const admin = await addMember(owner, "scim-admin", "ADMIN", "ADMIN");
    await signInAs(page, admin.email);
    await page.goto(owner.org("identity?tab=scim"));
    await settle(page);
    await expect(page.getByRole("heading", { name: "Access restricted" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Issue token" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Rotate", exact: true })).toHaveCount(0);
    const [key] = await keysOf();
    const base = `/organizations/${owner.orgId}/identity/scim-keys`;
    expect((await api(admin.session, "POST", `${base}/${key!.id}/rotate`)).status).toBe(403);
    expect((await api(admin.session, "DELETE", `${base}/${key!.id}`)).status).toBe(403);
    expect((await api(admin.session, "POST", base, { idp_config_id: key!.id })).status).toBe(403);
  });
});
