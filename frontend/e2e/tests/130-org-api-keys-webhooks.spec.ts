/**
 * ORGANIZATION TABS, PART 4 (Final session 1, organization tabs task): API keys and Webhooks. Real input per tab: secrets shown
 * once and never again, what a name or address may be, what is explained when something is refused, a revoked key that stops
 * working, and what each role and plan can do.
 */
import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api } from "../support/api";
import { addMember, newCustomer, signInAs } from "../support/journey";
import { enterpriseCustomer } from "../support/workflow-helpers";

test.describe("API keys", () => {
  test("a key needs a name and a permission, shows its secret once, is told apart from another by name, rotates and is revoked", async ({ page, problems }) => {
    test.setTimeout(300_000);
    problems.allowHttp(/\/api-keys$/, [409, 422], "a duplicate name or a past expiry is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused key");
    const customer = await enterpriseCustomer("orgkeys");
    await signInAs(page, customer.email);
    await page.goto(customer.org("api-keys"));
    await expect(page.getByText("No API keys")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "New key" }).click();
    const create = page.getByRole("button", { name: "Create key" });
    const name = page.getByRole("textbox", { name: "Name" });
    await expect(create).toBeDisabled();
    await name.fill("   ");
    await page.getByRole("checkbox", { name: "work_items:read" }).check();
    await expect(create, "a name of spaces is not a name").toBeDisabled();
    await name.fill("  Ledger sync  ");
    await expect(create).toBeEnabled();
    // The earliest expiry offered is tomorrow: a key that has already expired never works.
    const expiry = page.locator("#key-expiry");
    const min = await expiry.getAttribute("min");
    expect(min && min > new Date().toISOString().slice(0, 10)).toBeTruthy();

    await create.click();
    const secret = page.getByRole("region", { name: "New API key" });
    await expect(secret).toContainText("Copy this key now", { timeout: 15_000 });
    const token = (await secret.locator("code").innerText()).trim();
    expect(token.length).toBeGreaterThan(24);
    await expect(secret).toContainText("Ledger sync");
    // The key works with exactly the permission it was given, and only then.
    const headers = { Authorization: `Bearer ${token}` };
    const base = `${process.env.E2E_API_ORIGIN ?? "http://127.0.0.1:8000"}/api/v1`;
    const reader = await fetch(`${base}/workspaces/${customer.wsId}/work-items`, { headers });
    expect(reader.status).toBe(200);
    const tooMuch = await fetch(`${base}/organizations/${customer.orgId}/api-keys`, { headers });
    expect([401, 403]).toContain(tooMuch.status);
    await page.getByRole("button", { name: "I've saved it" }).click();
    expect(await page.content(), "the secret is still on the page").not.toContain(token);

    // A second key with the same name (even with other spaces) is explained, not created.
    await page.getByRole("button", { name: "New key" }).click();
    await name.fill("Ledger sync ");
    await page.getByRole("checkbox", { name: "work_items:read" }).check();
    await create.click();
    await expect(page.getByRole("alert").filter({ hasText: /already exists|name/i })).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Cancel" }).click();
    const listed = await api<Array<{ name: string }>>(customer.session, "GET", `/organizations/${customer.orgId}/api-keys`);
    expect(listed.body.map((k) => k.name)).toEqual(["Ledger sync"]);

    // Reload: no secret anywhere. Rotate: a new secret, the old one overlaps. Revoke: asks first, then stops it at once.
    await page.reload();
    await expect(page.getByText("Ledger sync")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/won.t be shown again/)).toHaveCount(0);
    await page.getByRole("button", { name: "Rotate" }).first().click();
    const rotated = page.getByRole("region", { name: "New API key" });
    await expect(rotated).toContainText("Copy this key now", { timeout: 15_000 });
    const newToken = (await rotated.locator("code").innerText()).trim();
    expect(newToken).not.toBe(token);
    await page.getByRole("button", { name: "I've saved it" }).click();
    expect((await fetch(`${base}/workspaces/${customer.wsId}/work-items`, { headers: { Authorization: `Bearer ${newToken}` } })).status).toBe(200);
    await page.getByRole("button", { name: "Revoke Ledger sync" }).click();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Revoke Ledger sync" })).toBeVisible();
    await page.getByRole("button", { name: "Revoke Ledger sync" }).click();
    await page.getByRole("button", { name: "Confirm revoke" }).click();
    await expect(page.getByRole("heading", { name: "Revoked" })).toBeVisible({ timeout: 15_000 });
    expect([401, 403]).toContain((await fetch(`${base}/workspaces/${customer.wsId}/work-items`, { headers: { Authorization: `Bearer ${newToken}` } })).status);
    // A revoked key's name is free again.
    await page.getByRole("button", { name: "New key" }).click();
    await name.fill("Ledger sync");
    await page.getByRole("checkbox", { name: "work_items:read" }).check();
    await create.click();
    await expect(page.getByRole("region", { name: "New API key" })).toBeVisible({ timeout: 15_000 });
    await expectHealthyPage(page);
  });

  test("an admin may manage keys, a member sees nothing of them, and the Free plan shows the lock", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgkeys2");
    const admin = await addMember(customer, "orgkeys-admin", "ADMIN");
    const member = await addMember(customer, "orgkeys-member", "MEMBER");
    await signInAs(page, admin.email);
    await page.goto(customer.org("api-keys"));
    await expect(page.getByRole("button", { name: "New key" })).toBeVisible({ timeout: 30_000 });
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("api-keys"));
      await expect(memberPage.getByRole("button", { name: "New key" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
    const free = await newCustomer("orgkeys3", "Keys Free Ltd");
    await signInAs(page, free.email);
    await page.goto(free.org("api-keys"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included/i).first()).toBeVisible({ timeout: 30_000 });
    const refused = await api(free.session, "POST", `/organizations/${free.orgId}/api-keys`, { name: "Nope", scopes: ["work_items:read"] });
    expect(refused.status).toBe(402);
  });
});

test.describe("Webhooks", () => {
  test("an address is checked as it is typed and by the server, the signing secret shows once, and rotating, testing and deleting work", async ({ page, problems }) => {
    test.setTimeout(300_000);
    problems.allowHttp(/\/webhooks\//, [400, 422, 502], "an address that is not a public https address is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused endpoint");
    const customer = await enterpriseCustomer("orghooks");
    await signInAs(page, customer.email);
    await page.goto(customer.org("webhooks"));
    await page.getByRole("button", { name: "New endpoint" }).click();
    const url = page.getByRole("textbox", { name: "Endpoint URL" });
    const submit = page.getByRole("button", { name: /create|save|add endpoint/i }).last();

    // Plain http is explained on the field; an address that points inside the network is refused by the server with a reason.
    await url.fill("http://hooks.example.com/x");
    await expect(page.getByText(/Must start with https/)).toBeVisible();
    await url.fill("https://127.0.0.1/hook");
    await page.getByRole("checkbox", { name: "work_item.created" }).check();
    await submit.click();
    await expect(page.getByRole("alert").first()).toBeVisible({ timeout: 15_000 });
    expect((await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/webhooks/endpoints`)).body).toEqual([]);
    await url.fill("https://user:pass@hooks.example.com/x");
    await submit.click();
    await expect(page.getByRole("alert").first()).toContainText(/user name or password|credentials|not allowed|invalid/i, { timeout: 15_000 });

    // Nothing chosen to listen to: refused before it is sent. Then a real one.
    await url.fill("https://hooks.example.com/servabo");
    await page.getByRole("checkbox", { name: "work_item.created" }).uncheck();
    await expect(submit).toBeDisabled();
    await page.getByRole("checkbox", { name: "work_item.created" }).check();
    await page.getByRole("textbox", { name: "Description (optional)" }).fill("Ledger sync");
    await submit.click();
    const secret = page.getByRole("region", { name: "Webhook signing secret" });
    await expect(secret).toContainText("won't be shown again", { timeout: 20_000 });
    const first = (await secret.getByText(/^whsec_/).innerText()).trim();
    await page.getByRole("button", { name: "I've saved it" }).click();
    expect(await page.content()).not.toContain(first);
    const row = page.getByRole("listitem").filter({ hasText: "https://hooks.example.com/servabo" });
    await expect(row).toContainText("Ledger sync");
    await expect(row).toContainText("1 event");

    // The secret is never listed; rotating gives a different one and says when the old one stops.
    const listed = await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/webhooks/endpoints`);
    expect(JSON.stringify(listed.body)).not.toContain(first);
    await row.getByRole("button", { name: "Rotate secret" }).click();
    await expect(secret).toContainText("previous secret keeps working", { timeout: 15_000 });
    const second = (await secret.getByText(/^whsec_/).innerText()).trim();
    expect(second).not.toBe(first);
    await page.getByRole("button", { name: "I've saved it" }).click();

    // A test event is queued and shows in the deliveries; delete asks first.
    await row.getByRole("button", { name: "Deliveries" }).click();
    await row.getByRole("button", { name: "Send test event" }).click();
    await expect(page.getByText(/Test event queued/)).toBeVisible({ timeout: 15_000 });
    await row.getByRole("button", { name: "Delete https://hooks.example.com/servabo" }).click();
    await row.getByRole("button", { name: "Cancel" }).click();
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Delete https://hooks.example.com/servabo" }).click();
    await row.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByRole("button", { name: "Delete https://hooks.example.com/servabo" })).toHaveCount(0, { timeout: 15_000 });
    await expectHealthyPage(page);
  });

  test("an admin may manage endpoints, a member sees nothing, and the Free plan shows the lock", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orghooks2");
    const admin = await addMember(customer, "orghooks-admin", "ADMIN");
    const member = await addMember(customer, "orghooks-member", "MEMBER");
    await signInAs(page, admin.email);
    await page.goto(customer.org("webhooks"));
    await expect(page.getByRole("button", { name: "New endpoint" })).toBeVisible({ timeout: 30_000 });
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("webhooks"));
      await expect(memberPage.getByRole("button", { name: "New endpoint" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
    const free = await newCustomer("orghooks3", "Hooks Free Ltd");
    await signInAs(page, free.email);
    await page.goto(free.org("webhooks"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included/i).first()).toBeVisible({ timeout: 30_000 });
    const refused = await api(free.session, "POST", `/organizations/${free.orgId}/webhooks/endpoints`, { url: "https://hooks.example.com/x", event_types: ["work_item.created"] });
    expect(refused.status).toBe(402);
  });
});
