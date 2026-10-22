import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useConfirmDialog } from "./useConfirmDialog";

afterEach(cleanup);

const Probe: React.FC<{ onAnswer: (answer: boolean) => void }> = ({ onAnswer }) => {
  const { ask, confirmDialog } = useConfirmDialog();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          void ask({ title: "Delete rule?", message: "It cannot be undone.", confirmText: "Delete rule" }).then(onAnswer);
        }}
      >
        open
      </button>
      {confirmDialog}
    </>
  );
};

describe("useConfirmDialog", () => {
  it("resolves true on the named button and shows its verb, not 'Delete'", async () => {
    const answer = vi.fn();
    render(<Probe onAnswer={answer} />);
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete rule" }));
    });
    expect(answer).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("resolves false on Cancel and on Escape, and starts on the safe button", async () => {
    const answer = vi.fn();
    render(<Probe onAnswer={answer} />);
    fireEvent.click(screen.getByText("open"));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => {
      fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    });
    expect(answer).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
