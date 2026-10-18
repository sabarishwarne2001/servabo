/**
 * Phase 1 — the workspace's dispatch policy: where straight-through starts, where exceptions
 * start, and whether a missing required field holds a document for review. Admins change it.
 */
import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, SlidersHorizontal } from "lucide-react";

import { batchKeys, getDispatchPolicy, saveDispatchPolicy } from "@/services/api/batches";
import { errorMessage } from "@/services/api/errors";
import { LaneChip } from "@/components/batches/shared";

const toPercent = (value: number): number => Math.round(value * 100);

const ThresholdRow: React.FC<{
  readonly lane: "STRAIGHT_THROUGH" | "EXCEPTION";
  readonly relation: string;
  readonly value: number;
  readonly min: number;
  readonly ariaLabel: string;
  readonly accent: string;
  readonly disabled: boolean;
  readonly onChange: (next: number) => void;
}> = ({ lane, relation, value, min, ariaLabel, accent, disabled, onChange }) => (
  <label className="block space-y-2">
    <span className="flex items-center justify-between gap-3">
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <LaneChip lane={lane} />
        <span className="text-xs font-medium text-muted-foreground">{relation}</span>
      </span>
      <span className="fp-num shrink-0 rounded-md border border-border bg-muted/50 px-2 py-0.5 text-sm font-semibold tabular-nums">
        {value}%
      </span>
    </span>
    <input
      type="range" min={min} max={100} step={1} value={value} disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
      aria-label={ariaLabel}
      className={`block w-full min-w-0 ${accent} disabled:opacity-60`}
    />
  </label>
);

/** The three lanes drawn to scale on one bar, with the middle (review) range spelled out. */
const LaneScale: React.FC<{ readonly floor: number; readonly straight: number }> = ({ floor, straight }) => {
  const low = Math.min(floor, straight);
  const high = Math.max(floor, straight);
  return (
    <div className="space-y-1.5" data-testid="dispatch-lane-scale">
      <div aria-hidden className="flex h-2 overflow-hidden rounded-full bg-muted">
        <span className="bg-destructive/70" style={{ width: `${low}%` }} />
        <span className="bg-amber-500/70" style={{ width: `${high - low}%` }} />
        <span className="flex-1 bg-emerald-500/70" />
      </div>
      <p className="text-xs leading-snug text-muted-foreground">
        {low === high
          ? "No documents fall in the review lane."
          : `Scores from ${low}% to just under ${high}% go to human review.`}
      </p>
    </div>
  );
};

export const DispatchPolicyCard: React.FC<{ readonly workspaceId: string; readonly canEdit: boolean }> = ({
  workspaceId,
  canEdit,
}) => {
  const client = useQueryClient();
  const policy = useQuery({ queryKey: batchKeys.policy(workspaceId), queryFn: () => getDispatchPolicy(workspaceId) });
  const [straight, setStraight] = useState(90);
  const [floor, setFloor] = useState(60);
  const [requireFields, setRequireFields] = useState(true);
  const [tag, setTag] = useState(true);

  useEffect(() => {
    if (policy.data) {
      setStraight(toPercent(policy.data.straight_through_min_confidence));
      setFloor(toPercent(policy.data.review_min_confidence));
      setRequireFields(policy.data.require_required_fields);
      setTag(policy.data.tag_documents);
    }
  }, [policy.data]);

  const save = useMutation({
    mutationFn: () =>
      saveDispatchPolicy(workspaceId, {
        straight_through_min_confidence: straight / 100,
        review_min_confidence: floor / 100,
        require_required_fields: requireFields,
        tag_documents: tag,
      }),
    onSuccess: async () => {
      toast.success("Dispatch policy saved. It applies the next time a batch is dispatched.");
      await client.invalidateQueries({ queryKey: batchKeys.all(workspaceId) });
    },
    onError: (error) => toast.error(errorMessage(error, "The policy could not be saved.")),
  });

  const invalid = floor > straight;
  const dirty =
    policy.data !== undefined &&
    (straight !== toPercent(policy.data.straight_through_min_confidence) ||
      floor !== toPercent(policy.data.review_min_confidence) ||
      requireFields !== policy.data.require_required_fields ||
      tag !== policy.data.tag_documents);

  return (
    <section className="fp-card space-y-4 p-4" aria-labelledby="policy-title" data-testid="dispatch-policy">
      <header className="flex items-start gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/60 text-muted-foreground">
          <SlidersHorizontal className="h-4 w-4" aria-hidden />
        </span>
        <div>
          <h2 id="policy-title" className="text-[15px] font-semibold tracking-tight">Dispatch policy</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Verified documents at or above the straight-through threshold, with every required field, go straight
            through. Below the floor they are exceptions. Unverified documents always go to review.
          </p>
        </div>
      </header>
      {policy.isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading" />
      ) : (
        <>
          {/*
           * The card sits in a narrow column beside the batch list, so its width follows the page's
           * column and not the viewport. Each threshold therefore gets its own full-width row (never a
           * viewport-breakpoint grid): the lane chip and its "from" / "below" wording on the left, the
           * value on the right, the track underneath. Nothing shares a line with another control, and
           * the label side wraps instead of running into the value.
           */}
          <div className="space-y-5">
            <ThresholdRow
              lane="STRAIGHT_THROUGH"
              relation="from"
              value={straight}
              min={50}
              ariaLabel="Straight-through threshold (percent)"
              accent="accent-emerald-600"
              disabled={!canEdit}
              onChange={setStraight}
            />
            <ThresholdRow
              lane="EXCEPTION"
              relation="below"
              value={floor}
              min={0}
              ariaLabel="Exception floor (percent)"
              accent="accent-red-600"
              disabled={!canEdit}
              onChange={setFloor}
            />
            <LaneScale floor={floor} straight={straight} />
          </div>
          {invalid ? (
            <p role="alert" className="text-xs text-destructive">The exception floor cannot be above the straight-through threshold.</p>
          ) : null}
          <div className="space-y-2 text-sm">
            <label className="flex items-start gap-2.5">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-primary" checked={requireFields} disabled={!canEdit}
                     onChange={(e) => setRequireFields(e.target.checked)} />
              A missing required field holds the document for review
            </label>
            <label className="flex items-start gap-2.5">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-primary" checked={tag} disabled={!canEdit}
                     onChange={(e) => setTag(e.target.checked)} />
              Tag dispatched documents (dispatch-straight-through, dispatch-review, dispatch-exception)
            </label>
            <p className="pl-[1.625rem] text-xs text-muted-foreground" data-testid="tag-documents-note">
              Switching this off stops new tags; the tags already written stay on their documents.
            </p>
          </div>
          {canEdit ? (
            <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
              {policy.data?.is_default ? <span className="text-xs text-muted-foreground">Using the defaults</span> : null}
              <button
                type="button"
                className="fp-btn fp-btn-primary h-8 text-xs"
                disabled={!dirty || invalid || save.isPending}
                onClick={() => save.mutate()}
              >
                {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                Save policy
              </button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Workspace admins can change the policy.</p>
          )}
        </>
      )}
    </section>
  );
};

export default DispatchPolicyCard;
