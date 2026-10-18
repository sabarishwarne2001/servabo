/**
 * CREDENTIALS: ROTATE AND RETIRE (campaign Session C, long tail).
 *
 * Secrets that can be replaced must really be replaced. On an Enterprise tenant of its own, in the
 * browser, checked against the server:
 *  - API keys: "Rotate" shows the new secret once; the old secret keeps working for the overlap and the
 *    new one works; rotating again too soon warns ("A previous secret is still active"), "Wait" does
 *    nothing and "Rotate anyway" ends the old secret at once; "Revoke" → "Confirm revoke" stops the key.
 *  - Webhooks: "Rotate secret" shows a new signing secret once and says how long the previous one stays
 *    valid; "Delete" asks first.
 *  - Provider keys (BYOK): "Add key" stores one (only a fingerprint is ever shown again), "Rotate" replaces
 *    it, "Retire" asks first and deletes it.
 * A member without the right role has no such buttons and the server refuses them.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, fetchOnce } from "../support/api";
import { API_BASE, runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";

/**
 * Whether a secret is a live key. The public API answers 401 to a secret that is not (or no longer) a key;
 * a live key that is not enabled for the public API (the default for a new key) is known and answers 403.
 */
const isLive = async (secret: string, workspaceId: string): Promise<boolean> => {
  const response = await fetchOnce(`${API_BASE}/public/documents?workspace_id=${workspaceId}`, { headers: { Authorization: `Bearer ${secret}` } });
  expect([200, 401, 403], `unexpected answer for a key: ${response.status}`).toContain(response.status);
  return response.status !== 401;
};

test.describe("Credentials: rotate and retire", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let customer: Customer;

  test.beforeAll(async () => {
    customer = await newCustomer("rotate", "Rotation Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "5");
  });

  test("API key: Rotate gives a new secret once, the old one still works for the overlap; Rotate anyway ends it; Revoke stops the key", async ({ page, problems }) => {
    problems.allowHttp(/\/api-keys\/[0-9a-f-]+\/rotate/, [409], "rotating again inside the overlap is warned about");
    const name = `Rotation key ${runId()}`;
    await signInAs(page, customer.email);
    await page.goto(customer.org("api-keys"));
    await settle(page);
    await page.getByRole("button", { name: "New key" }).click();
    await page.getByRole("textbox", { name: "Name" }).fill(name);
    await page.getByRole("checkbox", { name: "work_items:read" }).check();
    await page.getByRole("button", { name: "Create key" }).click();
    const reveal = page.getByRole("region", { name: "New API key" }).or(page.getByLabel("New API key"));
    const secretOf = async (): Promise<string> => (await reveal.locator("code").first().innerText()).trim();
    const first = await secretOf();
    expect(await isLive(first, customer.wsId)).toBe(true);
    await page.getByRole("button", { name: "I've saved it" }).click();
    await expect(reveal).toHaveCount(0);

    const row = page.getByRole("listitem").filter({ hasText: name });
    // Rotate: a new secret, shown once; the old secret is valid for the overlap and the new one works.
    await row.getByRole("button", { name: "Rotate", exact: true }).click();
    const second = await secretOf();
    expect(second).not.toBe(first);
    await page.getByRole("button", { name: "I've saved it" }).click();
    expect(await isLive(second, customer.wsId), "the new secret opens").toBe(true);
    expect(await isLive(first, customer.wsId), "the old secret still works during the overlap").toBe(true);
    await page.reload();
    await settle(page);
    await expect(page.locator("main")).not.toContainText(second);

    // Rotating again at once: the overlap warning. "Wait" changes nothing.
    await page.getByRole("listitem").filter({ hasText: name }).getByRole("button", { name: "Rotate", exact: true }).click();
    await expect(page.getByText("A previous secret is still active")).toBeVisible();
    await page.getByRole("button", { name: "Wait" }).click();
    await expect(page.getByText("A previous secret is still active")).toHaveCount(0);
    expect(await isLive(second, customer.wsId)).toBe(true);
    expect(await isLive(first, customer.wsId)).toBe(true);

    // "Rotate anyway": the oldest secret stops at once; the one before the new secret becomes the overlap.
    await page.getByRole("listitem").filter({ hasText: name }).getByRole("button", { name: "Rotate", exact: true }).click();
    await page.getByRole("button", { name: "Rotate anyway" }).click();
    const third = await secretOf();
    await page.getByRole("button", { name: "I've saved it" }).click();
    expect(new Set([first, second, third]).size).toBe(3);
    expect(await isLive(third, customer.wsId)).toBe(true);
    expect(await isLive(first, customer.wsId), "the first secret is gone").toBe(false);
    expect(await isLive(second, customer.wsId), "the one before the latest stays for the overlap").toBe(true);

    // Revoke: asks first (Cancel keeps it), then the key stops working and is listed as revoked.
    const live = page.getByRole("listitem").filter({ hasText: name });
    await live.getByRole("button", { name: `Revoke ${name}` }).click();
    await live.getByRole("button", { name: "Cancel" }).click();
    expect(await isLive(third, customer.wsId)).toBe(true);
    await live.getByRole("button", { name: `Revoke ${name}` }).click();
    await live.getByRole("button", { name: "Confirm revoke" }).click();
    await expect(live.getByText("Revoked")).toBeVisible();
    expect(await isLive(third, customer.wsId)).toBe(false);
    expect(await isLive(second, customer.wsId), "revoking ends the overlap secret too").toBe(false);
    const listed = await api<Array<{ name: string; deactivated_at: string | null }>>(customer.session, "GET", `/organizations/${customer.orgId}/api-keys`);
    expect(listed.body.find((k) => k.name === name)?.deactivated_at).not.toBeNull();
    await expectHealthyPage(page);
  });

  test("Webhook: Rotate secret shows a new signing secret once and says when the old one ends; Delete asks first", async ({ page, problems }) => {
    problems.allowHttp(/\/webhooks\//, [400, 422, 502], "the receiver is unreachable from the sandbox");
    const url = `https://hooks.rotation.example.com/${runId()}`;
    await signInAs(page, customer.email);
    await page.goto(customer.org("webhooks"));
    await settle(page);
    await page.getByRole("button", { name: "New endpoint" }).click();
    await page.getByRole("textbox", { name: "Endpoint URL" }).fill(url);
    await page.getByRole("checkbox", { name: "work_item.created" }).check();
    await page.getByRole("button", { name: /create|save|add endpoint/i }).last().click();
    const revealed = page.getByRole("region", { name: "Webhook signing secret" }).or(page.getByLabel("Webhook signing secret"));
    await expect(revealed).toBeVisible({ timeout: 15_000 });
    const first = (await revealed.getByText(/^whsec_/).innerText()).trim();
    await page.getByRole("button", { name: "I've saved it" }).click();

    const row = page.getByRole("listitem").filter({ hasText: url });
    await row.getByRole("button", { name: "Rotate secret" }).click();
    await expect(revealed).toBeVisible({ timeout: 15_000 });
    const second = (await revealed.getByText(/^whsec_/).innerText()).trim();
    expect(second).not.toBe(first);
    await expect(revealed).toContainText("The previous secret keeps working until");
    await page.getByRole("button", { name: "I've saved it" }).click();
    await page.reload();
    await settle(page);
    await expect(page.locator("main")).not.toContainText(second);
    await expect(page.getByRole("listitem").filter({ hasText: url })).toContainText("Both the current and previous signing secrets");

    // Delete asks first; Cancel keeps the endpoint, confirming removes it.
    const again = page.getByRole("listitem").filter({ hasText: url });
    await again.getByRole("button", { name: `Delete ${url}` }).click();
    await again.getByRole("button", { name: "Cancel" }).click();
    await expect(again).toBeVisible();
    await again.getByRole("button", { name: `Delete ${url}` }).click();
    await again.getByRole("button", { name: /^(Confirm|Delete)/ }).last().click();
    await expect(page.getByRole("listitem").filter({ hasText: url })).toHaveCount(0);
    const endpoints = await api<Array<{ url: string }>>(customer.session, "GET", `/organizations/${customer.orgId}/webhooks/endpoints`);
    expect(endpoints.status, endpoints.text.slice(0, 200)).toBe(200);
    expect(endpoints.body.map((r) => r.url)).not.toContain(url);
    await expectHealthyPage(page);
  });

  test("Provider key: Add key stores one (only a fingerprint is shown), Rotate replaces it, Retire asks first and deletes it", async ({ page, problems }) => {
    problems.allowHttp(/\/byok\//, [400, 422, 502, 503], "the provider cannot be reached from the sandbox");
    const listed = async (): Promise<Array<{ provider: string; key_fingerprint: string; key_version: number; status: string }>> =>
      (await api<Array<{ provider: string; key_fingerprint: string; key_version: number; status: string }>>(customer.session, "GET", `/organizations/${customer.orgId}/byok/credentials`)).body;
    await signInAs(page, customer.email);
    await page.goto(customer.org("byok"));
    await settle(page);
    const provider = await page.getByRole("article").filter({ has: page.getByRole("button", { name: "Add key" }) }).first()
      .getByRole("heading", { level: 3 }).innerText();
    const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: provider, exact: true, level: 3 }) });
    await card.getByRole("button", { name: "Add key" }).click();
    // The provider's keys have a known beginning (the field's placeholder, e.g. "gsk_…"); use it.
    const prefix = ((await card.getByLabel(new RegExp(`${provider} API key`)).getAttribute("placeholder")) ?? "").replace("…", "");
    const secret = `${prefix}e2e${runId()}first0123456789`;
    await card.getByLabel(new RegExp(`${provider} API key`)).fill(secret);
    await card.getByRole("button", { name: "Save key" }).click();
    await expect(card.getByRole("button", { name: "Retire" })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("main")).not.toContainText(secret);
    const stored = (await listed()).find((c) => c.status !== "UNCONFIGURED");
    expect(stored, "the key is stored").toBeTruthy();
    expect(JSON.stringify(await listed())).not.toContain(secret);
    const firstFingerprint = stored?.key_fingerprint ?? null;

    // Rotate replaces it: a different fingerprint, still no secret anywhere.
    await card.getByRole("button", { name: "Rotate", exact: true }).click();
    await card.getByLabel(new RegExp(`Replace ${provider} key`)).fill(`${prefix}e2e${runId()}second9876543210`);
    await card.getByRole("button", { name: "Rotate key" }).click();
    await expect(card.getByRole("button", { name: "Retire" })).toBeVisible();
    await expect.poll(async () => (await listed()).find((c) => c.status !== "UNCONFIGURED")?.key_fingerprint ?? null).not.toBe(firstFingerprint);
    expect((await listed()).find((c) => c.status !== "UNCONFIGURED")?.key_version, "rotation raises the key version").toBe((stored?.key_version ?? 0) + 1);
    expect(JSON.stringify(await listed())).not.toContain("second9876543210");

    // Retire asks first; Cancel keeps the key, confirming deletes it.
    await card.getByRole("button", { name: "Retire" }).click();
    const dialog = page.getByRole("alertdialog", { name: `Retire the ${provider} key?` });
    await dialog.getByRole("button", { name: "Cancel" }).click();
    expect((await listed()).some((c) => c.status !== "UNCONFIGURED")).toBe(true);
    await card.getByRole("button", { name: "Retire" }).click();
    await page.getByRole("alertdialog", { name: `Retire the ${provider} key?` }).getByRole("button", { name: "Retire key" }).click();
    await expect(card).toContainText("Key retired.");
    await expect(card.getByRole("button", { name: "Add key" })).toBeVisible();
    expect((await listed()).filter((c) => c.status !== "UNCONFIGURED")).toEqual([]);
    await page.reload();
    await settle(page);
    await expect(page.getByRole("button", { name: "Retire" })).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("a member has no rotate or revoke buttons, and the server refuses them", async ({ page }) => {
    const member = await addMember(customer, "rotate-member", "MEMBER", "CONTRIBUTOR");
    const created = await api<{ api_key: { id: string } }>(customer.session, "POST", `/organizations/${customer.orgId}/api-keys`, {
      name: `Owner key ${runId()}`, scopes: ["work_items:read"],
    });
    expect(created.status, created.text).toBeLessThan(300);
    const keyId = created.body.api_key.id;
    await signInAs(page, member.email);
    await page.goto(customer.org("api-keys"));
    await settle(page);
    await expect(page.getByRole("button", { name: "Rotate", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "New key" })).toHaveCount(0);
    const rotate = await api(member.session, "POST", `/organizations/${customer.orgId}/api-keys/${keyId}/rotate`);
    const revoke = await api(member.session, "DELETE", `/organizations/${customer.orgId}/api-keys/${keyId}`);
    expect([rotate.status, revoke.status].every((status) => status === 403 || status === 404)).toBe(true);
    const state = await api<Array<{ id: string; deactivated_at: string | null }>>(customer.session, "GET", `/organizations/${customer.orgId}/api-keys`);
    expect(state.body.find((k) => k.id === keyId)?.deactivated_at).toBeNull();
  });
});
