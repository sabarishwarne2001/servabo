/** The draggable sidebar divider: its limits, its memory, the keyboard, a drag, and a reset. */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SidebarResizeHandle } from "./SidebarResizeHandle";
import { SHELL_SIDEBAR, clampWidth, forgetSidebarWidths, getSidebarWidth, setSidebarWidth, useSidebarWidth } from "./sidebarWidth";

const Probe = () => {
  const width = useSidebarWidth(SHELL_SIDEBAR);
  return (
    <div style={{ width }} data-testid="side">
      <SidebarResizeHandle spec={SHELL_SIDEBAR} />
    </div>
  );
};

// jsdom has no PointerEvent; this one carries what the divider reads (position, button, pointer id and kind).
class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;
  readonly pointerType: string;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
    this.pointerType = init.pointerType ?? "mouse";
  }
}

beforeEach(() => {
  Object.defineProperty(window, "PointerEvent", { configurable: true, value: TestPointerEvent });
  window.localStorage.clear();
  forgetSidebarWidths();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1600 });
  HTMLElement.prototype.setPointerCapture = () => undefined;
  HTMLElement.prototype.releasePointerCapture = () => undefined;
  window.requestAnimationFrame = (cb) => {
    cb(0);
    return 1;
  };
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.sidebarDragging;
});

describe("the sidebar width", () => {
  it("starts at the default and is always within its limits", () => {
    expect(getSidebarWidth(SHELL_SIDEBAR)).toBe(260);
    expect(clampWidth(SHELL_SIDEBAR, 50)).toBe(SHELL_SIDEBAR.min);
    expect(clampWidth(SHELL_SIDEBAR, 5000)).toBe(SHELL_SIDEBAR.max);
    expect(clampWidth(SHELL_SIDEBAR, Number.NaN)).toBe(SHELL_SIDEBAR.initial);
    // A small window lowers the maximum, but never below the minimum.
    expect(clampWidth(SHELL_SIDEBAR, 400, 300)).toBe(300);
    expect(clampWidth(SHELL_SIDEBAR, 400, 100)).toBe(SHELL_SIDEBAR.min);
  });

  it("is remembered in the browser, and a bad stored value falls back", () => {
    setSidebarWidth(SHELL_SIDEBAR, 333);
    expect(window.localStorage.getItem("servabo_sidebar_width.shell")).toBe("333");
    forgetSidebarWidths();
    expect(getSidebarWidth(SHELL_SIDEBAR)).toBe(333);
    forgetSidebarWidths();
    window.localStorage.setItem("servabo_sidebar_width.shell", "wide");
    expect(getSidebarWidth(SHELL_SIDEBAR)).toBe(260);
  });
});

describe("the divider", () => {
  it("is a labelled, focusable separator that states its value", () => {
    render(<Probe />);
    const handle = screen.getByRole("separator", { name: "Resize the sidebar" });
    expect(handle.getAttribute("tabindex")).toBe("0");
    expect(handle.getAttribute("aria-valuenow")).toBe("260");
    expect(handle.getAttribute("aria-valuemin")).toBe("220");
    expect(handle.getAttribute("aria-valuemax")).toBe("420");
  });

  it("moves with the arrow keys, jumps with Home and End, and goes back with Enter", () => {
    render(<Probe />);
    const handle = screen.getByRole("separator");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(screen.getByTestId("side").style.width).toBe("276px");
    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    expect(screen.getByTestId("side").style.width).toBe("228px");
    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    expect(screen.getByTestId("side").style.width).toBe("220px");
    fireEvent.keyDown(handle, { key: "End" });
    expect(screen.getByTestId("side").style.width).toBe("420px");
    fireEvent.keyDown(handle, { key: "Home" });
    expect(screen.getByTestId("side").style.width).toBe("220px");
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(screen.getByTestId("side").style.width).toBe("260px");
    expect(window.localStorage.getItem("servabo_sidebar_width.shell")).toBeNull();
  });

  it("follows a drag by mouse or finger, pauses animation while dragging, and remembers the end", () => {
    render(<Probe />);
    const handle = screen.getByRole("separator");
    fireEvent.pointerDown(handle, { pointerId: 1, pointerType: "touch", clientX: 260, button: 0 });
    expect(document.documentElement.dataset.sidebarDragging).toBe("true");
    fireEvent.pointerMove(handle, { pointerId: 1, pointerType: "touch", clientX: 340 });
    expect(screen.getByTestId("side").style.width).toBe("340px");
    // Not written to the browser until the drag ends.
    expect(window.localStorage.getItem("servabo_sidebar_width.shell")).toBeNull();
    fireEvent.pointerMove(handle, { pointerId: 1, pointerType: "touch", clientX: 900 });
    expect(screen.getByTestId("side").style.width).toBe("420px");
    fireEvent.pointerUp(handle, { pointerId: 1, pointerType: "touch", clientX: 900 });
    expect(document.documentElement.dataset.sidebarDragging).toBeUndefined();
    expect(window.localStorage.getItem("servabo_sidebar_width.shell")).toBe("420");
  });

  it("ignores a right-click, and a second pointer that is not the one dragging", () => {
    render(<Probe />);
    const handle = screen.getByRole("separator");
    fireEvent.pointerDown(handle, { pointerId: 1, pointerType: "mouse", clientX: 260, button: 2 });
    expect(document.documentElement.dataset.sidebarDragging).toBeUndefined();
    fireEvent.pointerDown(handle, { pointerId: 2, pointerType: "mouse", clientX: 260, button: 0 });
    fireEvent.pointerMove(handle, { pointerId: 9, pointerType: "mouse", clientX: 400 });
    expect(screen.getByTestId("side").style.width).toBe("260px");
    fireEvent.pointerUp(handle, { pointerId: 2, pointerType: "mouse", clientX: 260 });
  });

  it("never lets the sidebar take more than its share of a narrow window", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 500 });
    render(<Probe />);
    const handle = screen.getByRole("separator");
    act(() => {
      fireEvent.keyDown(handle, { key: "End" });
    });
    expect(screen.getByTestId("side").style.width).toBe("250px");
  });

  it("goes back to the default on a double click", () => {
    render(<Probe />);
    const handle = screen.getByRole("separator");
    fireEvent.keyDown(handle, { key: "End" });
    fireEvent.doubleClick(handle);
    expect(screen.getByTestId("side").style.width).toBe("260px");
  });
});
