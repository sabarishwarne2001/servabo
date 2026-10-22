/** Money, one way: rupees in lakh and crore grouping with the rupee sign, other currencies in the person's language. */
import { afterEach, describe, expect, it } from "vitest";

import { applyDisplayPreferences, formatMoney } from "./displayTime";

afterEach(() => applyDisplayPreferences(undefined, "en-US"));

describe("formatMoney", () => {
  it.each(["en-US", "de-DE", "hi-IN", "fr-FR"])("groups rupees the Indian way whatever the language (%s)", (language) => {
    applyDisplayPreferences(undefined, language);
    expect(formatMoney(1234567.5, "INR")).toBe("₹12,34,567.50");
    expect(formatMoney(123456789, "inr")).toBe("₹12,34,56,789.00");
    expect(formatMoney(999, "INR")).toBe("₹999.00");
    expect(formatMoney(-18, "INR")).toBe("-₹18.00");
  });

  it("keeps other currencies in the person's language with their own symbol", () => {
    applyDisplayPreferences(undefined, "en-US");
    expect(formatMoney(1234567.5, "USD")).toBe("$1,234,567.50");
    applyDisplayPreferences(undefined, "de-DE");
    expect(formatMoney(1234.5, "EUR")).toMatch(/^1\.234,50\s€$/);
  });

  it("prints a plain number, never a guessed symbol, when there is no usable currency", () => {
    applyDisplayPreferences(undefined, "en-US");
    expect(formatMoney(12, null)).toBe("12.00");
    expect(formatMoney(12, "")).toBe("12.00");
    expect(formatMoney(1234.5, "ZZZ")).toMatch(/1,234\.50/);
  });

  it("shows a dash for a missing or impossible amount", () => {
    expect(formatMoney(null, "INR")).toBe("—");
    expect(formatMoney(undefined, "INR")).toBe("—");
    expect(formatMoney(Number.NaN, "INR")).toBe("—");
    expect(formatMoney(Number.POSITIVE_INFINITY, "USD")).toBe("—");
  });
});
