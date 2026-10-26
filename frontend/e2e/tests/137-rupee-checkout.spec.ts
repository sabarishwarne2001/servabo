/**
 * PAYING IN RUPEES (Final session 2A, N-187). An Indian distributor's organization (its workspace is in India's time
 * zone) opens Billing in rupees, sees per-user prices in ₹, picks Business for three people and is told, before paying,
 * that its monthly total with GST (₹17,696) is above the ₹15,000 that Indian banks let run without approving each
 * payment, with yearly offered instead. It pays on the stand-in Dodo's checkout, which was told this is an Indian
 * business purchase: billing country IN, UPI and RuPay, a tax ID required and pre-filled with the GSTIN of its
 * GSTR-2B. Back in Servabo the payment is confirmed on Business with three seats.
 */
import AxeBuilder from "@axe-core/playwright";

import { test, expect, settle } from "../support/fixtures";
import { api } from "../support/api";
import { DODO_ORIGIN, GATEWAY } from "../support/env";
import { gstin, gstr2b } from "../support/gst";
import { newCustomer, signInAs, standIn, type Customer } from "../support/journey";

const BUYER = gstin("27", "AAACR4321K");

let customer: Customer;

test.describe("Paying in rupees as an Indian business", () => {
  test.skip(GATEWAY !== "dodo", "rupees are sold through the stand-in Dodo");
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(300_000);
    customer = await newCustomer("rupees", "Rupee Distributors Pvt Ltd");
    const zone = await api(customer.session, "PATCH", `/workspaces/${customer.wsId}`, { timezone: "Asia/Kolkata" });
    expect(zone.status, zone.text).toBe(200);
    // A GSTR-2B import tells Servabo the organization's own GSTIN, which the checkout pre-fills.
    const form = new FormData();
    const statement = gstr2b(BUYER, "2026-09", [
      { gstin: gstin("27", "AABCS5555K"), name: "Sahyadri Packaging", docs: [{ number: "A-1", date: "2026-09-05", taxable: 1000 }] },
    ]);
    form.append("file", new Blob([statement], { type: "application/json" }), "GSTR2B_092026.json");
    expect((await api(customer.session, "POST", `/workspaces/${customer.wsId}/gst/returns`, form)).status).toBe(200);
    standIn("dodo-catalogue", null); // the plans in dollars and rupees, as products at the stand-in Dodo
  });

  test("Billing opens in rupees, says the mandate rule before paying, and Dodo is told it is an Indian business", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    await settle(page);
    const options = page.getByTestId("plan-billing-options");
    await expect(options.getByRole("combobox")).toHaveValue("INR");
    await expect(page.getByRole("radio", { name: /^Business.*₹4,999/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("radio", { name: /^Starter.*₹1,499/ })).toBeVisible();

    await page.getByTestId("plan-cta-business").click();
    await page.locator("#seat-count").fill("3");
    const notice = page.getByTestId("india-mandate-notice");
    await expect(notice).toContainText("17,696");
    await expect(notice).toContainText("15,000");
    await expect(notice.getByRole("button", { name: "Pay yearly instead" })).toBeVisible();
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).include("main").analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical"), JSON.stringify(axe.violations, null, 2)).toEqual([]);

    await page.getByRole("button", { name: "Subscribe", exact: true }).click(); // changing seats asks again
    await page.getByRole("button", { name: "Continue to payment" }).click();
    await expect(page).toHaveURL(new RegExp(`^${DODO_ORIGIN.replace(/\./g, "\\.")}/checkout/`), { timeout: 20_000 });
    await expect(page.locator("body")).toContainText("Business × 3: INR 14,997.00 per month");
    const india = page.getByTestId("india");
    await expect(india).toContainText("Billing country: IN");
    await expect(india).toContainText("UPI, RuPay");
    await expect(india).toContainText("Tax ID required");
    await expect(page.getByTestId("tax-id")).toHaveText(BUYER);
    await page.getByRole("button", { name: "Pay", exact: true }).click();

    const returned = page.getByTestId("checkout-return");
    await expect(returned).toBeVisible({ timeout: 20_000 });
    await expect(returned).toContainText("Payment confirmed", { timeout: 60_000 });
    await expect(page.getByTestId("checkout-confirmed-plan")).toContainText(/business plan with 3 seats/i);
  });

  test("anyone can switch the currency: dollars show the dollar prices", async ({ page }) => {
    const other = await newCustomer("dollars", "Dollar Traders Ltd");
    await signInAs(page, other.email);
    await page.goto(other.org("billing"));
    await settle(page);
    const options = page.getByTestId("plan-billing-options");
    await expect(options.getByRole("combobox")).toHaveValue("USD");
    await expect(page.getByRole("radio", { name: /^Business.*\$299/ })).toBeVisible({ timeout: 20_000 });
    await options.getByRole("combobox").selectOption("INR");
    await expect(page.getByRole("radio", { name: /^Business.*₹4,999/ })).toBeVisible();
  });
});
