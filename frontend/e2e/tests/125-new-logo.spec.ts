/**
 * THE NEW SERVABO LOGO IS THE DEFAULT (Final session 1, logo task): a customer who has just signed up and has not uploaded a
 * logo sees the Servabo logo in their workspace, never a blank badge or initials; the browser tab and the sign-in page carry
 * the new mark; and a logo the customer uploads still wins.
 */
import { test, expect } from "../support/fixtures";
import { signInAs, newCustomer } from "../support/journey";

test("a new workspace shows the Servabo logo until its own logo is uploaded", async ({ page }) => {
  test.setTimeout(120_000);
  const customer = await newCustomer("newlogo", "Fresh Start Traders");
  await signInAs(page, customer.email);
  await page.goto(customer.ws(""));
  await expect(page.locator("main")).toBeVisible({ timeout: 30_000 });

  // The sidebar's identity block: the Servabo mark, and no initials badge for "Fresh Start".
  const mark = page.locator("aside svg[data-servabo-mark], nav svg[data-servabo-mark], header svg[data-servabo-mark]").first();
  await expect(mark).toBeVisible();
  const box = await mark.boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(20);
  await expect(page.getByText("FS", { exact: true })).toHaveCount(0);

  // The workspace settings say so too.
  await page.goto(customer.ws("settings"));
  await page.getByRole("button", { name: /^General Name, locale and members/ }).click();
  await expect(page.getByText("Default logo")).toBeVisible();
});

test("the browser tab and the sign-in page carry the new mark", async ({ page, request }) => {
  const icon = await request.get("/favicon.svg");
  expect(icon.ok()).toBeTruthy();
  const svg = await icon.text();
  expect(svg).toContain("linearGradient");
  expect(svg).toContain("#8b5cf6"); // the ribbon's violet end
  await page.goto("/login");
  await expect(page.locator("svg[data-servabo-mark]").first()).toBeVisible();
  await expect(page.locator('link[rel="icon"]').first()).toHaveAttribute("href", "/favicon.svg");
});
