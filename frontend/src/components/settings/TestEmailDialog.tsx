import React, { useId, useRef } from "react";

import { useDialogFocus } from "@/hooks/useDialogFocus";

interface TestEmailDialogProps {
  isOpen: boolean;
  recipient: string;
  isSending: boolean;
  onRecipientChange: (value: string) => void;
  onCancel: () => void;
  onSend: () => void;
}

export const TestEmailDialog: React.FC<TestEmailDialogProps> = ({
  isOpen,
  recipient,
  isSending,
  onRecipientChange,
  onCancel,
  onSend,
}) => {
  const titleId = useId();
  const inputId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  // A named dialog: Escape closes it (not while a send is under way) and focus starts in the address field.
  useDialogFocus(dialogRef, onCancel, { open: isOpen, busy: isSending });

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-xl border border-border bg-card shadow-2xl"
      >
        <div className="border-b border-border px-6 py-4">
          <h2 id={titleId} className="text-lg font-semibold">
            Send Test Email
          </h2>

          <p className="mt-1 text-sm text-muted-foreground">
            Enter the recipient email address.
          </p>
        </div>

        <div className="space-y-4 p-6">
          <div className="space-y-2">
            <label htmlFor={inputId} className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Recipient Email
            </label>

            <input
              id={inputId}
              type="email"
              value={recipient}
              onChange={(e) => onRecipientChange(e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              placeholder="recipient@example.com"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSending}
            className="rounded-lg border border-border px-4 py-2 text-sm font-semibold"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={onSend}
            disabled={isSending || recipient.trim() === ""}
            className="fp-btn-primary rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {isSending ? "Sending..." : "Send Test Email"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default TestEmailDialog;
