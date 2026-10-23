import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import MarkdownRenderer from "./MarkdownRenderer";
afterEach(cleanup);
describe("assistant Markdown and source citations", () => {
  it("renders formatting and only binds citations that have actual sources", () => {
    const citation = vi.fn();
    const { container } = render(
      <MarkdownRenderer
        content={"**Invoice total** is 42 [1]. Unknown [99]. `code [1]`"}
        numericCitationCount={1}
        onNumericCitationClick={citation}
      />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("Invoice total");
    expect(screen.getAllByRole("button", { name: "Open citation 1" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Open citation 1" }));
    expect(citation).toHaveBeenCalledWith(0);
    expect(container.textContent).toContain("[99]");
    expect(container.querySelector("code")?.textContent).toBe("code [1]");
  });
  it("removes scripts, event handlers and unsafe links before inserting buttons", () => {
    const { container } = render(
      <MarkdownRenderer
        content={
          '<script>alert(1)</script><img src=x onerror="alert(2)">[unsafe](javascript:alert(3)) [1]'
        }
        numericCitationCount={1}
      />,
    );
    expect(container.querySelector("script, img, [onerror], [onclick]")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByRole("button", { name: "Open citation 1" })).toBeTruthy();
  });
});
