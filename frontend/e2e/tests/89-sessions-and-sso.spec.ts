/**
 * SESSIONS AND SINGLE SIGN-ON ENFORCEMENT (Settings → Sessions; Organization → Enterprise identity).
 *
 * Sessions. A new person signs in from two other "devices" (their own browsers' user agents), then in
 * the real page: "End session" ends one of them (its refresh token stops working, the other one and
 * this page carry on); "Sign out" on this device ends only this session; "Sign out everywhere" (asked
 * to confirm, cancellable) ends every session, signs this page out, and every other device's refresh
 * token is refused afterwards. Only ever done to people created here, never a seeded one.
 *
 * Enterprise identity. An owner connects a SAML provider (the stand-in provider of
 * backend/scripts/e2e_stand_in.py, the same as spec 63), cannot require single sign-on before it is
 * active (page and server), saves role mappings ("Save mapping") that persist and resolve through the
 * dry run, and requires single sign-on. A member then meets the "Single sign-on required" notice on a
 * password session and gets back in through the provider; the sign-in page sends the member's address
 * to the provider; the owner keeps working on a password (break-glass) until that is switched off, and
 * then is stopped too. Admins and members are refused by the server and shown "Access restricted".
 */
import type { Page } from "@playwright/test";

import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api, apiLogin, fetchOnce, type ApiSession } from "../support/api";
import { signUpVerified, tokenOf } from "../support/accounts";
import { API_BASE, PASSWORD, runId } from "../support/env";
import { newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { linkFrom, waitForMail } from "../support/mail";

// ---------------------------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------------------------

const UA_PHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const UA_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:120.0) Gecko/20100101 Firefox/120.0";
const PHONE = "Safari on iPhone";
const MAC = "Firefox on macOS";

interface Device {
  readonly userAgent: string;
  readonly accessToken: string;
  readonly refreshToken: string;
}

interface SessionRow {
  readonly id: string;
  readonly user_agent: string | null;
}

/** Sign in over the API as a browser on another device would: its own user agent, its own session. */
async function signInFrom(email: string, userAgent: string): Promise<Device> {
  const response = await fetchOnce(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": userAgent },
    body: new URLSearchParams({ username: email, password: PASSWORD }).toString(),
  });
  const text = await response.text();
  expect(response.status, text).toBe(200);
  const cookie = (response.headers.getSetCookie?.() ?? []).find((entry) => entry.startsWith("servabo_refresh="));
  expect(cookie, "the login set the refresh cookie").toBeTruthy();
  const refreshToken = (cookie ?? "").split(";")[0]!.slice("servabo_refresh=".length);
  return { userAgent, accessToken: (JSON.parse(text) as { access_token: string }).access_token, refreshToken };
}

/** What the server says to a refresh token: 200 (still a live session) or 401 (ended). */
async function refreshStatus(refreshToken: string): Promise<number> {
  const response = await fetchOnce(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { Cookie: `servabo_refresh=${refreshToken}` },
  });
  await response.text();
  return response.status;
}

async function meStatus(accessToken: string): Promise<number> {
  const response = await fetchOnce(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${accessToken}` } });
  await response.text();
  return response.status;
}

async function sessionsOf(session: ApiSession): Promise<SessionRow[]> {
  const listed = await api<SessionRow[]>(session, "GET", "/auth/sessions");
  expect(listed.status, listed.text).toBe(200);
  return listed.body;
}

const sessionIdOf = async (session: ApiSession, userAgent: string): Promise<string | undefined> =>
  (await sessionsOf(session)).find((row) => row.user_agent === userAgent)?.id;

const sessionsPath = (customer: Customer): string => customer.ws("settings?section=sessions");

test.describe("Sessions", () => {
  test.setTimeout(180_000);

  test("End session on another device ends only that device", async ({ page }) => {
    const customer = await newCustomer("sess-end", "Sessions End Ltd");
    const phone = await signInFrom(customer.email, UA_PHONE);
    const mac = await signInFrom(customer.email, UA_MAC);
    const phoneId = await sessionIdOf(customer.session, UA_PHONE);
    expect(phoneId, "the phone's session is listed").toBeTruthy();

    await signInAs(page, customer.email);
    await page.goto(sessionsPath(customer));
    await expect(page.getByRole("heading", { name: "Active sessions" })).toBeVisible();
    await expect(page.getByRole("button", { name: `End session on ${PHONE}` })).toBeVisible();
    await expect(page.getByRole("button", { name: `End session on ${MAC}` })).toBeVisible();
    // This page's own session is the one marked, and it is offered "Sign out", not "End session".
    const here = page.getByRole("listitem").filter({ hasText: "This device" });
    await expect(here).toHaveCount(1);
    await expect(here.getByRole("button", { name: "Sign out of this device" })).toBeVisible();

    await page.getByRole("button", { name: `End session on ${PHONE}` }).click();
    await expect(page.getByRole("button", { name: `End session on ${PHONE}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `End session on ${MAC}` })).toBeVisible();

    // The server agrees: the phone's refresh token and its access token no longer work, the
    // other device's still does, and the list no longer carries the phone.
    expect(await refreshStatus(phone.refreshToken)).toBe(401);
    expect(await meStatus(phone.accessToken)).toBe(401);
    expect((await sessionsOf(customer.session)).map((row) => row.id)).not.toContain(phoneId);
    expect(await refreshStatus(mac.refreshToken)).toBe(200);

    // This page is still signed in after a reload, and the list stays without the phone.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Active sessions" })).toBeVisible();
    await expect(page.getByRole("button", { name: `End session on ${PHONE}` })).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("the server refuses to end someone else's session, and one that does not exist", async () => {
    const customer = await newCustomer("sess-refuse", "Sessions Refuse Ltd");
    const stranger = await newCustomer("sess-stranger", "Sessions Stranger Ltd");
    const device = await signInFrom(customer.email, UA_PHONE);
    const victimId = await sessionIdOf(customer.session, UA_PHONE);
    expect(victimId).toBeTruthy();

    const foreign = await api(stranger.session, "DELETE", `/auth/sessions/${victimId}`);
    expect(foreign.status, foreign.text).toBe(404);
    const missing = await api(customer.session, "DELETE", "/auth/sessions/00000000-0000-4000-8000-000000000000");
    expect(missing.status, missing.text).toBe(404);
    expect(await sessionIdOf(customer.session, UA_PHONE), "the session is still listed").toBe(victimId);
    expect(await refreshStatus(device.refreshToken)).toBe(200);
  });

  test("Sign out on this device ends this session and leaves the others", async ({ page }) => {
    const customer = await newCustomer("sess-here", "Sessions Here Ltd");
    const mac = await signInFrom(customer.email, UA_MAC);

    await signInAs(page, customer.email);
    await page.goto(sessionsPath(customer));
    await expect(page.getByRole("heading", { name: "Active sessions" })).toBeVisible();
    const here = page.getByRole("listitem").filter({ hasText: "This device" });
    await expect(here).toHaveCount(1);
    await here.getByRole("button", { name: "Sign out of this device" }).click();
    await expect(page).toHaveURL(/\/login/);

    // Signed out in the browser: the protected page sends it back to the sign-in page.
    await page.goto(sessionsPath(customer));
    await expect(page).toHaveURL(/\/login/);
    // The other device is untouched, and the account itself still signs in.
    expect(await refreshStatus(mac.refreshToken)).toBe(200);
    await apiLogin(customer.email);
  });

  test("Sign out everywhere asks first, then ends every session including this page's", async ({ page, problems }) => {
    problems.allowHttp(/\/auth\/refresh$/, [401], "the browser has no session left to renew once signed out everywhere");
    const customer = await newCustomer("sess-all", "Sessions All Ltd");
    const phone = await signInFrom(customer.email, UA_PHONE);
    const mac = await signInFrom(customer.email, UA_MAC);
    expect(await meStatus(customer.session.accessToken)).toBe(200);

    await signInAs(page, customer.email);
    await page.goto(sessionsPath(customer));
    await expect(page.getByRole("heading", { name: "Active sessions" })).toBeVisible();

    // Changing one's mind costs nothing: Cancel leaves everything as it was.
    await page.getByRole("button", { name: "Sign out everywhere" }).click();
    await expect(page.getByText("Yes, sign out everywhere")).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Yes, sign out everywhere" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Sign out everywhere" })).toBeVisible();
    expect(await refreshStatus(phone.refreshToken), "cancelling ended nothing").toBe(200);
    // That refresh rotated the token; keep the new one for the later check of the same device.
    const phoneAgain = await signInFrom(customer.email, UA_PHONE);

    await page.getByRole("button", { name: "Sign out everywhere" }).click();
    await page.getByRole("button", { name: "Yes, sign out everywhere" }).click();
    await expect(page).toHaveURL(/\/login/);

    // The browser holds no session any more...
    await expect
      .poll(async () => (await page.context().cookies()).filter((cookie) => cookie.name === "servabo_refresh" && cookie.value).length)
      .toBe(0);
    await page.goto(sessionsPath(customer));
    await expect(page).toHaveURL(/\/login/);

    // ...and neither does any other device: every refresh token is refused, as are the old access tokens.
    for (const [name, device] of [["phone", phoneAgain], ["mac", mac]] as const) {
      expect(await refreshStatus(device.refreshToken), `${name}'s refresh token`).toBe(401);
      expect(await meStatus(device.accessToken), `${name}'s access token`).toBe(401);
    }
    expect(await refreshStatus(phone.refreshToken), "the rotated phone token").toBe(401);
    expect(await meStatus(customer.session.accessToken), "the API session that created the account").toBe(401);

    // Nothing is locked: the person simply signs in again, with one session.
    const again = await apiLogin(customer.email);
    expect(await sessionsOf(again)).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------------------------
// Single sign-on enforcement
// ---------------------------------------------------------------------------------------------

const CONNECTION = "Company sign-in";

interface Person {
  readonly email: string;
}

/** A person at the company's email domain who joins the organization (before sign-in is locked down). */
async function joinAt(owner: Customer, email: string, organizationRole: string, workspaceRole: string): Promise<Person> {
  const person = await signUpVerified(email);
  const since = Date.now() - 1_000;
  const invited = await api(owner.session, "POST", `/organizations/${owner.orgId}/invitations`, {
    email,
    organization_role: organizationRole,
    grants: [{ workspace_id: owner.wsId, role: workspaceRole }],
  });
  expect(invited.status, invited.text).toBe(201);
  const mail = await waitForMail(email, /invitations\/accept/, since);
  const accepted = await api(person, "POST", "/invitations/accept", { token: tokenOf(linkFrom(mail, /invitations\/accept/)) });
  expect(accepted.status, accepted.text).toBe(200);
  return { email };
}

interface Provider {
  entity_id: string;
  sso_url: string;
  certificate: string;
}

/**
 * An Enterprise customer whose company domain is proved and bound to sign-in by SSO, with the
 * company's own people already in the organization (once SSO is required, new people cannot be
 * invited by password). The owner is an ordinary customer: their address is not at the company's
 * domain, and the seeded people share e2e.example.com, which must never be bound to a provider.
 */
async function setUpCompany(
  label: string,
  name: string,
  joiners: ReadonlyArray<{ prefix: string; organizationRole: string; workspaceRole: string }>,
): Promise<{ owner: Customer; domain: string; idp: Provider; people: Person[] }> {
  const owner = await newCustomer(label, name);
  standIn("subscribe", owner.orgSlug, "--plan", "enterprise", "--seats", "10");
  const domain = `sso-${runId()}.example.com`;
  const people: Person[] = [];
  for (const joiner of joiners) {
    people.push(await joinAt(owner, `${joiner.prefix}-${runId()}@${domain}`, joiner.organizationRole, joiner.workspaceRole));
  }
  // The domain, proved at the company's DNS provider (stand-in), bound to sign-in by SSO.
  const claimed = await api<{ id: string; expected_txt_record: string }>(owner.session, "POST",
    `/organizations/${owner.orgId}/identity/domains`, { domain });
  expect(claimed.status, claimed.text).toBe(201);
  standIn("dns-publish", null, "--name", domain, "--value", claimed.body.expected_txt_record);
  const verified = await api(owner.session, "POST", `/organizations/${owner.orgId}/identity/domains/${claimed.body.id}/verify`, {});
  expect(verified.status, verified.text).toBe(200);
  const bound = await api(owner.session, "POST", `/organizations/${owner.orgId}/identity/domains/${claimed.body.id}/bind-sso`, {});
  expect(bound.status, bound.text).toBe(200);
  const idp = standIn("saml-idp", null, "--domain", domain) as unknown as Provider;
  return { owner, domain, idp, people };
}

/**
 * The provider's two pages, answered here: Servabo's /sso/start redirect is read (it must name the
 * configured provider) and followed; the provider's sign-in page signs `email` in and posts the signed
 * answer to Servabo's ACS (stand-in: backend/scripts/e2e_stand_in.py saml-response). With
 * `completeSignIn` false the provider's page is only a landing page, so a test can see where the
 * browser was sent.
 */
async function standInProvider(page: Page, domain: string, email: string, completeSignIn: boolean): Promise<void> {
  await page.route(/\/api\/v1\/sso\/start/, async (route) => {
    const response = await route.fetch({ maxRedirects: 0 });
    const location = response.headers()["location"] ?? "";
    expect(response.status(), await response.text()).toBe(302);
    expect(location.startsWith(`http://idp.${domain}/sso?SAMLRequest=`), location).toBe(true);
    await route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><meta http-equiv="refresh" content="0;url=${location.replace(/"/g, "&quot;")}">`,
    });
  });
  await page.route(new RegExp(`^http://idp\\.${domain.replace(/\./g, "\\.")}/sso`), async (route) => {
    if (!completeSignIn) {
      await route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Identity provider</title><h1>Identity provider sign-in</h1>" });
      return;
    }
    const url = new URL(route.request().url());
    const answer = standIn("saml-response", null, "--domain", domain, "--email", email,
      "--saml-request", url.searchParams.get("SAMLRequest") ?? "") as { acs_url: string; saml_response: string };
    const relay = url.searchParams.get("RelayState");
    await route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><title>Identity provider</title><form method="post" action="${answer.acs_url}">`
        + `<input type="hidden" name="SAMLResponse" value="${answer.saml_response}">`
        + (relay ? `<input type="hidden" name="RelayState" value="${relay.replace(/"/g, "&quot;")}">` : "")
        + "</form><script>document.forms[0].submit()</script>",
    });
  });
}

interface Policy {
  require_sso: boolean;
  sso_bypass_for_owners: boolean;
}

interface Refusal {
  detail?: unknown;
  code?: unknown;
  error?: { code?: unknown } | undefined;
}

const refusalCode = (body: Refusal | string): string => JSON.stringify(body);

test.describe("Single sign-on enforcement", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(300_000);

  let owner: Customer;
  let domain: string;
  let admin: Person;
  let member: Person;
  let idp: Provider;

  const policyPath = (): string => `/organizations/${owner.orgId}/identity/security-policy`;
  const identity = (tab: string): string => owner.org(`identity?tab=${tab}`);
  const requireSso = (page: Page) => page.getByRole("checkbox", { name: /Require single sign-on/ });
  const bypass = (page: Page) => page.getByRole("checkbox", { name: /Owners can bypass SSO/ });
  const policy = async (): Promise<Policy> => {
    const read = await api<Policy>(await apiLogin(owner.email), "GET", policyPath());
    expect(read.status, read.text).toBe(200);
    return read.body;
  };
  const connectionRow = (page: Page) => page.getByRole("button", { name: new RegExp(CONNECTION) });
  const openConnection = async (page: Page): Promise<void> => {
    await expect(connectionRow(page)).toBeVisible({ timeout: 15_000 });
    if ((await connectionRow(page).getAttribute("aria-expanded")) !== "true") await connectionRow(page).click();
    await expect(page.getByRole("button", { name: "Save mapping" })).toBeVisible();
  };
  /** The work-items list of the organization's workspace: any request into the organization does. */
  const intoOrganization = (who: ApiSession) => api<Refusal | unknown[]>(who, "GET", `/workspaces/${owner.wsId}/work-items?limit=1`);
  const requireThroughTheCheckbox = async (page: Page): Promise<void> => {
    await requireSso(page).click();
    await page.getByRole("button", { name: "Require single sign-on", exact: true }).click();
    await expect(requireSso(page)).toBeChecked();
    await expect.poll(async () => (await policy()).require_sso).toBe(true);
  };

  test.beforeAll(async () => {
    const company = await setUpCompany("sso-owner", "Sso Policy Corp", [
      { prefix: "sso-admin", organizationRole: "ADMIN", workspaceRole: "ADMIN" },
      { prefix: "sso-member", organizationRole: "MEMBER", workspaceRole: "CONTRIBUTOR" },
    ]);
    ({ owner, domain, idp } = company);
    [admin, member] = company.people as [Person, Person];
  });

  test("the owner connects the provider; requiring single sign-on waits until it is active", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(identity("sso"));
    await page.getByRole("button", { name: "Add connection" }).click();
    await page.getByRole("group", { name: "Protocol" }).getByRole("button", { name: "SAML 2.0" }).click();
    await page.getByLabel("Name").fill(CONNECTION);
    await page.getByLabel("Verified domain").selectOption({ label: domain });
    await page.getByLabel("Entity ID").fill(idp.entity_id);
    await page.getByLabel("SSO URL").fill(idp.sso_url);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(connectionRow(page)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Not activated")).toBeVisible();
    if ((await connectionRow(page).getAttribute("aria-expanded")) !== "true") await connectionRow(page).click();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await page.getByLabel("Certificate PEM").fill(idp.certificate);
    await page.getByRole("button", { name: "Add certificate" }).click();
    await expect(page.getByLabel("Certificate PEM")).toHaveCount(0);

    // With a provider that is not active, the option explains itself and the server refuses it too.
    await page.goto(identity("security"));
    await expect(requireSso(page)).toBeDisabled();
    await expect(page.getByText("Connect and activate an identity provider under Single sign-on first")).toBeVisible();
    const refused = await api(await apiLogin(owner.email), "PUT", policyPath(), { require_sso: true });
    expect(refused.status, refused.text).toBe(409);
    expect((await policy()).require_sso).toBe(false);

    // Activate it from the connection, and the option opens up.
    await page.goto(identity("sso"));
    await openConnection(page);
    await page.getByRole("button", { name: "Activate connection" }).click();
    await expect(page.getByText(/The connection is active/)).toBeVisible({ timeout: 15_000 });
    const configs = await api<Array<{ display_name: string; is_active: boolean }>>(
      await apiLogin(owner.email), "GET", `/organizations/${owner.orgId}/identity/idp-configs`);
    expect(configs.body.find((config) => config.display_name === CONNECTION)?.is_active).toBe(true);
    await page.goto(identity("security"));
    await expect(requireSso(page)).toBeEnabled();
    await expect(requireSso(page)).not.toBeChecked();
    await expectHealthyPage(page);
  });

  test("Save mapping keeps a role mapping: it persists after a reload and decides the role in the dry run", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(identity("sso"));
    await openConnection(page);

    // Nothing to save without a value; OWNER cannot be granted by a provider (it is not offered).
    await expect(page.getByRole("button", { name: "Save mapping" })).toBeDisabled();
    await expect(page.getByLabel("Organization role").locator("option")).toHaveText(["MEMBER", "BILLING", "ADMIN"]);

    await page.getByLabel("Attribute name").fill("groups");
    await page.getByLabel("Match kind").selectOption({ label: "equals" });
    await page.getByLabel("Match value").fill("servabo-admins");
    await page.getByLabel("Organization role").selectOption("ADMIN");
    await page.getByRole("button", { name: "Save mapping" }).click();
    await expect(page.getByText("Role mapping saved. It applies from the next sign-in.")).toBeVisible();

    // Through the API, as the owner: the mapping decides the role; anything else is the default.
    const owned = await apiLogin(owner.email);
    const config = (await api<Array<{ id: string; display_name: string }>>(
      owned, "GET", `/organizations/${owner.orgId}/identity/idp-configs`)).body.find((c) => c.display_name === CONNECTION);
    expect(config, "the connection exists").toBeTruthy();
    const dryRun = async (groups: string[]): Promise<string> => {
      const result = await api<{ resolved_role: string }>(owned, "POST",
        `/organizations/${owner.orgId}/identity/idp-configs/${config!.id}/dry-run`, { attributes: { groups } });
      expect(result.status, result.text).toBe(200);
      return result.body.resolved_role;
    };
    expect(await dryRun(["servabo-admins"])).toBe("ADMIN");
    expect(await dryRun(["nobody"])).toBe("MEMBER");

    // After a reload the page still resolves them: it asks the server, which kept the rule.
    await page.reload();
    await openConnection(page);
    const resolves = async (sample: string, role: string): Promise<void> => {
      await page.getByLabel("Sample attribute values").fill(sample);
      await page.getByRole("button", { name: "Dry run" }).click();
      await expect(page.getByText("Resolved role").locator("xpath=following-sibling::dd[1]")).toHaveText(role);
    };
    await resolves("servabo-admins", "ADMIN");
    await resolves("someone-else", "MEMBER");

    // The server's own refusals: ownership cannot be granted, a mapping needs a value.
    const owning = await api(owned, "POST", `/organizations/${owner.orgId}/identity/idp-configs/${config!.id}/role-mappings`,
      { attribute_name: "groups", match_kind: "EQUALS", match_value: "x", organization_role: "OWNER", priority: 100 });
    expect(owning.status, owning.text).toBe(422);
    const blank = await api(owned, "POST", `/organizations/${owner.orgId}/identity/idp-configs/${config!.id}/role-mappings`,
      { attribute_name: "groups", match_kind: "EQUALS", match_value: "  ", organization_role: "ADMIN", priority: 100 });
    expect(blank.status, blank.text).toBe(422);
    expect(await dryRun(["servabo-admins"]), "refused mappings changed nothing").toBe("ADMIN");
    await expectHealthyPage(page);
  });

  test("admins and members cannot change sign-in policy or role mappings: the server refuses, the page says so", async ({ page }) => {
    const owned = await apiLogin(owner.email);
    const config = (await api<Array<{ id: string }>>(owned, "GET", `/organizations/${owner.orgId}/identity/idp-configs`)).body[0];
    expect(config).toBeTruthy();
    const base = `/organizations/${owner.orgId}/identity`;

    for (const [label, who] of [["admin", admin], ["member", member]] as const) {
      const session = await apiLogin(who.email);
      const changePolicy = await api(session, "PUT", `${base}/security-policy`, { require_sso: true });
      expect(changePolicy.status, `${label} require SSO: ${changePolicy.text.slice(0, 200)}`).toBe(403);
      const dropBypass = await api(session, "PUT", `${base}/security-policy`, { sso_bypass_for_owners: false });
      expect(dropBypass.status, `${label} drop bypass: ${dropBypass.text.slice(0, 200)}`).toBe(403);
      const mapping = await api(session, "POST", `${base}/idp-configs/${config!.id}/role-mappings`,
        { attribute_name: "groups", match_kind: "EQUALS", match_value: `${label}-grab`, organization_role: "ADMIN", priority: 1 });
      expect(mapping.status, `${label} role mapping: ${mapping.text.slice(0, 200)}`).toBe(403);
      const activate = await api(session, "POST", `${base}/idp-configs/${config!.id}/activate`);
      expect(activate.status, `${label} activate: ${activate.text.slice(0, 200)}`).toBe(403);
    }
    // An admin may read the policy (the console's data); a plain member may not.
    expect((await api(await apiLogin(admin.email), "GET", `${base}/security-policy`)).status).toBe(200);
    expect((await api(await apiLogin(member.email), "GET", `${base}/security-policy`)).status).toBe(403);
    expect(await policy()).toMatchObject({ require_sso: false, sso_bypass_for_owners: true });
    const grabbed = await api<{ resolved_role: string }>(owned, "POST", `${base}/idp-configs/${config!.id}/dry-run`,
      { attributes: { groups: ["admin-grab", "member-grab"] } });
    expect(grabbed.body.resolved_role, "no refused mapping was kept").toBe("MEMBER");

    // In the browser an admin is told the page is for owners, and no setting is offered.
    await signInAs(page, admin.email);
    await page.goto(identity("security"));
    await expect(page.getByTestId("access-restricted")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /Require single sign-on/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Save mapping" })).toHaveCount(0);
  });

  test("the owner requires single sign-on; a member on a password is stopped and signs in through the provider", async ({ page, problems }) => {
    problems.allowHttp(/\/api\/v1\//, [403], "the organization requires single sign-on and this session is a password session");
    // The owner turns it on, after being told that owners keep their password.
    const ownerPage = await page.context().newPage();
    await signInAs(ownerPage, owner.email);
    await ownerPage.goto(identity("security"));
    await requireSso(ownerPage).click();
    await expect(ownerPage.getByText("Owners can still use their password (break-glass access is on).")).toBeVisible();
    await ownerPage.getByRole("button", { name: "Not now" }).click();
    expect((await policy()).require_sso, "Not now changed nothing").toBe(false);
    await requireThroughTheCheckbox(ownerPage);
    await ownerPage.reload();
    await expect(requireSso(ownerPage)).toBeChecked();
    await expect(bypass(ownerPage)).toBeChecked();
    await ownerPage.close();

    // The server: a password session of a member or admin is refused with the SSO code; the owner's works.
    const refusedMember = await intoOrganization(await apiLogin(member.email));
    expect(refusedMember.status, refusedMember.text.slice(0, 200)).toBe(403);
    expect(refusalCode(refusedMember.body as Refusal), "the refusal names single sign-on").toContain("ORGANIZATION_SSO_REQUIRED");
    const refusedAdmin = await intoOrganization(await apiLogin(admin.email));
    expect(refusedAdmin.status, refusedAdmin.text.slice(0, 200)).toBe(403);
    expect((await intoOrganization(await apiLogin(owner.email))).status, "break-glass: the owner's password works").toBe(200);

    // The browser: the member's password session meets one notice, with the way in.
    await signInAs(page, member.email);
    await standInProvider(page, domain, member.email, true);
    await page.goto(owner.ws());
    const notice = page.getByRole("dialog", { name: "Single sign-on required" });
    await expect(notice).toBeVisible({ timeout: 20_000 });
    await expect(notice).toContainText("requires SSO authentication");
    await expect(notice.getByRole("button", { name: "Choose another organization" })).toBeVisible();

    // "Sign in with single sign-on" goes to the provider and returns to the page the member was on.
    await notice.getByRole("button", { name: "Sign in with single sign-on" }).click();
    await expect(page).toHaveURL(new RegExp(`${owner.wsSlug}`), { timeout: 45_000 });
    await expect(page.getByRole("dialog", { name: "Single sign-on required" })).toHaveCount(0, { timeout: 30_000 });
    await expect(page.locator("main")).toContainText(/Main|Upload/, { timeout: 30_000 });
    await expectHealthyPage(page);
  });

  test("the sign-in page sends a member of the organization to the provider; the owner signs in with a password", async ({ page }) => {
    // The member's address is at the company's domain: no password step, the provider is offered at once.
    await standInProvider(page, domain, member.email, false);
    await page.goto("/login");
    await page.getByRole("textbox", { name: "Email" }).fill(member.email);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(new RegExp(`^http://idp\\.${domain.replace(/\./g, "\\.")}/sso\\?SAMLRequest=`), { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Identity provider sign-in" })).toBeVisible();

    // The owner's address is elsewhere: the password form, and break-glass lets it through.
    await page.goto("/login");
    await page.getByRole("textbox", { name: "Email" }).fill(owner.email);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(page).toHaveURL(/\/workspaces/, { timeout: 30_000 });
    await page.goto(owner.ws());
    await expect(page.getByRole("dialog", { name: "Single sign-on required" })).toHaveCount(0);
    await expect(page.locator("main")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("switching the requirement off lets a member's password back in, and on again for the last step", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(identity("security"));
    await expect(requireSso(page)).toBeChecked();
    await requireSso(page).click();
    await expect(requireSso(page)).not.toBeChecked();
    await expect.poll(async () => (await policy()).require_sso).toBe(false);
    expect((await intoOrganization(await apiLogin(member.email))).status, "passwords work again").toBe(200);
    await page.reload();
    await expect(requireSso(page)).not.toBeChecked();

    await requireThroughTheCheckbox(page);
    expect((await intoOrganization(await apiLogin(member.email))).status).toBe(403);
  });

  test("turning the owners' bypass off is confirmed, and then stops the owner's password too", async ({ page, problems }) => {
    problems.allowHttp(/\/api\/v1\//, [403], "break-glass is off and this owner's session is a password session");
    await signInAs(page, owner.email);
    await page.goto(identity("security"));
    await expect(bypass(page)).toBeChecked();

    // Keeping it on changes nothing.
    await bypass(page).click();
    await expect(page.getByText("If your identity provider becomes unavailable, nobody will be able to sign in")).toBeVisible();
    await page.getByRole("button", { name: "Keep bypass on" }).click();
    await expect(page.getByRole("button", { name: "I understand — turn it off" })).toHaveCount(0);
    await expect(bypass(page)).toBeChecked();
    expect((await policy()).sso_bypass_for_owners).toBe(true);

    // Turning it off needs the second confirmation, and is saved.
    await bypass(page).click();
    await page.getByRole("button", { name: "I understand — turn it off" }).click();
    await expect(bypass(page)).not.toBeChecked();
    await page.reload();
    await expect(page.getByRole("dialog", { name: "Single sign-on required" })).toBeVisible({ timeout: 20_000 });

    // The owner's password now meets the same wall as everyone's. Their address is not at the company's
    // domain, so the notice says plainly that no provider answers for it, instead of sending them nowhere.
    const ownerSession = await apiLogin(owner.email);
    const stopped = await api<Refusal>(ownerSession, "GET", policyPath());
    expect(stopped.status, stopped.text.slice(0, 200)).toBe(403);
    expect(stopped.text).toContain("ORGANIZATION_SSO_REQUIRED");
    const notice = page.getByRole("dialog", { name: "Single sign-on required" });
    await notice.getByRole("button", { name: "Sign in with single sign-on" }).click();
    await expect(notice.getByRole("alert")).toContainText("No identity provider is connected for");
    await notice.getByRole("button", { name: "Choose another organization" }).click();
    await expect(page).toHaveURL(/\/workspaces/);
  });
});

test.describe("Role mappings — more than one", () => {
  test.setTimeout(240_000);

  test("Save mapping can be used again for a second rule on the same connection", async ({ page }) => {
    const { owner, domain, idp } = await setUpCompany("sso-maps", "Sso Mappings Corp", []);
    const session = await apiLogin(owner.email);
    const base = `/organizations/${owner.orgId}/identity`;
    const domains = await api<Array<{ id: string; domain: string }>>(session, "GET", `${base}/domains`);
    const created = await api<{ id: string }>(session, "POST", `${base}/idp-configs`, {
      verified_domain_id: domains.body.find((row) => row.domain === domain)?.id,
      protocol: "SAML2",
      display_name: CONNECTION,
      idp_entity_id: idp.entity_id,
      idp_sso_url: idp.sso_url,
    });
    expect(created.status, created.text).toBe(201);
    const dryRun = async (groups: string[]): Promise<string> => {
      const result = await api<{ resolved_role: string }>(session, "POST", `${base}/idp-configs/${created.body.id}/dry-run`,
        { attributes: { groups } });
      expect(result.status, result.text).toBe(200);
      return result.body.resolved_role;
    };

    await signInAs(page, owner.email);
    await page.goto(owner.org("identity?tab=sso"));
    const row = page.getByRole("button", { name: new RegExp(CONNECTION) });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.click();

    await page.getByLabel("Match value").fill("servabo-admins");
    await page.getByLabel("Organization role").selectOption("ADMIN");
    await page.getByRole("button", { name: "Save mapping" }).click();
    await expect.poll(() => dryRun(["servabo-admins"])).toBe("ADMIN");

    // A second rule for another group: the owner changes the value and role and saves again.
    await page.getByLabel("Match kind").selectOption({ label: "prefix" });
    await page.getByLabel("Match value").fill("fin-");
    await page.getByLabel("Organization role").selectOption("BILLING");
    await page.getByRole("button", { name: "Save mapping" }).click();
    await expect.poll(() => dryRun(["fin-ops"]), { message: "the second mapping was saved" }).toBe("BILLING");
    expect(await dryRun(["servabo-admins"]), "the first mapping is still in force").toBe("ADMIN");
  });
});
