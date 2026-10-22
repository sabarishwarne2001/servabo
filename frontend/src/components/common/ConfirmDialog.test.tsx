import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React, { useEffect, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

afterEach(cleanup);

/** A stand-in for the builder: a parent that reacts to Escape on `window`, as FlowBuilder does. */
const Host: React.FC<{ onParentEscape: () => void; children: React.ReactNode }> = ({ onParentEscape, children }) => {
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {onParentEscape();}
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onParentEscape]);
  return <div>{children}</div>;
};

describe("ConfirmDialog and Escape", () => {
  it("does not let Escape reach a parent's window handler", () => {
    const parent = vi.fn();
    const cancel = vi.fn();
    render(
      <Host onParentEscape={parent}>
        <ConfirmDialog open title="Discard your changes?" message="Edits are lost." confirmText="Discard changes" onConfirm={vi.fn()} onCancel={cancel} />
      </Host>,
    );
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(parent).not.toHaveBeenCalled();
  });

  it("closes only the top dialog when one is open over another", () => {
    const lower = vi.fn();
    const upper = vi.fn();
    const Stack: React.FC = () => {
      const [upperOpen] = useState(true);
      return (
        <>
          <ConfirmDialog open title="Lower" message="Lower dialog" confirmText="OK" onConfirm={vi.fn()} onCancel={lower} />
          <ConfirmDialog open={upperOpen} title="Upper" message="Upper dialog" confirmText="OK" onConfirm={vi.fn()} onCancel={upper} />
        </>
      );
    };
    render(<Stack />);
    expect(screen.getAllByRole("alertdialog")).toHaveLength(2);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(upper).toHaveBeenCalledTimes(1);
    expect(lower).not.toHaveBeenCalled();
  });
});
