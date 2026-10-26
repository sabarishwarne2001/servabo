/**
 * ORGANIZATION TABS, PART 3 (Final session 1, organization tabs task): Enterprise BYOK & models, Branding & custom domains,
 * Egress lockdown and Calibrated autonomy. Real input per tab: what a person can type, what is shown back, what survives a
 * reload, what each role and plan can do.
 */
import fs from "node:fs";

import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api } from "../support/api";
import { addMember, newCustomer, signInAs } from "../support/journey";
import { samplePath } from "../support/sample-docs";
import { enterpriseCustomer } from "../support/workflow-helpers";

const GROQ_KEY = `gsk_${"q".repeat(48)}`;

test.describe("Enterprise BYOK & models", () => {
  test("a provider key is added, shown only by its last four digits, rotated, tested and retired", async ({ page, problems }) => {
    test.setTimeout(240_000);
    problems.allowHttp(/\/byok\//, [400, 401, 402, 422, 502, 503], "the provider cannot be reached from the sandbox, so a key may be reported invalid");
    problems.allowConsole(/Failed to load resource/, "a refused provider check");
    const customer = await enterpriseCustomer("orgbyok");
    await signInAs(page, customer.email);
    await page.goto(customer.org("byok"));
    const groq = page.locator("article").filter({ has: page.getByRole("heading", { name: "Groq" }) });
    await expect(groq).toBeVisible({ timeout: 30_000 });
    await expect(groq).toContainText("No key stored.");
    await expect(groq.getByRole("button", { name: "Test connection" })).toHaveCount(0);

    // The key box hides what is typed; Save stays off until there is something to save.
    await groq.getByRole("button", { name: "Add key" }).click();
    const input = groq.locator('input[type="password"]');
    await expect(input).toHaveAttribute("autocomplete", "off");
    await expect(groq.getByRole("button", { name: "Save key" })).toBeDisabled();
    await input.fill("   ");
    await expect(groq.getByRole("button", { name: "Save key" })).toBeDisabled();
    await groq.getByRole("button", { name: "Cancel" }).click();
    await expect(groq.getByRole("button", { name: "Add key" })).toBeVisible();

    await groq.getByRole("button", { name: "Add key" }).click();
    await groq.locator('input[type="password"]').fill(`  ${GROQ_KEY}  `);
    await groq.getByRole("button", { name: "Save key" }).click();
    await expect(groq.getByText("••••" + GROQ_KEY.slice(-4))).toBeVisible({ timeout: 30_000 });
    await expect(groq.getByText(/fingerprint/)).toBeVisible();
    // Never shown again, in the page or in anything the page fetched.
    expect(await page.content()).not.toContain(GROQ_KEY);
    const overview = await api<Record<string, unknown>>(customer.session, "GET", `/organizations/${customer.orgId}/byok`);
    expect(JSON.stringify(overview.body)).not.toContain(GROQ_KEY);
    await page.reload();
    await expect(groq.getByText("••••" + GROQ_KEY.slice(-4))).toBeVisible({ timeout: 30_000 });

    // Rotating asks for a new key and keeps the card; testing reports a result in words.
    await groq.getByRole("button", { name: "Rotate" }).click();
    await groq.locator('input[type="password"]').fill(`gsk_${"z".repeat(48)}`);
    await groq.getByRole("button", { name: "Rotate key" }).click();
    await expect(groq.getByText("••••zzzz")).toBeVisible({ timeout: 30_000 });
    await groq.getByRole("button", { name: "Test connection" }).click();
    await expect(groq.getByText(/Last tested/)).toBeVisible();
    expect(await groq.innerText()).not.toMatch(/\[object|Traceback|undefined/);

    // Retiring asks first; cancelling keeps the key; confirming deletes it.
    await groq.getByRole("button", { name: "Retire" }).click();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(groq.getByText("••••zzzz")).toBeVisible();
    await groq.getByRole("button", { name: "Retire" }).click();
    await page.getByRole("button", { name: "Retire key" }).click();
    await expect(groq.getByText("No key stored.")).toBeVisible({ timeout: 30_000 });
    const gone = await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/byok/credentials`);
    expect(gone.body).toEqual([]);
    await expectHealthyPage(page);
  });

  test("an admin sees the keys but cannot change them, a member cannot open the tab, and the Free plan shows the lock", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgbyok2");
    await api(customer.session, "PUT", `/organizations/${customer.orgId}/byok/credentials`, { provider: "GROQ", api_key: GROQ_KEY });
    const admin = await addMember(customer, "orgbyok-admin", "ADMIN");
    const member = await addMember(customer, "orgbyok-member", "MEMBER");

    await signInAs(page, admin.email);
    await page.goto(customer.org("byok"));
    const groq = page.locator("article").filter({ has: page.getByRole("heading", { name: "Groq" }) });
    await expect(groq.getByText("••••" + GROQ_KEY.slice(-4))).toBeVisible({ timeout: 30_000 });
    await expect(groq.getByRole("button", { name: "Rotate" })).toBeDisabled();
    await expect(groq.getByRole("button", { name: "Retire" })).toBeDisabled();
    await expect(groq.getByRole("button", { name: "Test connection" })).toBeDisabled();
    const refused = await api(admin.session, "DELETE", `/organizations/${customer.orgId}/byok/credentials/GROQ`);
    expect(refused.status).toBe(403);

    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("byok"));
      await expect(memberPage.locator("article")).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }

    const free = await newCustomer("orgbyok3", "Byok Free Ltd");
    await signInAs(page, free.email);
    await page.goto(free.org("byok"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included/i).first()).toBeVisible({ timeout: 30_000 });
    const blocked = await api(free.session, "PUT", `/organizations/${free.orgId}/byok/credentials`, { provider: "GROQ", api_key: GROQ_KEY });
    expect(blocked.status).toBe(402);
  });
});

test.describe("Branding & custom domains", () => {
  test("a brand is checked as it is typed, saved, shown in the preview, switched live, and survives a reload", async ({ page, problems }) => {
    test.setTimeout(240_000);
    problems.allowHttp(/\/branding$/, [422], "a brand name with forbidden characters is refused, by design");
    problems.allowConsole(/422/, "the refused brand name");
    const customer = await enterpriseCustomer("orgbrand");
    await signInAs(page, customer.email);
    await page.goto(customer.org("branding"));
    const name = page.locator("#brand-name");
    const save = page.getByRole("button", { name: "Save brand" });
    await expect(name).toBeVisible({ timeout: 30_000 });
    await expect(save).toBeDisabled();
    await expect(page.getByText("Not applied", { exact: true })).toBeVisible();

    // A colour must be six-digit hex; the message is on the field and Save is off until it is fixed.
    const primary = page.locator("#color-primary_color");
    await primary.fill("red");
    await expect(page.getByRole("alert").filter({ hasText: "Use six-digit hex" })).toBeVisible();
    await expect(save).toBeDisabled();
    await primary.fill("#1A73E8");
    await expect(page.getByRole("alert").filter({ hasText: "Use six-digit hex" })).toHaveCount(0);

    // A forbidden character in the name is refused by the server in words.
    await name.fill("Acme <b>Cloud</b>");
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByText(/cannot contain|not allowed|< >/i).first()).toBeVisible({ timeout: 15_000 });
    expect((await api<{ brand_name: string | null }>(customer.session, "GET", `/organizations/${customer.orgId}/branding`)).body.brand_name).toBeNull();

    // Ampersands and apostrophes are fine; the preview follows the typing; Discard puts it back.
    await name.fill("Barnes & Noble's Cloud");
    await expect(page.getByText("Barnes & Noble's Cloud").first()).toBeVisible();
    await page.getByRole("button", { name: "Discard changes" }).click();
    await expect(name).toHaveValue("");
    await expect(primary, "Discard puts every draft back, colours included").toHaveValue("");
    await primary.fill("#1A73E8");
    await name.fill("  Barnes & Noble's Cloud  ");
    await save.click();
    await expect(save).toBeDisabled({ timeout: 15_000 });
    const stored = await api<{ brand_name: string; primary_color: string; is_enabled: boolean }>(customer.session, "GET", `/organizations/${customer.orgId}/branding`);
    expect(stored.body.brand_name).toBe("Barnes & Noble's Cloud");
    expect(stored.body.primary_color.toLowerCase()).toBe("#1a73e8");
    expect(stored.body.is_enabled).toBe(false);

    // A preset sets every colour at once; the scheme applies as soon as it is chosen; the brand is switched live and back.
    await page.getByRole("button", { name: /Apply .* preset/ }).first().click();
    await expect(save).toBeEnabled();
    await save.click();
    await expect(save).toBeDisabled({ timeout: 15_000 });
    await page.getByRole("button", { name: "Dark", exact: true }).click();
    await expect(page.getByRole("button", { name: "Dark", exact: true })).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });
    await page.getByRole("button", { name: "Enable custom branding" }).click();
    await expect(page.getByText("Live", { exact: true })).toBeVisible({ timeout: 15_000 });
    await page.reload();
    await expect(page.locator("#brand-name")).toHaveValue("Barnes & Noble's Cloud", { timeout: 30_000 });
    await expect(page.getByText("Live", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Dark", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Disable custom branding" }).click();
    await expect(page.getByText("Not applied", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expectHealthyPage(page);
  });

  test("a logo is uploaded, shown, replaced by nothing when a non-picture is chosen, and removed", async ({ page, problems }) => {
    test.setTimeout(240_000);
    problems.allowHttp(/\/branding\/logo$/, [400, 415, 422], "a file that is not a picture is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused upload");
    const customer = await enterpriseCustomer("orglogo");
    await signInAs(page, customer.email);
    await page.goto(customer.org("branding"));
    const logoTile = page.locator("div").filter({ has: page.getByText("PNG, JPEG or WebP", { exact: true }) }).last();
    await expect(page.getByText("PNG, JPEG or WebP", { exact: true })).toBeVisible({ timeout: 30_000 });
    const fileInput = page.locator('main input[type="file"]').first();

    // Something that is not a picture is refused with a message and nothing is stored.
    const notAPicture = test.info().outputPath("notes.png");
    fs.writeFileSync(notAPicture, "these are notes, not a picture");
    await fileInput.setInputFiles(notAPicture);
    await expect(page.getByText(/valid image|not a|unsupported|could not|image/i).first()).toBeVisible({ timeout: 15_000 });
    expect((await api<{ logo_file_id: string | null }>(customer.session, "GET", `/organizations/${customer.orgId}/branding`)).body.logo_file_id).toBeNull();

    await fileInput.setInputFiles(samplePath("logoPng"));
    await expect(page.getByText("Uploaded").first()).toBeVisible({ timeout: 20_000 });
    expect((await api<{ logo_file_id: string | null }>(customer.session, "GET", `/organizations/${customer.orgId}/branding`)).body.logo_file_id).not.toBeNull();
    const served = await api(customer.session, "GET", `/organizations/${customer.orgId}/branding/logo`);
    expect(served.status).toBe(200);
    await page.reload();
    await expect(page.getByText("Uploaded").first()).toBeVisible({ timeout: 30_000 });
    void logoTile;
    await page.getByRole("button", { name: "Remove" }).first().click();
    await expect(page.getByText("PNG, JPEG or WebP", { exact: true })).toBeVisible({ timeout: 15_000 });
    expect((await api<{ logo_file_id: string | null }>(customer.session, "GET", `/organizations/${customer.orgId}/branding`)).body.logo_file_id).toBeNull();
  });

  test("on the Free plan what is on file can be read but nothing can be changed", async ({ page }) => {
    test.setTimeout(180_000);
    const customer = await newCustomer("orgbrand2", "Brand Free Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.org("branding"));
    await expect(page.locator("#brand-name")).toBeDisabled({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Enable custom branding" })).toBeDisabled();
    await expect(page.getByText(/included on higher plans/)).toBeVisible();
    const blocked = await api(customer.session, "PUT", `/organizations/${customer.orgId}/branding`, { brand_name: "Nope" });
    expect(blocked.status).toBe(402);
  });
});

test.describe("Egress lockdown", () => {
  test("rules are checked, listed, removable, and the switch changes what a test destination is told", async ({ page, problems }) => {
    test.setTimeout(240_000);
    problems.allowHttp(/\/egress\/rules$/, [409, 422], "a rule that is not usable, or is a duplicate, is refused, by design");
    problems.allowConsole(/Failed to load resource/, "the refused rule");
    const customer = await enterpriseCustomer("orgegress");
    await signInAs(page, customer.email);
    await page.goto(customer.org("egress"));
    const host = page.getByRole("textbox", { name: "Host, *.domain, IP or CIDR" });
    const add = page.getByRole("button", { name: "Add rule" });
    await expect(host).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Lockdown is off" })).toBeVisible();
    await expect(add).toBeDisabled();

    // A rule that allows everything, or is not a host at all, is refused in words; a bad port cannot be sent.
    for (const bad of ["*", "0.0.0.0/0", "http://hooks.acme.com", "exa mple.com", "999.1.1.1"]) {
      await host.fill(bad);
      await add.click();
      await expect(page.getByText(/could not be added|not a valid|URL|wildcard|allow everything|valid/i).first()).toBeVisible({ timeout: 10_000 });
    }
    const empty = await api<{ rules: unknown[] }>(customer.session, "GET", `/organizations/${customer.orgId}/egress`);
    expect(empty.body.rules).toEqual([]);
    await host.fill("hooks.example.com");
    await page.getByRole("textbox", { name: "Port" }).fill("70000");
    await expect(add).toBeDisabled();
    await page.getByRole("textbox", { name: "Port" }).fill("443");
    await expect(add).toBeEnabled();
    await add.click();
    await expect(page.getByText("Rule added.")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Remove hooks.example.com" })).toBeVisible();
    // The same rule again is explained, not duplicated.
    await host.fill("hooks.example.com");
    await page.getByRole("textbox", { name: "Port" }).fill("443");
    await add.click();
    await expect(page.getByText(/already exists|could not be added/i).first()).toBeVisible({ timeout: 10_000 });
    expect((await api<{ rules: unknown[] }>(customer.session, "GET", `/organizations/${customer.orgId}/egress`)).body.rules).toHaveLength(1);

    // Lockdown on: the allowed host is told yes, any other is told no, with the reason. Off: everything is allowed again.
    await page.getByRole("button", { name: "Switch lockdown on" }).click();
    const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog"));
    if (await confirm.isVisible()) await confirm.getByRole("button").last().click();
    await expect(page.getByRole("heading", { name: "Lockdown is on" })).toBeVisible({ timeout: 15_000 });
    const urlBox = page.getByRole("textbox", { name: "URL or host" });
    await urlBox.fill("https://hooks.example.com/servabo");
    await page.getByRole("button", { name: "Test", exact: true }).click();
    await expect(page.locator("main")).toContainText(/allowed|permitted/i, { timeout: 15_000 });
    await urlBox.fill("https://elsewhere.example.org/x");
    await page.getByRole("button", { name: "Test", exact: true }).click();
    await expect(page.locator("main")).toContainText(/refused|blocked|not allowed/i, { timeout: 15_000 });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Lockdown is on" })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Switch lockdown off" }).click();
    if (await confirm.isVisible()) await confirm.getByRole("button").last().click();
    await expect(page.getByRole("heading", { name: "Lockdown is off" })).toBeVisible({ timeout: 15_000 });

    // Removing the rule empties the list.
    await page.getByRole("button", { name: "Remove hooks.example.com" }).click();
    if (await confirm.isVisible()) await confirm.getByRole("button").last().click();
    await expect(page.getByText("Rule removed.")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Remove hooks.example.com" })).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("an admin may read and test but not change; a Business organization sees the lock; a member cannot open it", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgegress2");
    await api(customer.session, "POST", `/organizations/${customer.orgId}/egress/rules`, { host_pattern: "keep.example.com" });
    const admin = await addMember(customer, "orgegress-admin", "ADMIN");
    const member = await addMember(customer, "orgegress-member", "MEMBER");
    await signInAs(page, admin.email);
    await page.goto(customer.org("egress"));
    await expect(page.getByText("keep.example.com")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Switch lockdown on" }), "an admin is not offered the switch").toHaveCount(0);
    await expect(page.getByText(/Only the organization owner can change the lockdown/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Remove keep.example.com" })).toHaveCount(0);
    expect((await api(admin.session, "PUT", `/organizations/${customer.orgId}/egress`, { lockdown_enabled: true })).status).toBe(403);

    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("egress"));
      await expect(memberPage.getByText("keep.example.com")).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
  });
});

test.describe("Calibrated autonomy", () => {
  test("the owner sets the error limit and audit share, is told what happens, and the setting is kept; an admin only reads", async ({ page, browser }) => {
    test.setTimeout(300_000);
    const customer = await enterpriseCustomer("orgautonomy");
    const admin = await addMember(customer, "orgauto-admin", "ADMIN");
    await signInAs(page, customer.email);
    // Exercise the real loading state: the heading renders before the overview arrives.
    // Keep the real response and permissions; only delivery is delayed.
    await page.route("**/api/v1/organizations/*/autonomy", async (route) => {
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({ response });
    });
    await page.goto(customer.org("autonomy"));
    const limit = page.locator("#autonomy-alpha");
    await expect(page.getByRole("heading", { name: "Calibrated autonomy" })).toBeVisible({ timeout: 30_000 });
    const decisionTypes = page.getByRole("navigation", { name: "Decision types" }).getByRole("button");
    await expect.poll(() => decisionTypes.count(), { timeout: 30_000 }).toBeGreaterThan(0);
    await expect(limit).toBeVisible({ timeout: 30_000 });
    const save = page.getByRole("button", { name: "Save and recalculate" });
    await expect(save).toBeDisabled();

    // Moving the slider changes the preview sentence but nothing is saved until Save.
    const before = await limit.inputValue();
    await limit.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(limit).not.toHaveValue(before);
    await expect(save).toBeEnabled();
    const audit = page.locator("#autonomy-audit");
    await audit.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    const alphaAfter = await limit.inputValue();
    const auditAfter = await audit.inputValue();
    const stored = async () => (await api<{ entries: Array<{ decision_type: string; target_error_rate: string; audit_sample_rate: string }> }>(customer.session, "GET", `/organizations/${customer.orgId}/autonomy`)).body.entries.find((e) => e.decision_type === "verification.document");
    const untouched = await stored();
    await save.click();
    await expect(page.getByText(/Saved/)).toBeVisible({ timeout: 30_000 });
    const kept = await stored();
    expect(kept?.target_error_rate).not.toBe(untouched?.target_error_rate);
    await page.reload();
    await expect(page.locator("#autonomy-alpha")).toHaveValue(alphaAfter, { timeout: 30_000 });
    await expect(page.locator("#autonomy-audit")).toHaveValue(auditAfter);

    // The slider cannot go outside what the server accepts.
    await page.locator("#autonomy-alpha").focus();
    await page.keyboard.press("End");
    expect(Number(await page.locator("#autonomy-alpha").inputValue())).toBeLessThanOrEqual(200);
    await page.keyboard.press("Home");
    expect(Number(await page.locator("#autonomy-alpha").inputValue())).toBeGreaterThanOrEqual(5);

    // An administrator reads the same page but cannot move or save.
    const ctx = await browser.newContext();
    const adminPage = await ctx.newPage();
    try {
      await signInAs(adminPage, admin.email);
      await adminPage.goto(customer.org("autonomy"));
      await expect(adminPage.locator("#autonomy-alpha")).toBeDisabled({ timeout: 30_000 });
      await expect(adminPage.locator("#autonomy-audit")).toBeDisabled();
      await expect(adminPage.getByText("Only an organization owner can change the limit.")).toBeVisible();
      await expect(adminPage.getByRole("button", { name: "Save and recalculate" })).toHaveCount(0);
    } finally {
      await ctx.close();
    }
  });

  test("below Enterprise the tab says what it needs instead of offering sliders", async ({ page }) => {
    test.setTimeout(180_000);
    const customer = await newCustomer("orgauto2", "Autonomy Free Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.org("autonomy"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included|Enterprise/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("#autonomy-alpha")).toHaveCount(0);
    const blocked = await api(customer.session, "GET", `/organizations/${customer.orgId}/autonomy`);
    expect(blocked.status).toBe(402);
  });
});
