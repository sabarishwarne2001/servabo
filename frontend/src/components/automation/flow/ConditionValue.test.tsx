import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FlowCatalog, FlowConditionValue, FlowField } from "@/types/automationFlow";
import { ConditionValue, currencyChoices } from "./ConditionValue";

afterEach(cleanup);

const catalog = { workspace: { currency: "INR", date_format: "DD/MM/YYYY", timezone: "Asia/Kolkata" } } as unknown as FlowCatalog;
const field = (patch: Partial<FlowField>): FlowField => ({
  key: "f", label: "F", type: "string", example: "", description: "", source: "document", ...patch,
});

const show = (
  f: FlowField | undefined,
  operator: string,
  value: FlowConditionValue = "",
  currency = "",
): ReturnType<typeof vi.fn> => {
  const onChange = vi.fn();
  render(
    <ConditionValue catalog={catalog} field={f} operator={operator} value={value} currency={currency}
      invalid={false} disabled={false} onChange={onChange} />,
  );
  return onChange;
};

describe("ConditionValue", () => {
  it("offers the workspace currency first, then the common ones", () => {
    expect(currencyChoices("inr")[0]).toBe("INR");
    expect(currencyChoices("INR").filter((c) => c === "INR")).toHaveLength(1);
    expect(currencyChoices(undefined)).toContain("USD");
  });

  it("takes an amount as a number and a currency, never micros", () => {
    const onChange = show(field({ type: "money" }), "GREATER_THAN", "1000000", "INR");
    expect(screen.getByLabelText("Value")).toHaveProperty("value", "1000000");
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "USD" } });
    expect(onChange).toHaveBeenCalledWith({ currency: "USD" });
  });

  it("gives a field with fixed values a dropdown of their plain names, not a code to type", () => {
    const onChange = show(field({ options: [{ value: "HIGH", label: "High" }, { value: "LOW", label: "Low" }] }), "EQUALS");
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "HIGH" } });
    expect(onChange).toHaveBeenCalledWith({ value: "HIGH" });
    expect(screen.getByRole("option", { name: "High" })).toBeTruthy();
  });

  it("lets 'is one of' hold a value with a comma in it", () => {
    const onChange = show(field({}), "IN", ["Beta"]);
    const input = screen.getByLabelText("Value");
    fireEvent.change(input, { target: { value: "Acme, Inc" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ value: ["Beta", "Acme, Inc"] });
    fireEvent.click(screen.getByRole("button", { name: "Remove Beta" }));
    expect(onChange).toHaveBeenCalledWith({ value: [] });
  });

  it("takes a low and a high for 'between'", () => {
    const onChange = show(field({ type: "number" }), "BETWEEN", ["5", "10"]);
    fireEvent.change(screen.getByLabelText("High value"), { target: { value: "20" } });
    expect(onChange).toHaveBeenCalledWith({ value: ["5", "20"] });
  });

  it("takes a whole number of days for 'older than'", () => {
    show(field({ type: "date" }), "OLDER_THAN_DAYS", "30");
    const input = screen.getByLabelText("Value") as HTMLInputElement;
    expect(input.type).toBe("number");
    expect(screen.getByText("days")).toBeTruthy();
  });

  it("uses a date picker for a date and Yes / No for a true-or-false field", () => {
    show(field({ type: "date" }), "BEFORE", "2026-10-01");
    expect((screen.getByLabelText("Value") as HTMLInputElement).type).toBe("date");
    cleanup();
    show(field({ type: "boolean" }), "EQUALS", "true");
    expect(screen.getByRole("option", { name: "Yes" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "No" })).toBeTruthy();
  });
});
