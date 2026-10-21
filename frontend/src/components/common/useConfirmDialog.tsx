import React, { useCallback, useEffect, useRef, useState } from "react";

import { ConfirmDialog } from "./ConfirmDialog";

/**
 * Session J — the easy way to ask a yes/no question inside an event handler, in Servabo's own
 * dialog and never the browser's. It replaces a synchronous `window.confirm`:
 *
 *     const { ask, confirmDialog } = useConfirmDialog();
 *     onClick={async () => { if (await ask({ title: "Delete rule?", message: "…", confirmText: "Delete rule" })) { remove(); } }}
 *     …
 *     {confirmDialog}
 *
 * `confirmText` is required on purpose: `ConfirmDialog` defaults to "Delete", which is wrong on a
 * dialog that deletes nothing. The function is called `ask`, not `confirm`, so the "no native
 * browser dialogs" guard (`npm run check:self`) has nothing to flag.
 */
export interface AskOptions {
  readonly title: string;
  readonly message: string;
  /** A verb that names the action ("Delete rule", "Discard changes"). */
  readonly confirmText: string;
  readonly cancelText?: string;
  /** "danger" (the default) for something that cannot be undone, "primary" otherwise. */
  readonly tone?: "danger" | "primary";
  /** Default "cancel", the safe button. */
  readonly initialFocus?: "confirm" | "cancel";
  /** A single-button notice that has only an acknowledgement. */
  readonly hideCancel?: boolean;
  readonly children?: React.ReactNode;
}

export interface UseConfirmDialog {
  readonly ask: (options: AskOptions) => Promise<boolean>;
  /** Render this once, anywhere in the component. */
  readonly confirmDialog: React.ReactElement | null;
}

export const useConfirmDialog = (): UseConfirmDialog => {
  const [pending, setPending] = useState<AskOptions | null>(null);
  const resolver = useRef<((answer: boolean) => void) | null>(null);

  const settle = useCallback((answer: boolean): void => {
    const resolve = resolver.current;
    resolver.current = null;
    setPending(null);
    resolve?.(answer);
  }, []);

  const ask = useCallback((options: AskOptions): Promise<boolean> => {
    // A second question while one is open answers the first "no".
    resolver.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
      setPending(options);
    });
  }, []);

  // Leaving the page with a question open answers it "no", so nothing waits forever.
  useEffect(
    () => () => {
      resolver.current?.(false);
      resolver.current = null;
    },
    [],
  );

  const confirmDialog = pending ? (
    <ConfirmDialog
      open
      title={pending.title}
      message={pending.message}
      confirmText={pending.confirmText}
      cancelText={pending.cancelText ?? "Cancel"}
      tone={pending.tone ?? "danger"}
      initialFocus={pending.initialFocus ?? "cancel"}
      hideCancel={pending.hideCancel ?? false}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    >
      {pending.children}
    </ConfirmDialog>
  ) : null;

  return { ask, confirmDialog };
};

export default useConfirmDialog;
