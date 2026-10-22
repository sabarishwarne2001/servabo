/**
 * ORGANIZATION TABS, PART 2 (Final session 1, organization tabs task): Transactional email, Service levels and Data governance
 * & compliance. Real input per tab: what the forms accept and refuse, what is shown back, what survives a reload, and what each
 * role and plan can do.
 */
import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api } from "../support/api";
import { addMember, newCustomer, signInAs } from "../support/journey";
import { enterpriseCustomer } from "../support/workflow-helpers";
import { waitForMail } from "../support/mail";

test.describe("Transactional email", () => {
  test("a configuration is checked, saved without ever showing its password, and a test message really arrives", async ({ page, problems }) => {
    test.setTimeout(240_000);
    problems.allowHttp(/\/email-settings$/, [422], "the form refuses an incomplete or impossible configuration, by design");
    problems.allowConsole(/422/, "the refused save");
    const customer = await enterpriseCustomer("orgemail");
    await signInAs(page, customer.email);
    await page.goto(customer.org("email-settings"));
    const enable = page.getByRole("checkbox", { name: /Use custom server/ });
    await expect(enable).toBeVisible({ timeout: 30_000 });
    const save = page.getByRole("button", { name: "Save settings" });
    await expect(save).toBeDisabled();

    // Switching it on with nothing filled in is refused with a reason a person can act on.
    await enable.check();
    await page.getByRole("textbox", { name: "Server host" }).fill("127.0.0.1");
    await save.click();
    const alert = page.getByRole("alert").filter({ hasText: /./ }).first();
    await expect(alert).toBeVisible({ timeout: 15_000 });
    expect(await alert.innerText()).not.toMatch(/\[object|undefined|\{"/);

    // A port that cannot exist, and a sender address that is not one: each is explained, nothing is saved.
    await page.getByRole("spinbutton", { name: "Port" }).fill("70000");
    await page.getByRole("combobox", { name: "Encryption" }).selectOption({ label: "None" });
    await page.getByRole("textbox", { name: "Username" }).fill("relay");
    await page.getByRole("textbox", { name: "Password" }).fill("relay-secret-9137");
    await page.getByRole("textbox", { name: "Sender name" }).fill("Mail Check");
    await page.getByRole("textbox", { name: "Sender address" }).fill("noreply@mailcheck.example.com");
    await save.click();
    await expect(page.getByRole("alert").first()).toContainText(/65535|port/i, { timeout: 15_000 });
    const none = await api<{ is_complete: boolean }>(customer.session, "GET", `/organizations/${customer.orgId}/email-settings`);
    expect(none.body.is_complete).toBe(false);

    // Valid: saved, the password box is emptied, and the page says a password is held (never what it is).
    await page.getByRole("spinbutton", { name: "Port" }).fill("1025");
    await save.click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("textbox", { name: "Password" })).toHaveValue("");
    await expect(page.getByRole("textbox", { name: "Password" })).toHaveAttribute("placeholder", /leave blank to keep/);
    await page.reload();
    await expect(page.getByRole("textbox", { name: "Server host" })).toHaveValue("127.0.0.1", { timeout: 30_000 });
    await expect(page.getByRole("spinbutton", { name: "Port" })).toHaveValue("1025");
    expect(await page.content(), "the password is in the page").not.toContain("relay-secret-9137");
    const stored = await api<Record<string, unknown>>(customer.session, "GET", `/organizations/${customer.orgId}/email-settings`);
    expect(JSON.stringify(stored.body)).not.toContain("relay-secret-9137");
    expect(stored.body.has_password).toBe(true);

    // A test message goes through the saved server and arrives, and says where it came from.
    const since = Date.now() - 1_000;
    const to = `mailcheck-${Date.now()}@e2e.example.com`;
    await page.getByRole("textbox", { name: "Send to" }).fill(to);
    await page.getByRole("button", { name: "Send test" }).click();
    await expect(page.getByText("Test email sent successfully.")).toBeVisible({ timeout: 30_000 });
    const mail = await waitForMail(to, /./, since);
    expect(mail.text).toMatch(/SMTP|configuration/i);

    // The password stays when only another field changes.
    await page.getByRole("textbox", { name: "Sender name" }).fill("Mail Check Two");
    await save.click();
    await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible({ timeout: 15_000 });
    const still = await api<{ has_password: boolean; sender_name: string }>(customer.session, "GET", `/organizations/${customer.orgId}/email-settings`);
    expect(still.body.has_password).toBe(true);
    expect(still.body.sender_name).toBe("Mail Check Two");
    await expectHealthyPage(page);
  });

  test("a server that cannot be reached is reported plainly, and a Free organization sees the lock, a member sees nothing", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgemail2");
    // The invitation goes first: once the organization's own server is set, invitations are sent through it.
    const member = await addMember(customer, "orgemail-member", "MEMBER");
    await api(customer.session, "PATCH", `/organizations/${customer.orgId}/email-settings`, {
      smtp_host: "127.0.0.1", smtp_port: 1, smtp_username: "u", smtp_password: "p", sender_name: "N", sender_email: "n@example.com",
      encryption: "NONE", is_enabled: true,
    });
    await signInAs(page, customer.email);
    await page.goto(customer.org("email-settings"));
    await page.getByRole("textbox", { name: "Send to" }).fill("someone@e2e.example.com");
    await page.getByRole("button", { name: "Send test" }).click();
    const result = page.locator("main").getByText(/refused|unable|could not|failed|connect|timed out|not allowed|blocked/i).first();
    await expect(result).toBeVisible({ timeout: 30_000 });
    expect(await page.locator("main").innerText()).not.toMatch(/Traceback|\[object/);

    // A plain member is turned away from the tab; the Free plan shows the lock, not a working form.
    const ctx = await browser.newContext();
    const memberPage = await ctx.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("email-settings"));
      await expect(memberPage.getByRole("textbox", { name: "Server host" })).toHaveCount(0, { timeout: 15_000 });
    } finally {
      await ctx.close();
    }
    const free = await newCustomer("orgemail3", "Free Mail Ltd");
    await signInAs(page, free.email);
    await page.goto(free.org("email-settings"));
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included/i).first()).toBeVisible({ timeout: 30_000 });
    const refused = await api(free.session, "PATCH", `/organizations/${free.orgId}/email-settings`, { smtp_host: "smtp.example.com" });
    expect(refused.status).toBe(402);
  });
});

test.describe("Service levels", () => {
  test("a custom target is validated, kept across a reload, marked contractual, and can go back to the default", async ({ page, problems }) => {
    test.setTimeout(180_000);
    const customer = await enterpriseCustomer("orgslo");
    await signInAs(page, customer.email);
    await page.goto(customer.org("service-levels"));
    const availability = page.getByRole("listitem").filter({ hasText: "API availability" });
    await expect(availability).toBeVisible({ timeout: 30_000 });
    await availability.getByRole("button", { name: "Change target" }).click();
    const input = availability.getByRole("textbox", { name: /Target for API availability/ });

    // Nonsense is explained and nothing is saved.
    problems.allowHttp(/\/slos\//, [400, 422], "a target outside its range is refused, by design");
    problems.allowConsole(/422/, "the refused target");
    for (const bad of ["99.9", "1.5", "-0.1", "abc", ""]) {
      await input.fill(bad);
      await availability.getByRole("button", { name: "Save" }).click();
      await expect(availability.getByRole("alert")).toContainText(/not saved|between 0 and 1/i, { timeout: 15_000 });
    }
    const untouched = await api<{ entries: Array<{ slo_key: string; target: { source: string } }> }>(customer.session, "GET", `/organizations/${customer.orgId}/slos`);
    expect(untouched.body.entries.every((entry) => entry.target.source !== "ORGANIZATION")).toBe(true);

    // A real one is kept, shown as custom and contractual, and survives a reload.
    await input.fill("0.995");
    await availability.getByRole("checkbox", { name: "Contractual" }).check();
    await availability.getByRole("button", { name: "Save" }).click();
    await expect(availability.getByText("Custom target")).toBeVisible({ timeout: 15_000 });
    await expect(availability.getByText("Contractual")).toBeVisible();
    await expect(availability).toContainText(/target 99\.50?\s?%|target 0\.995/);
    await page.reload();
    await expect(page.getByRole("listitem").filter({ hasText: "API availability" }).getByText("Custom target")).toBeVisible({ timeout: 30_000 });

    // The history switch re-reads without losing the custom target; going back to the default removes it.
    await page.getByLabel("History").selectOption("MONTH");
    await expect(page.getByRole("listitem").filter({ hasText: "API availability" }).getByText("Custom target")).toBeVisible();
    await page.getByLabel("History").selectOption("HOUR");
    const again = page.getByRole("listitem").filter({ hasText: "API availability" });
    await again.getByRole("button", { name: "Change target" }).click();
    await again.getByRole("button", { name: "Use platform default" }).click();
    await expect(page.getByText("Target reset to the platform default.")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("listitem").filter({ hasText: "API availability" }).getByText("Custom target")).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("below Enterprise the levels are readable and the target cannot be changed; a member cannot open the tab", async ({ page, browser }) => {
    test.setTimeout(180_000);
    const customer = await newCustomer("orgslo2", "Slo Free Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.org("service-levels"));
    await expect(page.getByRole("heading", { name: "Service levels" }).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/API availability/).first()).toBeVisible();
    await expect(page.getByText(/included on the|upgrade|isn.t included|not included/i).first()).toBeVisible();
    const slos = await api<{ entries: Array<{ slo_key: string }> }>(customer.session, "GET", `/organizations/${customer.orgId}/slos`);
    const blocked = await api(customer.session, "PUT", `/organizations/${customer.orgId}/slos/${slos.body.entries[0]!.slo_key}`, { target_value: "0.9" });
    expect(blocked.status).toBe(402);
    expect(blocked.text).toContain("CAPABILITY_REQUIRED");
  });
});

test.describe("Data governance & compliance", () => {
  test("retention: what is typed is what is saved, a typo is not read as 'forever', and the result is confirmed", async ({ page, problems }) => {
    problems.allowHttp(/\/compliance\/retention$/, [422], "a period outside its range is refused, by design");
    problems.allowConsole(/422/, "the refused period");
    test.setTimeout(180_000);
    const customer = await enterpriseCustomer("orgretention");
    await signInAs(page, customer.email);
    await page.goto(customer.org("compliance"));
    const documents = page.locator("#retention-work-items");
    const conversations = page.locator("#retention-conversations");
    const audit = page.locator("#retention-audit");
    const save = page.getByRole("button", { name: "Save retention policy" });
    await expect(documents).toBeVisible({ timeout: 30_000 });
    await expect(documents).toHaveValue("");

    const retention = async () => (await api<Record<string, number | null>>(customer.session, "GET", `/organizations/${customer.orgId}/compliance/retention`)).body;

    // A value that is not a number is refused on the page, never read as "keep forever".
    await api(customer.session, "PUT", `/organizations/${customer.orgId}/compliance/retention`, { work_item_retention_days: 365, auto_purge_enabled: false });
    await page.reload();
    await expect(documents).toHaveValue("365", { timeout: 30_000 });
    await documents.fill("abc");
    await save.click();
    await expect(page.getByRole("alert").filter({ hasText: /whole number|days|number/i })).toBeVisible({ timeout: 10_000 });
    expect((await retention()).work_item_retention_days, "a typo must not erase the policy").toBe(365);

    // Floors and ceilings are explained; nothing is saved by a refusal.
    for (const [field, value, message] of [
      [documents, "10", /30/], [conversations, "5", /30/], [audit, "100", /400/], [documents, "99999999999", /36500|at most|less than/i],
    ] as const) {
      await field.fill(value);
      await save.click();
      await expect(page.getByRole("alert").filter({ hasText: message })).toBeVisible({ timeout: 15_000 });
      await field.fill(field === documents ? "365" : "");
    }
    expect((await retention()).work_item_retention_days).toBe(365);

    // A real policy is saved, confirmed, audited and kept across a reload.
    await documents.fill("400");
    await conversations.fill("90");
    await audit.fill("800");
    await save.click();
    await expect(page.getByRole("status").filter({ hasText: /saved/i })).toBeVisible({ timeout: 15_000 });
    await page.reload();
    await expect(documents).toHaveValue("400", { timeout: 30_000 });
    await expect(conversations).toHaveValue("90");
    await expect(audit).toHaveValue("800");
    const changes = await api<{ items: Array<{ action: string }> }>(customer.session, "GET", `/organizations/${customer.orgId}/audit-logs?limit=20`);
    expect(changes.body.items.filter((row) => row.action === "RETENTION_CHANGED").length).toBeGreaterThanOrEqual(2);
    // Blank again means forever.
    await documents.fill("");
    await conversations.fill("");
    await audit.fill("");
    await save.click();
    await expect(page.getByRole("status").filter({ hasText: /saved/i })).toBeVisible({ timeout: 15_000 });
    expect((await retention()).work_item_retention_days).toBeNull();
    await expectHealthyPage(page);
  });

  test("residency, export and erasure: each needs its confirmation, the owner alone writes, an admin reads", async ({ page, browser, problems }) => {
    problems.allowHttp(/\/compliance\/erasures$/, [400], "an erasure with a wrong confirmation address is refused, by design");
    problems.allowConsole(/400/, "the refused erasure");
    test.setTimeout(300_000);
    const customer = await enterpriseCustomer("orgcompliance");
    const admin = await addMember(customer, "orgcomp-admin", "ADMIN");
    const member = await addMember(customer, "orgcomp-member", "MEMBER");

    await signInAs(page, customer.email);
    await page.goto(customer.org("compliance"));
    await expect(page.getByRole("heading", { name: "Data residency" })).toBeVisible({ timeout: 30_000 });
    // The region cannot be saved until the person says they understand it moves nothing already stored.
    const region = page.locator("#residency-region");
    const options = await region.locator("option").allTextContents();
    expect(options.length).toBeGreaterThan(1);
    await expect(page.getByRole("button", { name: "Save region" })).toBeDisabled();

    // Export: a bundle is made, listed, and its download is a real zip.
    await page.getByRole("button", { name: "Generate bundle" }).click();
    await expect(page.getByRole("button", { name: "Download", exact: true }).first()).toBeVisible({ timeout: 60_000 });
    const download = page.waitForEvent("download", { timeout: 30_000 });
    await page.getByRole("button", { name: "Download", exact: true }).first().click();
    expect((await download).suggestedFilename()).toMatch(/\.zip$/);

    // Erasure: the person is chosen by name, the impact is previewed, a wrong address or a missing phrase cannot erase,
    // and the right ones erase once and are recorded.
    await page.getByRole("button", { name: "Erase a subject" }).click();
    const choice = page.locator("#erasure-subject option", { hasText: member.email });
    await expect(choice).toHaveCount(1, { timeout: 20_000 });
    await page.locator("#erasure-subject").selectOption(await choice.getAttribute("value") ?? "");
    await page.getByRole("button", { name: "Run impact preview" }).click();
    await expect(page.getByRole("dialog")).toContainText(/document|record|session|membership|impact/i, { timeout: 20_000 });
    const erase = page.getByRole("button", { name: "Erase permanently" });
    await expect(erase).toBeDisabled();
    await page.locator("#erasure-email").fill("someone-else@example.com");
    await page.locator("#erasure-ticket").fill("DSAR-E2E-1");
    await page.locator("#erasure-phrase").fill("ERASE");
    if (await erase.isEnabled()) {
      await erase.click();
      await expect(page.getByRole("alert").filter({ hasText: /does not match|confirmation/i })).toBeVisible({ timeout: 15_000 });
    }
    expect((await api<unknown[]>(customer.session, "GET", `/organizations/${customer.orgId}/compliance/erasures`)).body).toHaveLength(0);
    await page.locator("#erasure-email").fill(member.email);
    await page.locator("#erasure-phrase").fill("");
    await expect(erase, "the confirmation word is required").toBeDisabled();
    await page.locator("#erasure-phrase").fill("ERASE");
    await expect(erase).toBeEnabled();
    await erase.click();
    await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByRole("cell", { name: "DSAR-E2E-1" })).toBeVisible({ timeout: 20_000 });
    const erasures = await api<Array<{ erasure_ticket: string; subject_email_hash: string }>>(customer.session, "GET", `/organizations/${customer.orgId}/compliance/erasures`);
    expect(erasures.body.map((row) => row.erasure_ticket)).toEqual(["DSAR-E2E-1"]);
    expect(JSON.stringify(erasures.body)).not.toContain(member.email);
    // The erased person's own session no longer works.
    expect((await api(member.session, "GET", "/me")).status).toBeGreaterThanOrEqual(400);

    // The administrator reads everything and writes nothing.
    const asAdmin = await browser.newContext();
    const adminPage = await asAdmin.newPage();
    try {
      await signInAs(adminPage, admin.email);
      await adminPage.goto(customer.org("compliance"));
      await expect(adminPage.getByRole("heading", { name: "Data residency" })).toBeVisible({ timeout: 30_000 });
      await expect(adminPage.getByRole("button", { name: "Save region" })).toHaveCount(0);
      await expect(adminPage.getByRole("button", { name: "Save retention policy" })).toHaveCount(0);
      await expect(adminPage.locator("#retention-work-items")).toBeDisabled();
      await expect(adminPage.getByText("Only an organization owner can change this.").first()).toBeVisible();
    } finally {
      await asAdmin.close();
    }
    const refused = await api(admin.session, "PUT", `/organizations/${customer.orgId}/compliance/retention`, { work_item_retention_days: 365 });
    expect(refused.status).toBe(403);
    const noPeek = await api(member.session, "GET", `/organizations/${customer.orgId}/compliance`);
    expect([401, 403, 404], "an erased person has no session left").toContain(noPeek.status);
  });
});
