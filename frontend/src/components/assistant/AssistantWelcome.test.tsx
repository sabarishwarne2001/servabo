import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import AssistantWelcome from "./AssistantWelcome";
afterEach(cleanup);
describe("assistant starters", () => {
  it("inserts a real scoped prompt rather than sending fabricated messages", () => {
    const insert = vi.fn();
    render(<AssistantWelcome onPrompt={insert} />);
    fireEvent.click(screen.getByRole("button", { name: /Compare documents/ }));
    expect(insert).toHaveBeenCalledWith(expect.stringContaining("with citations"));
  });
  it("does not offer mutation actions to a viewer", () => {
    render(<AssistantWelcome onPrompt={vi.fn()} readOnly />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/contributor access/)).toBeTruthy();
  });
});
