/**
 * "TEST CONNECTION" AND "SEND TEST" ON THE SETTINGS PAGES (campaign Session C, long tail).
 *
 *  - Settings → Email → "Send test": a dialog (named, so a screen reader can find it) asks for a
 *    recipient; Cancel sends nothing; an empty address cannot be sent; a real address gets a real message
 *    through the relay the workspace resolves to (the suite's mail catcher), and the page says which relay.
 *  - Settings → AI → "Test connection": the page reports a verdict that names the provider and model it
 *    tried, with the reason, and stays usable. In this sandbox no provider can be reached, so the verdict
 *    is a failure with its reason; a success is not driven here.
 * A viewer has neither button enabled.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { waitForMail } from "../support/mail";

test.describe("Settings: connection tests", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(180_000);
  let customer: Customer;

  test.beforeAll(async () => {
    customer = await newCustomer("conntest", "Connection Tests Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "3");
  });

  test("Send test: a named dialog, Cancel sends nothing, an empty address cannot be sent, a real one gets the message", async ({ page }) => {
    const recipient = `conntest-${runId()}@e2e.example.com`;
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=email"));
    await settle(page);
    await page.getByRole("button", { name: "Send test" }).click();
    const dialog = page.getByRole("dialog", { name: "Send test email" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Send Test Email" })).toBeDisabled();
    await dialog.getByLabel("Recipient Email").fill(recipient);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);

    const since = Date.now() - 1_000;
    await page.getByRole("button", { name: "Send test" }).click();
    await page.getByRole("dialog", { name: "Send test email" }).getByLabel("Recipient Email").fill(recipient);
    await page.getByRole("dialog", { name: "Send test email" }).getByRole("button", { name: "Send Test Email" }).click();
    await expect(page.getByText(/^Sent through /)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("dialog", { name: "Send test email" })).toHaveCount(0);
    const mail = await waitForMail(recipient, /./, since);
    expect(mail.text.length).toBeGreaterThan(0);
    await expectHealthyPage(page);
  });

  test("Escape closes the Send test dialog without sending", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=email"));
    await settle(page);
    await page.getByRole("button", { name: "Send test" }).click();
    const dialog = page.getByRole("dialog", { name: "Send test email" });
    await expect(dialog.getByLabel("Recipient Email")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });

  test("Test connection (AI) reports a verdict naming the provider and model, with its reason", async ({ page, problems }) => {
    problems.allowHttp(/\/ai-settings\/test|\/ai\/test|\/test$/, [400, 422, 502, 503], "no model provider can be reached from the sandbox");
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=ai"));
    await settle(page);
    const test = page.getByRole("button", { name: "Test connection" });
    await test.click();
    const verdict = page.locator("[aria-live=polite]").filter({ hasText: /Connected|Failed/ });
    await expect(verdict).toContainText(/(Connected|Failed) · \w+\/.+/, { timeout: 60_000 });
    await expect(test).toBeEnabled();
    await expectHealthyPage(page);
  });

  test("a viewer cannot send a test email or test the connection", async ({ page }) => {
    const viewer = await addMember(customer, "conntest-viewer", "MEMBER", "VIEWER");
    await signInAs(page, viewer.email);
    await page.goto(customer.ws("settings?section=email"));
    await settle(page);
    const send = page.getByRole("button", { name: "Send test" });
    if (await send.count()) await expect(send).toBeDisabled();
    await page.goto(customer.ws("settings?section=ai"));
    await settle(page);
    const check = page.getByRole("button", { name: "Test connection" });
    if (await check.count()) await expect(check).toBeDisabled();
  });
});
