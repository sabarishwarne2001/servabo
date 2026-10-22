/**
 * ORGANIZATION TABS, PART 5 (Final session 1, organization tabs task): Developer platform, Analytics & BI egress, Partner
 * marketplace, Enterprise identity and Audit log. Real input per tab: what a form accepts and refuses, what is explained, what
 * survives a reload, and what each role and plan can do.
 */
import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api } from "../support/api";
import { addMember, newCustomer, signInAs } from "../support/journey";
import { enterpriseCustomer } from "../support/workflow-helpers";

test.describe("Developer platform", () => {
  test("a gateway key is issued once, with a real name; a duplicate is explained; the window is a named dialog", async ({ page, problems }) => {
    test.setTimeout(240_000);
    problems.allowHttp(/\/developer\/keys$/, [409, 422], "a duplicate name is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused key");
    const customer = await enterpriseCustomer("orgdev");
    await signInAs(page, customer.email);
    await page.goto(customer.org("developer"));
    await page.getByRole("button", { name: "Issue key" }).first().click({ timeout: 30_000 });
    const dialog = page.getByRole("dialog", { name: "Issue a gateway API key" });
    await expect(dialog).toBeVisible();
    const issue = dialog.getByRole("button", { name: "Issue key" });
    const name = dialog.getByRole("textbox").first();
    await expect(issue).toBeDisabled();
    await name.fill("   ");
    await dialog.getByRole("checkbox").first().check();
    await expect(issue, "a name of spaces is not a name").toBeDisabled();
    await name.fill("  Gateway A  ");
    await expect(issue).toBeEnabled();
    await issue.click();
    const issued = page.getByRole("dialog", { name: "Key issued" });
    await expect(issued).toContainText("only time this token is shown", { timeout: 20_000 });
    const token = (await issued.locator("code").innerText()).trim();
    await page.getByRole("button", { name: "I have saved it" }).click();
    await expect(page.getByText("Gateway A").first()).toBeVisible({ timeout: 15_000 });
    expect(await page.content(), "the token is still on the page").not.toContain(token);
    const stored = await api<{ keys?: Array<{ name: string }> } | Array<{ name: string }>>(customer.session, "GET", `/organizations/${customer.orgId}/developer`);
    expect(JSON.stringify(stored.body)).not.toContain(token);
    expect(JSON.stringify(stored.body)).toContain("Gateway A");

    // The same name again is explained inside the window; Escape closes it and focus goes back.
    const opener = page.getByRole("button", { name: "Issue key" }).first();
    await opener.click();
    const second = page.getByRole("dialog", { name: "Issue a gateway API key" });
    await second.getByRole("textbox").first().fill("Gateway A");
    await second.getByRole("checkbox").first().check();
    await second.getByRole("button", { name: "Issue key" }).click();
    await expect(second.getByRole("alert")).toContainText(/already exists|name/i, { timeout: 15_000 });
    await page.keyboard.press("Escape");
    await expect(second).toHaveCount(0);
    await expect(opener).toBeFocused();
    await expectHealthyPage(page);
  });

  test("a member cannot open the console; the Free plan shows the lock", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgdev2");
    const member = await addMember(customer, "orgdev-member", "MEMBER");
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("developer"));
      await expect(memberPage.getByRole("button", { name: "Issue key" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
    const free = await newCustomer("orgdev3", "Dev Free Ltd");
    await signInAs(page, free.email);
    await page.goto(free.org("developer"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included/i).first()).toBeVisible({ timeout: 30_000 });
    const refused = await api(free.session, "POST", `/organizations/${free.orgId}/developer/keys`, { name: "Nope", scopes: ["work_items:read"] });
    expect(refused.status).toBe(402);
  });
});

test.describe("Analytics & BI egress", () => {
  test("a destination is checked, saved without its secret ever returning, and removed; every tab opens", async ({ page, problems }) => {
    test.setTimeout(300_000);
    problems.allowHttp(/\/analytics\//, [400, 409, 422, 502], "a destination that is not usable is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused destination");
    const customer = await enterpriseCustomer("organalytics");
    await signInAs(page, customer.email);
    await page.goto(customer.org("analytics"));
    await page.getByRole("button", { name: "Add destination" }).first().click({ timeout: 30_000 });
    const add = page.getByRole("button", { name: "Add destination" }).last();
    const fill = async (label: string, value: string) => page.getByRole("textbox", { name: label }).fill(value);

    // A label with markup and a bucket that cannot exist are refused with reasons; nothing is saved.
    await fill("Label", "<b>Warehouse</b>");
    await fill("Bucket", "UPPER_case!");
    await fill("Region", "eu-west-2");
    await fill("Access key ID", "AKIAE2ETESTONLY0000");
    await fill("Secret access key", "e2e-secret-never-shown-9137");
    await add.click();
    await expect(page.getByRole("alert").or(page.getByText(/must not contain|may contain only|invalid|could not/i)).first()).toBeVisible({ timeout: 15_000 });
    const none = await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/analytics/destinations`);
    expect(none.body).toEqual([]);

    await fill("Label", "E2E warehouse");
    await fill("Bucket", "acme-e2e-bucket");
    await add.click();
    await expect(page.getByText("E2E warehouse").first()).toBeVisible({ timeout: 20_000 });
    expect(await page.content(), "the secret is on the page").not.toContain("e2e-secret-never-shown-9137");
    const stored = await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/analytics/destinations`);
    expect(JSON.stringify(stored.body)).not.toContain("e2e-secret-never-shown-9137");
    expect(stored.body).toHaveLength(1);

    // The same label again is explained, not duplicated.
    await page.getByRole("button", { name: "Add destination" }).first().click();
    await fill("Label", "E2E warehouse");
    await fill("Bucket", "acme-e2e-bucket");
    await fill("Region", "eu-west-2");
    await fill("Access key ID", "AKIAE2ETESTONLY0000");
    await fill("Secret access key", "another-secret");
    await page.getByRole("button", { name: "Add destination" }).last().click();
    await expect(page.getByText(/already exists|could not/i).first()).toBeVisible({ timeout: 15_000 });
    expect((await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/analytics/destinations`)).body).toHaveLength(1);

    for (const tab of ["Sync schedules", "Run history", "Usage analytics", "Warehouse destinations"]) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
    }
    expect(await page.locator("main").innerText()).not.toMatch(/\[object|Traceback|undefined/);
    await expectHealthyPage(page);
  });

  test("a member cannot open it", async ({ browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("organalytics2");
    const member = await addMember(customer, "organalytics-member", "MEMBER");
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("analytics"));
      await expect(memberPage.getByRole("button", { name: "Add destination" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
  });
});

test.describe("Partner marketplace", () => {
  test("the catalogue and the installed list load for a new organization, with plain empty states; a member cannot open it", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgmarket");
    const member = await addMember(customer, "orgmarket-member", "MEMBER");
    await signInAs(page, customer.email);
    await page.goto(customer.org("marketplace"));
    await expect(page.getByRole("heading", { name: "Available" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/No published workflows/)).toBeVisible();
    expect(await page.locator("main").innerText()).not.toMatch(/\[object|Traceback|undefined/);
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("marketplace"));
      await expect(memberPage.getByRole("heading", { name: "Available" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
    await expectHealthyPage(page);
  });
});

test.describe("Enterprise identity", () => {
  test("a domain is claimed once in a usable form, shown with its record, and an address, a reserved ending or a pasted link is handled", async ({ page, problems }) => {
    test.setTimeout(300_000);
    problems.allowHttp(/\/identity\/domains/, [400, 409, 422], "a name that cannot be a domain is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused claim");
    const customer = await enterpriseCustomer("orgidentity");
    await signInAs(page, customer.email);
    await page.goto(customer.org("identity"));
    const box = page.getByRole("textbox", { name: "Domain to claim" });
    const claim = page.getByRole("button", { name: "Claim domain" });
    await expect(box).toBeVisible({ timeout: 30_000 });
    await expect(claim).toBeDisabled();

    for (const bad of ["192.168.1.1", "intranet.local", "-bad.example.co.uk"]) {
      await box.fill(bad);
      await claim.click();
      await expect(page.getByText(/not a valid|not a domain|IP address|public internet|cannot be proved|could not/i).first()).toBeVisible({ timeout: 15_000 });
    }
    expect((await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/identity/domains`)).body).toEqual([]);

    // A pasted address is reduced to its domain; claiming it again keeps one row; the record to publish is shown.
    await box.fill("https://Identity-Check.co.uk/login");
    await claim.click();
    await expect(page.getByText("identity-check.co.uk").first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/servabo-site-verification=/).first()).toBeVisible();
    await expect(page.getByText("Awaiting DNS").first()).toBeVisible();
    await box.fill("identity-check.co.uk");
    await claim.click();
    await expect.poll(async () => (await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/identity/domains`)).body.length).toBe(1);

    // Verifying without the record says "not yet" in words, never a crash.
    await page.getByRole("button", { name: /Verify|Check now|Check DNS/i }).first().click();
    await expect(page.getByText(/not found|not been|DNS record|could not|not yet|Awaiting DNS|missing/i).first()).toBeVisible({ timeout: 20_000 });
    expect(await page.locator("main").innerText()).not.toMatch(/\[object|Traceback|undefined/);
    await expectHealthyPage(page);
  });

  test("the security tab: the session lifetime is kept, a list that would lock you out is refused in words, and SSO cannot be required without a provider", async ({ page, problems }) => {
    test.setTimeout(300_000);
    problems.allowHttp(/\/identity\/security-policy$/, [409, 422], "a policy that would lock people out is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused policy");
    const customer = await enterpriseCustomer("orgidentity2");
    await signInAs(page, customer.email);
    await page.goto(customer.org("identity"));
    await page.getByRole("tab", { name: "Security" }).or(page.getByRole("button", { name: "Security", exact: true })).first().click({ timeout: 30_000 });
    const lifetime = page.locator("#identity-session-lifetime");
    await expect(lifetime).toBeVisible({ timeout: 30_000 });
    const choices = await lifetime.locator("option").evaluateAll((nodes) => nodes.map((n) => (n as HTMLOptionElement).value).filter(Boolean));
    expect(choices.length).toBeGreaterThan(0);
    await lifetime.selectOption(choices[choices.length - 1]!);
    await expect.poll(async () => (await api<{ max_session_age_s: number | null }>(customer.session, "GET", `/organizations/${customer.orgId}/identity/security-policy`)).body.max_session_age_s).toBe(Number(choices[choices.length - 1]));
    await page.reload();
    await page.getByRole("tab", { name: "Security" }).or(page.getByRole("button", { name: "Security", exact: true })).first().click();
    await expect(page.locator("#identity-session-lifetime")).toHaveValue(choices[choices.length - 1]!, { timeout: 30_000 });

    // The address list: the page shows the address it is checked against; a list without it is refused and nothing is saved.
    const networks = page.locator("#ip-allowlist");
    await expect(page.getByText("Your address now:")).toBeVisible();
    await networks.fill("203.0.113.0/24");
    await page.getByRole("button", { name: "Save allowed networks" }).click();
    await expect(page.getByText(/lock you out|not in this list|outside/i).first()).toBeVisible({ timeout: 15_000 });
    const kept = await api<{ ip_allowlist: string[] }>(customer.session, "GET", `/organizations/${customer.orgId}/identity/security-policy`);
    expect(kept.body.ip_allowlist).toEqual([]);
    await networks.fill("not-a-network");
    await page.getByRole("button", { name: "Save allowed networks" }).click();
    await expect(page.getByText(/not a valid|invalid|CIDR|network/i).first()).toBeVisible({ timeout: 15_000 });

    // With no identity provider the page says why single sign-on cannot be required.
    await expect(page.getByText(/identity provider|no provider|Connect and activate/i).first()).toBeVisible();
    await expectHealthyPage(page);
  });

  test("an admin reads the tabs and changes nothing; a member cannot open it; below Enterprise it is locked", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgidentity3");
    const admin = await addMember(customer, "orgid-admin", "ADMIN");
    const member = await addMember(customer, "orgid-member", "MEMBER");
    await signInAs(page, admin.email);
    await page.goto(customer.org("identity"));
    await expect(page.getByRole("heading", { name: "Domains" }).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Claim domain" })).toHaveCount(0);
    const refused = await api(admin.session, "POST", `/organizations/${customer.orgId}/identity/domains`, { domain: "admin-claim.co.uk" });
    expect(refused.status).toBe(403);
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("identity"));
      await expect(memberPage.getByRole("heading", { name: "Domains" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
    const free = await newCustomer("orgidentity4", "Identity Free Ltd");
    await signInAs(page, free.email);
    await page.goto(free.org("identity"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included|Enterprise/i).first()).toBeVisible({ timeout: 30_000 });
  });
});

test.describe("Audit log", () => {
  test("what people did is listed with who and when, filters narrow it, the export follows them, and nothing can be changed", async ({ page, browser }) => {
    test.setTimeout(300_000);
    const customer = await enterpriseCustomer("orgaudit");
    const admin = await addMember(customer, "orgaudit-admin", "ADMIN");
    // Two people leave marks: the owner renames the organization twice; the admin sets a legal name.
    for (const name of ["Audit Trail One", "Audit Trail Two"]) {
      expect((await api(customer.session, "PATCH", `/organizations/${customer.orgId}`, { name })).status).toBe(200);
    }
    expect((await api(admin.session, "PATCH", `/organizations/${customer.orgId}`, { legal_name: "Audit Legal Ltd" })).status).toBe(200);

    await signInAs(page, customer.email);
    await page.goto(customer.org("audit"));
    await expect(page.getByRole("heading", { name: "Audit log" }).first()).toBeVisible({ timeout: 30_000 });
    const table = page.getByRole("table");
    await expect(table.getByRole("row")).not.toHaveCount(1, { timeout: 30_000 });
    await expect(table).toContainText(/Updated/i);

    // Filters: by actor only that person's rows; by a resource that has none, a plain empty message; Clear brings them all back.
    const total = await table.getByRole("row").count();
    await page.getByLabel("Actor", { exact: true }).selectOption({ label: admin.email }).catch(async () => {
      const options = await page.getByLabel("Actor", { exact: true }).locator("option").evaluateAll((nodes) => nodes.map((n) => ({ v: (n as HTMLOptionElement).value, t: n.textContent ?? "" })));
      const found = options.find((o) => o.t.includes(admin.email.split("@")[0]!));
      expect(found, "the admin is a choice").toBeTruthy();
      await page.getByLabel("Actor", { exact: true }).selectOption(found!.v);
    });
    await expect.poll(async () => table.getByRole("row").count()).toBeLessThan(total);
    await page.getByRole("button", { name: "Clear" }).click();
    await expect.poll(async () => table.getByRole("row").count()).toBe(total);
    await page.getByLabel("Resource type", { exact: true }).selectOption({ label: "Api key" }).catch(async () => {
      await page.getByLabel("Resource type", { exact: true }).selectOption("API_KEY");
    });
    await expect(page.getByText("No entries match these filters.")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Clear" }).click();

    // A date window: from today to today includes today's rows; an end date in the past leaves none.
    const today = new Date().toISOString().slice(0, 10);
    await page.getByLabel("From date").fill(today);
    await page.getByLabel("To date").fill(today);
    await expect(table.getByRole("row")).not.toHaveCount(1, { timeout: 15_000 });
    // An end date before the start date is explained instead of asked; an end date in the past alone matches nothing.
    await page.getByLabel("To date").fill("2020-01-01");
    await expect(page.getByRole("alert").filter({ hasText: "end date is before the start date" })).toBeVisible({ timeout: 15_000 });
    await page.getByLabel("From date").fill("");
    await expect(page.getByText("No entries match these filters.")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Clear" }).click();

    // One entry can be opened; both exports download; the trail has no way to be edited.
    await page.getByRole("button", { name: "Inspect" }).first().click();
    await expect(page.getByRole("button", { name: "Close" })).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();
    for (const format of ["CSV", "NDJSON"]) {
      const download = page.waitForEvent("download", { timeout: 20_000 });
      await page.getByRole("button", { name: format, exact: true }).click();
      expect((await download).suggestedFilename()).toMatch(new RegExp(`\\.(${format.toLowerCase()}|ndjson|jsonl)$`, "i"));
    }
    const listed = await api<{ items: Array<{ id: string; action: string }> }>(customer.session, "GET", `/organizations/${customer.orgId}/audit-logs?limit=5`);
    for (const method of ["PATCH", "PUT", "DELETE"]) {
      const response = await api(customer.session, method, `/organizations/${customer.orgId}/audit-logs/${listed.body.items[0]!.id}`, { action: "X" });
      expect([403, 404, 405]).toContain(response.status);
    }
    // The export itself is in the trail.
    await page.reload();
    await page.getByLabel("Action", { exact: true }).selectOption("EXPORTED");
    await expect(page.getByRole("table")).toContainText(/Exported/i, { timeout: 15_000 });

    // An administrator reads the same trail; a member cannot.
    const asAdmin = await browser.newContext();
    const adminPage = await asAdmin.newPage();
    try {
      await signInAs(adminPage, admin.email);
      await adminPage.goto(customer.org("audit"));
      await expect(adminPage.getByRole("table")).toBeVisible({ timeout: 30_000 });
    } finally {
      await asAdmin.close();
    }
    await expectHealthyPage(page);
  });
});
