import { describe, expect, it } from "vitest";
import { rupees } from "./format";

describe("TRINETRA exact financial display", () => {
  it("retains paise above JavaScript's safe integer", () => {
    expect(rupees("45000000000000010000")).toBe("₹4,50,00,00,00,00,000.01");
    expect(rupees("1234567890000")).toBe("₹12,34,567.89");
  });
  it("distinguishes unknown, zero and signed evidence", () => {
    expect(rupees(null)).toBe("—");
    expect(rupees("0")).toBe("₹0.00");
    expect(rupees("-1050000")).toBe("-₹1.05");
  });
});
