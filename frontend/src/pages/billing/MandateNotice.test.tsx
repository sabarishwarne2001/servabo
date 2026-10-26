/**
 * Final session 2A (N-187 rule 8). Indian banks ask the customer to approve each automatic payment above ₹15,000, so
 * the billing page says so before a rupee checkout whose monthly total with GST is above it, and offers yearly.
 * And an add-on's price is shown in the organization's currency, monthly and yearly.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { addonPriceLine } from "@/components/billing/AddOnLockCard";
import { MandateNotice } from "@/pages/billing/PlanSelector";
import type { AddonAccess } from "@/types/entitlements";

afterEach(cleanup);

const BUSINESS_INR = { interval: "month", currency: "INR", unit_amount: 499_900, price_id: "pdt_b_inr", source: "BOOK" } as const;

describe("the ₹15,000 mandate notice", () => {
  it("says the bank will ask each month and offers yearly when three Business users pass the floor", () => {
    const yearly = vi.fn();
    render(<MandateNotice price={BUSINESS_INR} seats={3} limitMinor={1_500_000} gstPercent={18} yearlyAvailable onChooseYearly={yearly} />);
    const notice = screen.getByTestId("india-mandate-notice");
    // ₹4,999 × 3 = ₹14,997, with 18% GST ₹17,696.46, shown rounded.
    expect(notice.textContent).toContain("17,696");
    expect(notice.textContent).toContain("15,000");
    fireEvent.click(screen.getByRole("button", { name: "Pay yearly instead" }));
    expect(yearly).toHaveBeenCalledOnce();
  });

  it("says nothing inside the floor, for dollars, or for a yearly price", () => {
    const { container } = render(
      <>
        <MandateNotice price={BUSINESS_INR} seats={2} limitMinor={1_500_000} gstPercent={18} yearlyAvailable onChooseYearly={vi.fn()} />
        <MandateNotice price={{ ...BUSINESS_INR, currency: "USD", unit_amount: 29_900 }} seats={50} limitMinor={1_500_000}
          gstPercent={18} yearlyAvailable onChooseYearly={vi.fn()} />
        <MandateNotice price={{ ...BUSINESS_INR, interval: "year", unit_amount: 4_999_000 }} seats={3} limitMinor={1_500_000}
          gstPercent={18} yearlyAvailable onChooseYearly={vi.fn()} />
      </>,
    );
    expect(container.textContent).toBe("");
  });
});

describe("an add-on's price", () => {
  const gst = {
    addon_key: "addon.gst_credit", display_name: "GST Credit", monthly_price_micros: 49_000_000, currency: "USD",
    prices: [
      { currency: "USD", interval: "month", unit_amount: 4_900, purchasable: true },
      { currency: "USD", interval: "year", unit_amount: 49_000, purchasable: true },
      { currency: "INR", interval: "year", unit_amount: 1_499_000, purchasable: true },
      { currency: "INR", interval: "month", unit_amount: 149_900, purchasable: true },
    ],
  } as unknown as AddonAccess;

  it("is shown in rupees, monthly first, for an Indian organization, and in dollars otherwise", () => {
    expect(addonPriceLine(gst, "INR")).toMatch(/^₹1,499 a month or ₹14,990 a year$/);
    expect(addonPriceLine(gst, "USD")).toBe("$49 a month or $490 a year");
  });
});
