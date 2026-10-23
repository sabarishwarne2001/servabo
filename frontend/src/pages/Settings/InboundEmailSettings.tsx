/**
 * Settings → Email-in (Final session 1, 2B): the address a workspace receives documents at, who may send to it, the messages
 * held for approval and what arrived lately. Workspace administrators only.
 *
 * The address is long and random (never the workspace's name), shown with a copy button. "Rotate" replaces it; the old one
 * stops working at once (mail sent to it is refused, so nothing is lost silently, Postmark stops retrying). Rotating asks in the
 * app's own dialog, never a browser pop-up. Mail from anyone not on the list is held here, never dropped.
 */
import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Mail, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useConfirmDialog } from "@/components/common/useConfirmDialog";
import { ApiError } from "@/services/api/client";
import {
  addInboundSender,
  approveInboundMessage,
  discardInboundMessage,
  getInboundEmail,
  inboundEmailKeys,
  removeInboundSender,
  rotateInboundAddress,
  type InboundMessageView,
} from "@/services/api/inboundEmail";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, HINT, INPUT, SECTION_TITLE, SURFACE } from "@/components/ui/primitives";
import { formatTimestamp } from "@/utils/displayTime";
import { useResolvedTenant } from "@/routes/TenantContext";

const OUTCOME_WORDS: Readonly<Record<string, string>> = {
  ADDED: "Added as a document",
  ZIP_QUEUED: "Zip: its documents are being added",
  SKIPPED_GSTR2B: "Set aside",
  IGNORED_INLINE: "Ignored",
  REFUSED: "Not added",
  UNREADABLE: "Not readable",
  HELD: "Waiting",
  DISCARDED: "Discarded",
};

const reason = (error: unknown, fallback: string): string => (error instanceof ApiError && error.message ? error.message : fallback);

const MessageRow: React.FC<{
  readonly message: InboundMessageView;
  readonly onApprove?: () => void;
  readonly onDiscard?: () => void;
  readonly busy: boolean;
}> = ({ message, onApprove, onDiscard, busy }) => (
  <li className="space-y-1.5 rounded-lg border border-border/60 p-3" data-testid="inbound-message" data-status={message.status}>
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-foreground">{message.subject || "(no subject)"}</p>
        <p className={HINT}>
          From {message.from_name ? `${message.from_name} ` : ""}
          <span className="font-medium text-foreground">{message.from_address}</span>
          {message.received_at ? ` · ${formatTimestamp(message.received_at)}` : ""}
        </p>
      </div>
      <span
        className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
          message.status === "HELD"
            ? "bg-amber-500/15 text-amber-800 dark:text-amber-300"
            : message.status === "ACCEPTED"
              ? "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300"
              : "bg-muted text-muted-foreground"
        }`}
      >
        {message.status === "HELD" ? "Held" : message.status === "ACCEPTED" ? "Accepted" : "Discarded"}
      </span>
    </div>
    {message.hold_message && message.status === "HELD" && <p className="text-xs text-amber-800 dark:text-amber-300">{message.hold_message}</p>}
    {message.attachments.length > 0 && (
      <ul className="space-y-0.5 text-xs text-muted-foreground">
        {message.attachments.map((file, index) => (
          <li key={`${file.name}:${index}`}>
            <span className="font-medium text-foreground">{file.name}</span>: {OUTCOME_WORDS[file.outcome] ?? file.outcome}
            {file.note ? `. ${file.note}` : ""}
          </li>
        ))}
      </ul>
    )}
    {message.status === "HELD" && (onApprove || onDiscard) && (
      <div className="flex gap-2 pt-1">
        {message.can_approve && onApprove && (
          <button type="button" className={BUTTON_PRIMARY} disabled={busy} onClick={onApprove}>
            Approve
          </button>
        )}
        {onDiscard && (
          <button type="button" className={BUTTON_SECONDARY} disabled={busy} onClick={onDiscard}>
            Discard
          </button>
        )}
      </div>
    )}
  </li>
);

export const InboundEmailSettings: React.FC = () => {
  const { workspace } = useResolvedTenant();
  const workspaceId = workspace.id;
  const queryClient = useQueryClient();
  const { ask, confirmDialog } = useConfirmDialog();
  const [pattern, setPattern] = useState("");

  const view = useQuery({ queryKey: inboundEmailKeys.all(workspaceId), queryFn: () => getInboundEmail(workspaceId), retry: false });
  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: inboundEmailKeys.all(workspaceId) });
    void queryClient.invalidateQueries({ queryKey: ["ws", workspaceId, "work-items"] });
  };

  const rotate = useMutation({
    mutationFn: () => rotateInboundAddress(workspaceId),
    onSuccess: () => {
      toast.success("A new address is ready. The old one no longer works.");
      refresh();
    },
    onError: (error) => toast.error(reason(error, "The address could not be changed. Try again.")),
  });
  const add = useMutation({
    mutationFn: (value: string) => addInboundSender(workspaceId, value),
    onSuccess: () => {
      setPattern("");
      refresh();
    },
    onError: (error) => toast.error(reason(error, "That sender could not be added.")),
  });
  const remove = useMutation({
    mutationFn: (id: string) => removeInboundSender(workspaceId, id),
    onSuccess: refresh,
    onError: (error) => toast.error(reason(error, "That sender could not be removed.")),
  });
  const approve = useMutation({
    mutationFn: (id: string) => approveInboundMessage(workspaceId, id),
    onSuccess: (result) => {
      if (result.result === "accepted") {
        toast.success(result.documents === 1 ? "1 document added. Processing has started." : `${result.documents} documents added. Processing has started.`);
      } else {
        toast.error(result.message.hold_message ?? "The message is still held.");
      }
      refresh();
    },
    onError: (error) => toast.error(reason(error, "The message could not be approved.")),
  });
  const discard = useMutation({
    mutationFn: (id: string) => discardInboundMessage(workspaceId, id),
    onSuccess: () => {
      toast.success("Discarded.");
      refresh();
    },
    onError: (error) => toast.error(reason(error, "The message could not be discarded.")),
  });

  const copy = async (text: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Address copied.");
    } catch {
      toast.error("Copying did not work here. Select the address and copy it.");
    }
  };

  if (view.isLoading) {
    return <div className={`${SURFACE} p-6 text-sm text-muted-foreground`}>Loading…</div>;
  }
  if (view.isError || !view.data) {
    return (
      <div className={`${SURFACE} p-6 text-sm`} role="alert">
        Email-in could not be loaded. Reload the page, or try again in a moment.
      </div>
    );
  }
  const data = view.data;
  const held = data.messages.filter((message) => message.status === "HELD");
  const arrivals = data.messages.filter((message) => message.status !== "HELD");
  const busy = approve.isPending || discard.isPending;

  return (
    <div className="space-y-6" data-testid="email-in">
      <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="email-in-address-title">
        <div className="flex items-center gap-2">
          <Mail className="h-4 w-4 text-muted-foreground" aria-hidden />
          <h2 id="email-in-address-title" className={SECTION_TITLE}>
            Email-in
          </h2>
        </div>
        <p className={HINT}>
          Forward invoices and other documents to this workspace&apos;s own address. Each attachment becomes a document, a zip
          becomes all the documents inside it, and everything feeds GST credit, Helm and the value receipt like any upload.
        </p>
        {data.enabled && data.address ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <code className="break-all rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm" data-testid="email-in-address">
                {data.address}
              </code>
              <button type="button" className={BUTTON_SECONDARY} onClick={() => void copy(data.address ?? "")} aria-label="Copy the address">
                <Copy className="h-4 w-4" aria-hidden /> Copy
              </button>
              <button
                type="button"
                className={BUTTON_SECONDARY}
                disabled={rotate.isPending}
                onClick={() =>
                  void ask({
                    title: "Change this address?",
                    message:
                      "A new address replaces this one at once. Anything still sent to the old address is refused, so ask your suppliers and your mail rules to use the new one.",
                    confirmText: "Change address",
                  }).then((yes) => {
                    if (yes) {rotate.mutate();}
                  })
                }
              >
                <RefreshCw className="h-4 w-4" aria-hidden /> Change address
              </button>
            </div>
            <p className={HINT}>
              The address is random on purpose: it never contains the workspace&apos;s name. Anyone who has it can email documents, but
              only the senders below are added straight away; everyone else&apos;s mail waits here for you.
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="email-in-off">
            Email-in is not switched on yet for this Servabo. When it is, this page shows the address to forward to.
          </p>
        )}
      </section>

      <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="email-in-senders-title">
        <h2 id="email-in-senders-title" className={SECTION_TITLE}>
          Allowed senders
        </h2>
        <p className={HINT}>
          An email address (ap@supplier.in) or a whole domain (supplier.in). Mail from anyone else is held for you to approve; nothing is ever dropped quietly.
        </p>
        <form
          className="flex flex-wrap items-start gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (pattern.trim()) {add.mutate(pattern.trim());}
          }}
        >
          <label className="sr-only" htmlFor="email-in-sender">
            Sender address or domain
          </label>
          <input
            id="email-in-sender"
            className={`${INPUT} w-72 max-w-full`}
            value={pattern}
            placeholder="ap@supplier.in or supplier.in"
            onChange={(event) => setPattern(event.target.value)}
          />
          <button type="submit" className={BUTTON_PRIMARY} disabled={add.isPending || !pattern.trim()}>
            Allow
          </button>
        </form>
        {data.senders.length === 0 ? (
          <p className={HINT} data-testid="email-in-no-senders">
            No sender is allowed yet, so every message will wait here for approval.
          </p>
        ) : (
          <ul className="divide-y divide-border/60" data-testid="email-in-senders">
            {data.senders.map((sender) => (
              <li key={sender.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                <span className="font-medium">{sender.pattern}</span>
                <button
                  type="button"
                  className="rounded-md p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  aria-label={`Stop allowing ${sender.pattern}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(sender.id)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="email-in-held-title">
        <h2 id="email-in-held-title" className={SECTION_TITLE}>
          Waiting for you {held.length > 0 ? `(${held.length})` : ""}
        </h2>
        {held.length === 0 ? (
          <p className={HINT}>Nothing is waiting.</p>
        ) : (
          <ul className="space-y-2" data-testid="email-in-held">
            {held.map((message) => (
              <MessageRow
                key={message.id}
                message={message}
                busy={busy}
                onApprove={() => approve.mutate(message.id)}
                onDiscard={() =>
                  void ask({
                    title: "Discard this message?",
                    message: `The message from ${message.from_address} and its attachments are thrown away. It cannot be brought back.`,
                    confirmText: "Discard",
                  }).then((yes) => {
                    if (yes) {discard.mutate(message.id);}
                  })
                }
              />
            ))}
          </ul>
        )}
      </section>

      <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="email-in-recent-title">
        <h2 id="email-in-recent-title" className={SECTION_TITLE}>
          Recent arrivals
        </h2>
        {arrivals.length === 0 ? (
          <p className={HINT}>Nothing has arrived by email yet.</p>
        ) : (
          <ul className="space-y-2" data-testid="email-in-arrivals">
            {arrivals.map((message) => (
              <MessageRow key={message.id} message={message} busy={busy} />
            ))}
          </ul>
        )}
      </section>
      {confirmDialog}
    </div>
  );
};

export default InboundEmailSettings;
