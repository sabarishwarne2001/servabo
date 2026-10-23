/**
 * FIRST RUN (campaign session 4, §A.4; rewritten in Final session 1, 2C): a new customer reaches a useful result in minutes.
 *
 * A new organization's dashboard shows "Get started with Servabo", a server-ticked path to the first money found. With no
 * document at hand the owner tries the built-in sample invoice (an ordinary upload made by the server); each step ticks itself
 * from the workspace's real state, the read step offers the documents, and the card can be hidden and brought back.
 * (The steps for each role, the email-in address and the accessibility scan are in 120-getting-started.)
 */
import { test, expect, expectHealthyPage } from "../support/fixtures";
import { newCustomer, signInAs } from "../support/journey";

test.describe("First run", () => {
  test.setTimeout(240_000);

  test("a new customer tries the sample invoice from the getting-started card", async ({ page }) => {
    const customer = await newCustomer("first-run", "First Run Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.ws(""));

    const card = page.getByRole("region", { name: "Get started with Servabo" });
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card).toContainText("0 of 6 done");
    const steps = card.getByRole("list", { name: "Getting started steps" });
    await expect(steps.getByRole("listitem")).toHaveCount(6);

    await card.getByRole("button", { name: "Try a sample invoice" }).click();
    await expect(page.getByText(/Sample invoice added/)).toBeVisible({ timeout: 15_000 });
    await expect(steps.getByRole("listitem").first()).toContainText("(done)", { timeout: 30_000 });

    // Read by the worker like any upload; the card then counts the second step and offers the documents.
    await expect(card).toContainText("2 of 6 done", { timeout: 180_000 });
    await card.getByRole("link", { name: "Open your documents" }).click();
    await expect(page).toHaveURL(/\/work-items/);
    await expect(page.locator("main")).toContainText("sample-invoice-northwind.pdf", { timeout: 30_000 });
    await expectHealthyPage(page);

    // Hidden by the person, it stays hidden in this browser.
    await page.goto(customer.ws(""));
    await page.getByRole("button", { name: "Hide getting started" }).click();
    await expect(card).toHaveCount(0);
    await page.reload();
    await expect(page.locator("main")).toContainText(/Overview|Documents/, { timeout: 30_000 });
    await expect(page.getByRole("region", { name: "Get started with Servabo" })).toHaveCount(0);
    await page.getByRole("button", { name: /Show getting started/ }).click();
    await expect(page.getByRole("region", { name: "Get started with Servabo" })).toBeVisible();
    await expectHealthyPage(page);
  });
});
