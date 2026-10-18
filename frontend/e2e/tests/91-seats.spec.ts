/**
 * SEATS ON A PAID PLAN (Billing → Seats; campaign Session C).
 *
 * An owner of a paid subscription changes the number of seats in the browser. Each step is checked on
 * the page, through Servabo's API and at the payment provider (the stand-in Dodo that Servabo's own
 * calls reach): "One seat fewer" → "Review change" → "Confirm" releases a seat; leaving the dialog with
 * "Cancel" changes nothing; "Remove N unused seats" releases every seat nobody holds; "One seat more"
 * shows the seat price first and "Buy 1 seat" adds one. A member without billing rights has no
 * controls, and the server refuses their change.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, fetchOnce } from "../support/api";
import { DODO_ORIGIN, GATEWAY } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";

interface SubscriptionState {
  readonly seat_capacity: number | null;
  readonly seats_used: number;
  readonly seats_purchased: number;
  readonly subscription: { readonly gateway_subscription_id: string | null } | null;
}

const stateOf = async (customer: Customer): Promise<SubscriptionState> => {
  const response = await api<SubscriptionState>(customer.session, "GET", `/organizations/${customer.orgId}/billing/subscription`);
  expect(response.status, response.text.slice(0, 200)).toBe(200);
  return response.body;
};

/** How many seats the payment provider itself has on this customer's subscription. */
const seatsAtDodo = async (customer: Customer): Promise<number | null> => {
  const gatewayId = (await stateOf(customer)).subscription?.gateway_subscription_id;
  const response = await fetchOnce(`${DODO_ORIGIN}/_fake/state`, { method: "GET" });
  const body = (await response.json()) as { subscriptions: Array<{ subscription_id: string; quantity: number }> };
  return body.subscriptions.find((s) => s.subscription_id === gatewayId)?.quantity ?? null;
};

test.describe("Seats on a paid plan", () => {
  test.skip(GATEWAY !== "dodo", "Seat changes are played against the stand-in Dodo (E2E_GATEWAY=stripe runs the Stripe journeys)");
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let customer: Customer;

  const seatsRegion = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Seats" });

  test.beforeAll(async () => {
    customer = await newCustomer("seats", "Seats Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "developer", "--seats", "4");
  });

  test("the owner holds one of four paid seats and sees the stepper", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    await settle(page);
    const seats = seatsRegion(page);
    await expect(seats).toContainText("In use");
    await expect(seats).toContainText("Paid for");
    await expect(seats.getByRole("button", { name: "One seat fewer" })).toBeEnabled();
    await expect(seats.getByRole("button", { name: "Remove 3 unused seats" })).toBeVisible();
    const state = await stateOf(customer);
    expect([state.seat_capacity, state.seats_used, state.seats_purchased]).toEqual([4, 1, 4]);
    expect(await seatsAtDodo(customer)).toBe(4);
    await expectHealthyPage(page);
  });

  test("One seat fewer → Review change → Confirm releases a seat here and at the provider; Cancel changes nothing", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    await settle(page);
    const seats = seatsRegion(page);

    // Cancel first: nothing moves.
    await seats.getByRole("button", { name: "One seat fewer" }).click();
    await expect(seats.locator("output")).toContainText("3");
    await seats.getByRole("button", { name: "Review change" }).click();
    let dialog = seats.getByRole("dialog", { name: "Confirm seat change" });
    await expect(dialog).toContainText("Change the subscription from 4 to 3 seats?");
    await expect(dialog).toContainText("Removes 1 unused seat.");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect((await stateOf(customer)).seats_purchased).toBe(4);
    expect(await seatsAtDodo(customer)).toBe(4);

    // Now confirm.
    await seats.getByRole("button", { name: "Review change" }).click();
    dialog = seats.getByRole("dialog", { name: "Confirm seat change" });
    await expect(dialog).toContainText("from 4 to 3 seats");
    await dialog.getByRole("button", { name: "Confirm" }).click();
    await expect(dialog).toHaveCount(0, { timeout: 30_000 });
    await expect(seats).toContainText("Paid for");
    await expect.poll(async () => (await stateOf(customer)).seat_capacity, { timeout: 60_000 }).toBe(3);
    await expect.poll(() => seatsAtDodo(customer), { timeout: 60_000 }).toBe(3);

    await page.reload();
    await settle(page);
    await expect(seatsRegion(page).getByRole("button", { name: "Remove 2 unused seats" })).toBeVisible();
    await expectHealthyPage(page);
  });

  test("Remove N unused seats releases every seat nobody holds", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    await settle(page);
    const seats = seatsRegion(page);
    await seats.getByRole("button", { name: "Remove 2 unused seats" }).click();
    await seats.getByRole("button", { name: "Review change" }).click();
    const dialog = seats.getByRole("dialog", { name: "Confirm seat change" });
    await expect(dialog).toContainText("from 3 to 1 seat?");
    await expect(dialog).toContainText("Removes 2 unused seats.");
    await dialog.getByRole("button", { name: "Confirm" }).click();
    await expect(dialog).toHaveCount(0, { timeout: 30_000 });
    await expect.poll(async () => (await stateOf(customer)).seat_capacity, { timeout: 60_000 }).toBe(1);
    await expect.poll(() => seatsAtDodo(customer), { timeout: 60_000 }).toBe(1);

    // Nobody is unused any more, and the stepper cannot go below the seats in use.
    await page.reload();
    await settle(page);
    await expect(seatsRegion(page).getByRole("button", { name: /^Remove \d+ unused seats?$/ })).toHaveCount(0);
    await expect(seatsRegion(page).getByRole("button", { name: "One seat fewer" })).toBeDisabled();
    await expectHealthyPage(page);
  });

  test("One seat more shows the seat price first, and Buy 1 seat adds it here and at the provider", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.org("billing"));
    await settle(page);
    const seats = seatsRegion(page);
    await seats.getByRole("button", { name: "One seat more" }).click();
    await seats.getByRole("button", { name: "Review change" }).click();
    const dialog = seats.getByRole("dialog", { name: "Confirm seat change" });
    await expect(dialog).toContainText("$49.00 per seat per month", { timeout: 20_000 });
    await expect(dialog).toContainText("Charged now for the rest of this period:");
    await dialog.getByRole("button", { name: "Buy 1 seat" }).click();
    await expect(dialog).toHaveCount(0, { timeout: 30_000 });
    await expect.poll(async () => (await stateOf(customer)).seat_capacity, { timeout: 60_000 }).toBe(2);
    await expect.poll(() => seatsAtDodo(customer), { timeout: 60_000 }).toBe(2);
    await page.reload();
    await settle(page);
    await expect(seatsRegion(page).getByRole("button", { name: "Remove 1 unused seat" })).toBeVisible();
    await expectHealthyPage(page);
  });

  test("a member without billing rights has no seat controls, and the server refuses their change", async ({ page }) => {
    const member = await addMember(customer, "seats-member", "MEMBER", "CONTRIBUTOR");
    await signInAs(page, member.email);
    await page.goto(customer.org("billing"));
    await settle(page);
    const seats = seatsRegion(page);
    if (await seats.count()) {
      await expect(seats.getByRole("button", { name: "One seat more" })).toHaveCount(0);
      await expect(seats.getByRole("button", { name: "One seat fewer" })).toHaveCount(0);
    }
    const before = (await stateOf(customer)).seats_purchased;
    const refused = await api(member.session, "POST", `/organizations/${customer.orgId}/billing/seats`, { seats: 1, confirmed_unit_price_micros: null });
    expect([401, 403]).toContain(refused.status);
    expect((await stateOf(customer)).seats_purchased).toBe(before);
  });
});
