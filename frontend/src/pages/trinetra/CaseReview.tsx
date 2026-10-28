import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT, SELECT } from "@/components/ui/primitives";
import { decideCredit, getCreditDetail } from "@/services/api/trinetra";
import { errorMessage } from "@/services/api/errors";
import { rupees } from "./format";
import InquiryPanel from "./InquiryPanel";
import ReviewTools from "./ReviewTools";

export const DECISIONS: readonly (readonly [string, string])[] = [
  ["ALLOCATE", "Allocate a statement posting"],
  ["DISPUTED", "Mark as disputed"],
  ["EXPLAINED", "Close with an explanation"],
  ["WITHDRAWN", "Withdraw the case"],
  ["CA_REVIEWED", "Confirmed by the accountant"],
  ["UNRESOLVED", "Leave unresolved"],
  ["REJECT_MATCH", "This statement row is not the match"],
  ["ANNOTATE", "Add a note to the case"],
  ["REOPEN", "Reopen"],
];

export default function CaseReview({
  workspaceId,
  creditId,
  canDecide,
}: {
  workspaceId: string;
  creditId: string;
  canDecide: boolean;
}) {
  const cache = useQueryClient();
  const [action, setAction] = useState("ALLOCATE");
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState("0");
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [line, setLine] = useState("");
  const [note, setNote] = useState("");
  const [waiting, setWaiting] = useState<string | null>(null);
  const detail = useQuery({
    queryKey: ["trinetra", workspaceId, "case", creditId],
    queryFn: () => getCreditDetail(workspaceId, creditId),
  });
  const save = useMutation({
    mutationFn: async () => {
      if (!detail.data) {
        throw new Error("Reload the case before reviewing it.");
      }
      const chosen = detail.data.statement_lines.find((l) => l.id === line);
      return decideCredit(workspaceId, creditId, {
        revision: detail.data.revision,
        action,
        reason,
        review_minutes: Number(minutes),
        ...(action === "REJECT_MATCH" || action === "ANNOTATE"
          ? {
              ...(chosen ? { snapshot_id: chosen.snapshot_id, line_id: chosen.id } : {}),
              ...(action === "ANNOTATE" ? { note } : {}),
            }
          : {}),
        allocations:
          action === "ALLOCATE"
            ? detail.data.statement_lines
                .filter((line) => Boolean(amounts[line.id]))
                .map((line) => ({
                  snapshot_id: line.snapshot_id,
                  line_id: line.id,
                  amount: amounts[line.id],
                }))
            : [],
      });
    },
    onSuccess: (result) => {
      // Enterprise: a closure above the organization's threshold waits for a second person (HTTP 202; nothing is closed yet).
      const asked = result as unknown as { approval_required?: boolean; message?: string };
      setWaiting(
        asked.approval_required
          ? (asked.message ?? "This closure needs a second person's approval.")
          : null,
      );
      setReason("");
      setMinutes("0");
      setAmounts({});
      setNote("");
      void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
    },
  });
  if (detail.isPending) {
    return <p role="status">Loading review history…</p>;
  }
  if (detail.isError) {
    return (
      <p role="alert">
        Review history could not be loaded.{" "}
        <button className={BUTTON_SECONDARY} onClick={() => void detail.refetch()}>
          Try again
        </button>
      </p>
    );
  }
  return (
    <div className="space-y-4 border-t border-border pt-4">
      {detail.data && (
        <ReviewTools
          key={detail.data.revision}
          workspaceId={workspaceId}
          data={detail.data}
          canDecide={canDecide}
        />
      )}
      <h3 className="text-sm font-semibold">Review history</h3>
      <ol className="space-y-2 text-xs">
        {detail.data?.events.map((event) => (
          <li key={event.revision}>
            <span className="font-medium">
              Revision {event.revision} · {event.action.toLowerCase().replaceAll("_", " ")}
            </span>
            <p className="text-muted-foreground">{event.reason}</p>
          </li>
        ))}
      </ol>
      {canDecide && (
        <>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <label className="block text-sm">
              Review decision
              <select
                className={`${SELECT} mt-1 w-full`}
                value={action}
                onChange={(e) => setAction(e.target.value)}
              >
                {DECISIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {action === "ALLOCATE" && (
              <fieldset className="space-y-3">
                <legend className="text-xs">
                  Allocate only amounts you verified against the source
                </legend>
                {detail.data?.statement_lines.map((line) => (
                  <label className="block text-xs" key={line.id}>
                    Posting {Number(line.id) + 1} · available {rupees(line.available_micros)}
                    <input
                      className={`${INPUT} mt-1`}
                      inputMode="decimal"
                      pattern="[0-9]+(\.[0-9]{1,2})?"
                      value={amounts[line.id] ?? ""}
                      onChange={(e) => setAmounts({ ...amounts, [line.id]: e.target.value })}
                      placeholder="Amount in INR"
                    />
                  </label>
                ))}
              </fieldset>
            )}
            {(action === "REJECT_MATCH" || action === "ANNOTATE") && (
              <label className="block text-sm">
                {action === "REJECT_MATCH"
                  ? "The statement row that is not the match"
                  : "The statement row this is about (optional)"}
                <select
                  className={`${SELECT} mt-1 w-full`}
                  required={action === "REJECT_MATCH"}
                  value={line}
                  onChange={(e) => setLine(e.target.value)}
                >
                  <option value="">Choose a row</option>
                  {detail.data?.statement_lines.map((l) => (
                    <option key={l.id} value={l.id}>
                      Posting {Number(l.id) + 1} · {rupees(l.amount_micros)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {action === "ANNOTATE" && (
              <label className="block text-sm">
                The note
                <textarea
                  required
                  maxLength={500}
                  className={`${INPUT} mt-1`}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
            )}
            <label className="block text-sm">
              Reason and evidence
              <textarea
                required
                minLength={10}
                maxLength={1000}
                className={`${INPUT} mt-1`}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              Minutes spent on this review (optional)
              <input
                type="number"
                min={0}
                max={480}
                step={1}
                className={`${INPUT} mt-1`}
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
              />
            </label>
            <button className={BUTTON_PRIMARY} disabled={save.isPending}>
              {save.isPending ? "Recording…" : "Record review"}
            </button>
            {save.isError && (
              <p role="alert" className="text-sm text-destructive">
                {errorMessage(save.error, "Review could not be recorded.")}
              </p>
            )}
            {waiting && (
              <p role="status" className="text-sm" data-testid="trinetra-approval-requested">
                {waiting}
              </p>
            )}
          </form>
        </>
      )}
      <InquiryPanel workspaceId={workspaceId} creditId={creditId} canDecide={canDecide} />
    </div>
  );
}
