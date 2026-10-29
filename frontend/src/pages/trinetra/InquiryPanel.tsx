import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT, SELECT } from "@/components/ui/primitives";
import StatusPill from "@/components/ui/StatusPill";
import { useTenant } from "@/hooks/useTenant";
import { workItemDetailsPath } from "@/routes/tenantPaths";
import { ApiError, errorMessage } from "@/services/api/errors";
import {
  approveInquiry,
  draftInquiry,
  editInquiry,
  getInquiryAllowance,
  listCaseInquiries,
  sendInquiry,
  withdrawInquiry,
  type Inquiry,
} from "@/services/api/trinetra";
import { formatTimestamp } from "@/utils/displayTime";

export const DOCUMENT_WORDS: Readonly<Record<string, string>> = {
  CERTIFICATE: "Tax deduction certificate (Form 16A)",
  DEDUCTOR_ADVICE: "Withholding advice",
  CORRECTION_RESPONSE: "Response to a correction",
};

const STATUS_WORDS: Readonly<Record<string, string>> = {
  DRAFT: "Draft",
  APPROVED: "Approved, not sent",
  SENT: "Sent",
  FAILED: "Could not be sent",
  REPLIED: "Replied",
  WITHDRAWN: "Withdrawn",
};

function InquiryRow({
  workspaceId,
  item,
  canDecide,
}: {
  workspaceId: string;
  item: Inquiry;
  canDecide: boolean;
}) {
  const cache = useQueryClient();
  const { state } = useTenant();
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(item.subject);
  const [body, setBody] = useState(item.body);
  const [override, setOverride] = useState("");
  const [withdrawing, setWithdrawing] = useState(false);
  const [reason, setReason] = useState("");
  const refresh = () => void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
  const edit = useMutation({
    mutationFn: () => editInquiry(workspaceId, item.id, { subject, body }),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const approve = useMutation({
    mutationFn: () => approveInquiry(workspaceId, item.id),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: () => sendInquiry(workspaceId, item.id, override.trim() || undefined),
    onSuccess: refresh,
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawInquiry(workspaceId, item.id, reason),
    onSuccess: () => {
      setWithdrawing(false);
      refresh();
    },
  });
  const tooSoon = send.error instanceof ApiError && send.error.code === "TRINETRA_INQUIRY_TOO_SOON";
  const failure = [edit, approve, send, withdraw].find((m) => m.isError);
  const open = ["DRAFT", "APPROVED", "FAILED"].includes(item.status);
  return (
    <li
      className="space-y-2 rounded-lg border border-border p-3 text-sm"
      data-testid="trinetra-inquiry"
      data-status={item.status}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          {DOCUMENT_WORDS[item.document_kind] ?? item.document_kind}
        </span>
        <StatusPill status={item.status} label={STATUS_WORDS[item.status] ?? item.status} />
      </div>
      {!editing && (
        <>
          <p className="font-medium">{item.subject}</p>
          <p className="whitespace-pre-wrap text-muted-foreground">{item.body}</p>
        </>
      )}
      {item.sent_at && (
        <p className="text-xs text-muted-foreground">
          Sent {formatTimestamp(item.sent_at)} to {item.recipient_masked ?? "the confirmed contact"}
          .
        </p>
      )}
      {item.replied_at && (
        <p className="text-xs" data-testid="trinetra-inquiry-reply">
          The customer replied {formatTimestamp(item.replied_at)}.{" "}
          {state.status === "ready" && item.reply_work_item_id ? (
            <Link
              className="text-primary underline underline-offset-4"
              to={workItemDetailsPath(
                state.organization.organization_slug,
                state.workspace.slug,
                item.reply_work_item_id,
              )}
            >
              Open the document
            </Link>
          ) : null}
        </p>
      )}
      {item.status === "FAILED" && item.delivery_detail && (
        <p className="text-xs text-destructive">{item.delivery_detail}</p>
      )}
      {item.override_reason && (
        <p className="text-xs text-muted-foreground">
          Sent again on purpose: {item.override_reason}
        </p>
      )}
      {canDecide && open && editing && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            edit.mutate();
          }}
        >
          <label className="block">
            Subject
            <input
              required
              minLength={5}
              maxLength={200}
              className={`${INPUT} mt-1`}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </label>
          <label className="block">
            Message
            <textarea
              required
              minLength={10}
              maxLength={2000}
              rows={5}
              className={`${INPUT} mt-1`}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <button className={BUTTON_PRIMARY} disabled={edit.isPending}>
              Save the draft
            </button>
            <button type="button" className={BUTTON_SECONDARY} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {canDecide && open && !editing && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {item.status === "DRAFT" && (
              <>
                <button className={BUTTON_SECONDARY} onClick={() => setEditing(true)}>
                  Edit
                </button>
                <button
                  className={BUTTON_PRIMARY}
                  disabled={approve.isPending}
                  onClick={() => approve.mutate()}
                >
                  Approve the draft
                </button>
              </>
            )}
            {item.status !== "DRAFT" && (
              <button
                className={BUTTON_PRIMARY}
                disabled={send.isPending}
                onClick={() => send.mutate()}
              >
                Press Send
              </button>
            )}
            <button
              className={BUTTON_SECONDARY}
              onClick={() => setWithdrawing(!withdrawing)}
              aria-expanded={withdrawing}
            >
              Withdraw
            </button>
          </div>
          {item.status !== "DRAFT" && (
            <p className="text-xs text-muted-foreground">
              Nothing is sent until you press Send. It goes only to the customer's confirmed
              contact, and asks for a document; it alleges nothing.
            </p>
          )}
          {tooSoon && (
            <label className="block">
              An inquiry about this case went out in the last 7 days. To send another anyway, say
              why:
              <textarea
                minLength={10}
                maxLength={500}
                className={`${INPUT} mt-1`}
                value={override}
                onChange={(e) => setOverride(e.target.value)}
              />
            </label>
          )}
          {withdrawing && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                withdraw.mutate();
              }}
            >
              <label className="block">
                Why you are withdrawing it
                <textarea
                  required
                  minLength={10}
                  maxLength={500}
                  className={`${INPUT} mt-1`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <button className={BUTTON_SECONDARY} disabled={withdraw.isPending}>
                Withdraw this inquiry
              </button>
            </form>
          )}
        </div>
      )}
      {failure && (
        <p role="alert" className="text-destructive">
          {errorMessage(failure.error, "That could not be done.")}
        </p>
      )}
    </li>
  );
}

/** Ask the customer for the document: a draft a person edits, approves and sends (never automatic), the plan's monthly allowance and the replies. */
export default function InquiryPanel({
  workspaceId,
  creditId,
  canDecide,
}: {
  workspaceId: string;
  creditId: string;
  canDecide: boolean;
}) {
  const cache = useQueryClient();
  const inquiries = useQuery({
    queryKey: ["trinetra", workspaceId, "inquiries", creditId],
    queryFn: () => listCaseInquiries(workspaceId, creditId),
  });
  const allowance = useQuery({
    queryKey: ["trinetra", workspaceId, "allowance"],
    queryFn: () => getInquiryAllowance(workspaceId),
  });
  const [kind, setKind] = useState("CERTIFICATE");
  const create = useMutation({
    mutationFn: () => draftInquiry(workspaceId, creditId, { document_kind: kind }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] }),
  });
  return (
    <section
      className="space-y-3 border-t border-border pt-4"
      aria-labelledby={`inquiries-${creditId}`}
      data-testid="trinetra-inquiries"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`inquiries-${creditId}`} className="text-sm font-semibold">
          Ask the customer for the document
        </h3>
        {allowance.data && (
          <span className="text-xs text-muted-foreground" data-testid="trinetra-allowance">
            {allowance.data.used} of {allowance.data.limit} sent this month
          </span>
        )}
      </div>
      {inquiries.isPending && (
        <p role="status" className="text-sm">
          Loading inquiries…
        </p>
      )}
      {inquiries.isError && (
        <p role="alert" className="text-sm text-destructive">
          The inquiries could not be loaded.
        </p>
      )}
      {inquiries.data && !inquiries.data.items.length && (
        <p className="text-sm text-muted-foreground">
          No inquiry yet. A draft is only ever sent by a person pressing Send.
        </p>
      )}
      <ul className="space-y-2">
        {inquiries.data?.items.map((item) => (
          <InquiryRow
            key={`${item.id}-${item.status}-${item.subject}`}
            workspaceId={workspaceId}
            item={item}
            canDecide={canDecide}
          />
        ))}
      </ul>
      {canDecide && (
        <form
          className="flex flex-wrap items-end gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label>
            Ask for
            <select
              className={`${SELECT} ml-2`}
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {Object.entries(DOCUMENT_WORDS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button className={BUTTON_SECONDARY} disabled={create.isPending}>
            Prepare a draft
          </button>
        </form>
      )}
      {create.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(create.error, "The draft could not be prepared.")}
        </p>
      )}
    </section>
  );
}
