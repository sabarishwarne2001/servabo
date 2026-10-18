/**
 * ACCOUNT AND ORGANIZATION SECURITY BUTTONS (campaign Session C, long tail).
 *
 * Four things nothing in the browser pressed, each on people created for the test:
 *  - "New recovery codes" in Settings → two-factor sign-in: a wrong code is refused, a right one gives ten
 *    new codes, the old unused ones stop working at sign-in and a new one works;
 *  - the organization's "Require two-factor sign-in…" (with "Not now") and "Stop requiring two-factor
 *    sign-in": members without two-factor are named, are refused by the server while it is required, and
 *    are let back in when it stops;
 *  - "Decline invitation": the invitee is not added, and the invitation can no longer be accepted;
 *  - "Leave organization" for a member who holds no workspace: the membership ends.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, apiLogin, fetchOnce } from "../support/api";
import { signUpVerified } from "../support/accounts";
import { API_BASE, PASSWORD, runId } from "../support/env";
import { addMember, newCustomer, signInAs } from "../support/journey";
import { linkFrom, waitForMail } from "../support/mail";
import { totpCode } from "../support/totp";

/** Password step of a sign-in through the API: the challenge for a person with two-factor on. */
async function challengeFor(email: string): Promise<string> {
  const response = await fetchOnce(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password: PASSWORD }).toString(),
  });
  const body = (await response.json()) as { mfa_required?: boolean; mfa_token?: string };
  expect(body.mfa_required, "the password alone must not sign in").toBe(true);
  return String(body.mfa_token);
}

async function signInWithCode(email: string, code: string): Promise<number> {
  const response = await fetchOnce(`${API_BASE}/auth/login/mfa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_token: await challengeFor(email), code }),
  });
  return response.status;
}

test.describe("New recovery codes", () => {
  test.setTimeout(180_000);

  test("a wrong app code is refused; a right one gives ten new codes and the old ones stop working", async ({ page, problems }) => {
    problems.allowHttp(/\/me\/mfa\/recovery-codes$/, [400, 401, 403, 422], "a wrong code is refused");
    problems.allowHttp(/\/auth\/login\/mfa$/, [400, 401], "a spent recovery code is refused");
    const customer = await newCustomer("mfa-codes", "Recovery Codes Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings"));
    const panel = page.getByRole("region", { name: "Two-factor sign-in" });
    await expect(panel.getByTestId("mfa-state")).toContainText("Off.", { timeout: 15_000 });
    await panel.getByRole("button", { name: "Turn on two-factor sign-in" }).click();
    await panel.getByLabel("Current password").fill(PASSWORD);
    await panel.getByRole("button", { name: "Continue" }).click();
    const secret = (await panel.getByTestId("mfa-secret").innerText()).replace(/\s/g, "");
    await panel.getByLabel("6-digit code from the app").fill(totpCode(secret));
    await panel.getByRole("button", { name: "Turn on", exact: true }).click();
    const listed = async (): Promise<string[]> =>
      (await panel.getByRole("list", { name: "Recovery codes" }).getByRole("listitem").allInnerTexts()).map((text) => text.trim());
    await expect(panel.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
    const oldCodes = await listed();
    await panel.getByRole("button", { name: "I have saved them" }).click();
    await expect(panel.getByTestId("mfa-state")).toContainText("On. 10 recovery codes left.");

    // A wrong code is refused, and Cancel leaves everything as it was.
    await panel.getByRole("button", { name: "New recovery codes" }).click();
    await panel.getByLabel("6-digit code from the app").fill("000000");
    await panel.getByRole("button", { name: "Get new codes" }).click();
    await expect(panel.getByRole("alert")).toContainText("That code is not right");
    await panel.getByRole("button", { name: "Cancel" }).click();
    await expect(panel.getByTestId("mfa-state")).toContainText("On. 10 recovery codes left.");

    // A right one (the app's next code: the step shown at turn-on is spent) replaces them.
    await panel.getByRole("button", { name: "New recovery codes" }).click();
    await panel.getByLabel("6-digit code from the app").fill(totpCode(secret, Date.now() + 30_000));
    await panel.getByRole("button", { name: "Get new codes" }).click();
    await expect(panel).toContainText("New recovery codes are ready. The old ones no longer work.");
    await expect(panel.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
    const newCodes = await listed();
    expect(new Set(newCodes).size).toBe(10);
    expect(newCodes.filter((code) => oldCodes.includes(code))).toEqual([]);
    await panel.getByRole("button", { name: "I have saved them" }).click();
    await expect(panel.getByTestId("mfa-state")).toContainText("On. 10 recovery codes left.");

    // At sign-in: an old code is refused, a new one is accepted (once).
    expect(await signInWithCode(customer.email, oldCodes[0]!)).toBeGreaterThanOrEqual(400);
    expect(await signInWithCode(customer.email, newCodes[0]!)).toBe(200);
    expect(await signInWithCode(customer.email, newCodes[0]!), "a recovery code works once").toBeGreaterThanOrEqual(400);
    await page.reload();
    await settle(page);
    await expect(page.getByRole("region", { name: "Two-factor sign-in" }).getByTestId("mfa-state")).toContainText("On. 9 recovery codes left.");
    await expectHealthyPage(page);
  });
});

test.describe("Requiring two-factor sign-in for the organization", () => {
  test.setTimeout(180_000);

  test("Not now changes nothing; Require names who is affected and the server refuses them; Stop lets them back in", async ({ page, problems }) => {
    problems.allowHttp(/\/api\/v1\//, [403], "a member without two-factor is refused while it is required");
    const owner = await newCustomer("org-mfa", "Org MFA Ltd");
    const member = await addMember(owner, "org-mfa-member", "MEMBER", "CONTRIBUTOR");
    const intoOrganization = async (): Promise<{ status: number; code?: string }> => {
      const session = await apiLogin(member.email);
      const response = await api<{ code?: string; detail?: { code?: string } }>(session, "GET", `/workspaces/${owner.wsId}/work-items?page_size=1`);
      return { status: response.status, code: response.body?.code ?? response.body?.detail?.code };
    };
    const required = async (): Promise<boolean> =>
      (await api<{ required: boolean }>(owner.session, "GET", `/organizations/${owner.orgId}/two-factor-policy`)).body.required;

    await signInAs(page, owner.email);
    await page.goto(owner.org("settings"));
    await settle(page);
    const card = page.locator("section").filter({ has: page.getByRole("heading", { name: "Two-factor sign-in", exact: true }) });
    await expect(card).toContainText("Not required.");
    await expect(card).toContainText("not turned it on yet");
    await expect(card.getByRole("list", { name: "Members without two-factor sign-in" })).toContainText(member.email);
    expect((await intoOrganization()).status).toBe(200);

    // Not now: the confirmation closes and nothing is required.
    await card.getByRole("button", { name: "Require two-factor sign-in…" }).click();
    await expect(card).toContainText("will be asked to turn it on before they can continue");
    await card.getByRole("button", { name: "Not now" }).click();
    await expect(card.getByRole("button", { name: "Require two-factor sign-in…" })).toBeVisible();
    expect(await required()).toBe(false);

    // The owner must have two-factor on first, so requiring it cannot lock the owner out.
    problems.allowHttp(/\/two-factor-policy$/, [409], "the owner has not turned on two-factor yet");
    await card.getByRole("button", { name: "Require two-factor sign-in…" }).click();
    await card.getByRole("button", { name: "Require two-factor sign-in", exact: true }).click();
    await expect(card.getByRole("alert")).toContainText("Turn on two-factor sign-in for your own account first");
    expect(await required()).toBe(false);
    const setup = await api<{ secret?: string; manual_entry_key?: string }>(owner.session, "POST", "/me/mfa/setup", { password: PASSWORD });
    expect(setup.status, setup.text).toBeLessThan(300);
    const secret = String(setup.body.secret ?? setup.body.manual_entry_key ?? "").replace(/\s/g, "");
    const confirmed = await api(owner.session, "POST", "/me/mfa/confirm", { code: totpCode(secret) });
    expect(confirmed.status, confirmed.text).toBeLessThan(300);

    // Require: saved, the member is refused by the server.
    await page.reload();
    await settle(page);
    await card.getByRole("button", { name: "Require two-factor sign-in…" }).click();
    await card.getByRole("button", { name: "Require two-factor sign-in", exact: true }).click();
    await expect(card).toContainText("Required for every member.");
    await expect.poll(required).toBe(true);
    expect(await intoOrganization()).toMatchObject({ status: 403, code: "ORGANIZATION_MFA_REQUIRED" });
    await page.reload();
    await settle(page);
    await expect(card).toContainText("Required for every member.");

    // Stop requiring: one click, saved, the member is let back in.
    await card.getByRole("button", { name: "Stop requiring two-factor sign-in" }).click();
    await expect(card).toContainText("Not required.");
    await expect.poll(required).toBe(false);
    expect((await intoOrganization()).status).toBe(200);
    await expectHealthyPage(page);
  });
});

test.describe("Invitations the invitee does not take", () => {
  test.setTimeout(180_000);

  test("Decline invitation: nobody is added, and the invitation can no longer be accepted", async ({ page, problems }) => {
    problems.allowHttp(/\/invitations\//, [400, 404, 409, 410], "a declined invitation is gone");
    const owner = await newCustomer("decline", "Decline Ltd");
    const email = `decliner-${runId()}@e2e.example.com`;
    const person = await signUpVerified(email);
    const since = Date.now() - 1_000;
    const invited = await api<{ id: string }>(owner.session, "POST", `/organizations/${owner.orgId}/invitations`, {
      email, organization_role: "MEMBER", grants: [{ workspace_id: owner.wsId, role: "VIEWER" }],
    });
    expect(invited.status, invited.text).toBe(201);
    const link = linkFrom(await waitForMail(email, /invitations\/accept/, since), /invitations\/accept/);

    await signInAs(page, email);
    await page.goto(link);
    await expect(page.getByRole("heading", { name: /^Join Decline Ltd/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Accept and join" })).toBeVisible();
    await page.getByRole("button", { name: "Decline invitation" }).click();
    await expect(page.getByRole("button", { name: "Decline invitation" })).toHaveCount(0, { timeout: 20_000 });

    const members = await api<{ items: Array<{ user?: { email?: string } }> }>(owner.session, "GET", `/organizations/${owner.orgId}/members`);
    expect(members.body.items.map((m) => m.user?.email)).not.toContain(email);
    const pending = await api<Array<{ id: string; email: string }>>(owner.session, "GET", `/organizations/${owner.orgId}/invitations?status=PENDING`);
    expect((Array.isArray(pending.body) ? pending.body : []).map((row) => row.email)).not.toContain(email);

    // Opening the link again no longer offers to join.
    await page.goto(link);
    await expect(page.getByRole("button", { name: "Accept and join" })).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(`Join Decline Ltd`);
    const context = await api<{ organizations: Array<{ organization_slug: string }> }>(person, "GET", "/me/context");
    expect(context.body.organizations.map((o) => o.organization_slug)).not.toContain(owner.orgSlug);
    await expectHealthyPage(page);
  });
});

test.describe("Leaving an organization", () => {
  test.setTimeout(180_000);

  test("a member who holds no workspace can leave it from the picker, and the membership ends", async ({ page }) => {
    const owner = await newCustomer("leave-org", "Leave Org Ltd");
    const email = `leaver-${runId()}@e2e.example.com`;
    const person = await signUpVerified(email);
    const since = Date.now() - 1_000;
    const invited = await api(owner.session, "POST", `/organizations/${owner.orgId}/invitations`, {
      email, organization_role: "MEMBER", grants: [],
    });
    expect(invited.status, invited.text).toBe(201);
    const { tokenOf } = await import("../support/accounts");
    const accepted = await api(person, "POST", "/invitations/accept", {
      token: tokenOf(linkFrom(await waitForMail(email, /invitations\/accept/, since), /invitations\/accept/)),
    });
    expect(accepted.status, accepted.text).toBe(200);

    await signInAs(page, email);
    await page.goto("/workspaces");
    const card = page.getByRole("article", { name: "Leave Org Ltd" });
    await expect(card).toContainText("You do not have access to any workspace in this organization yet.");
    await card.getByRole("button", { name: "Leave organization" }).click();
    await expect(page.getByRole("article", { name: "Leave Org Ltd" })).toHaveCount(0, { timeout: 20_000 });

    const context = await api<{ organizations: Array<{ organization_slug: string }> }>(await apiLogin(email), "GET", "/me/context");
    expect(context.body.organizations.map((o) => o.organization_slug)).not.toContain(owner.orgSlug);
    const members = await api<{ items: Array<{ user?: { email?: string }; status?: string }> }>(owner.session, "GET", `/organizations/${owner.orgId}/members`);
    expect(members.body.items.filter((m) => m.user?.email === email && (m.status ?? "ACTIVE") === "ACTIVE")).toEqual([]);
    await page.reload();
    await expect(page.getByRole("article", { name: "Leave Org Ltd" })).toHaveCount(0);
    await expectHealthyPage(page);
  });
});
