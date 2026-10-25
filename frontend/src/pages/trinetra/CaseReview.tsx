import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT, SELECT } from "@/components/ui/primitives";
import { decideCredit, getCreditDetail, getInquiryDraft } from "@/services/api/trinetra";
import { errorMessage } from "@/services/api/errors";
import { rupees } from "./format";
import ReviewTools from "./ReviewTools";

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
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const detail = useQuery({
    queryKey: ["trinetra", workspaceId, "case", creditId],
    queryFn: () => getCreditDetail(workspaceId, creditId),
  });
  const draft = useMutation({ mutationFn: () => getInquiryDraft(workspaceId, creditId) });
  const save = useMutation({
    mutationFn: async () => {
      if (!detail.data) {
        throw new Error("Reload the case before reviewing it.");
      }
      return decideCredit(workspaceId, creditId, {
        revision: detail.data.revision,
        action,
        reason,
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
    onSuccess: () => {
      setReason("");
      setAmounts({});
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
        <ReviewTools workspaceId={workspaceId} data={detail.data} canDecide={canDecide} />
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
                {["ALLOCATE", "DISPUTED", "EXPLAINED", "WITHDRAWN", "CA_REVIEWED", "REOPEN"].map(
                  (value) => (
                    <option key={value} value={value}>
                      {value.toLowerCase().replaceAll("_", " ")}
                    </option>
                  ),
                )}
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
            <button className={BUTTON_PRIMARY} disabled={save.isPending}>
              {save.isPending ? "Recording…" : "Record review"}
            </button>
            {save.isError && (
              <p role="alert" className="text-sm text-destructive">
                {errorMessage(save.error, "Review could not be recorded.")}
              </p>
            )}
          </form>
          <button
            className={BUTTON_SECONDARY}
            onClick={() => draft.mutate()}
            disabled={draft.isPending}
          >
            Prepare inquiry draft
          </button>
          {draft.data && (
            <div className="rounded border border-border p-3 text-sm">
              <p className="font-medium">{draft.data.subject}</p>
              <p className="mt-2 whitespace-pre-wrap">{draft.data.body}</p>
              <p className="mt-3 text-xs text-muted-foreground">
                Draft only. No message has been sent.
              </p>
            </div>
          )}
          {draft.isError && <p role="alert">The draft could not be prepared.</p>}
        </>
      )}
    </div>
  );
}
