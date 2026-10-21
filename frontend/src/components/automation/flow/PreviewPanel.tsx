/**
 * Session J — "Test & preview": what the rule would have done on the last 30 days. Read-only on the server: it counts,
 * it never acts. Shown in Servabo's own dialog (focus trap, Escape closes only this).
 */

import React, { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { ApiError } from "@/services/api/errors";
import { formatTimestampDate } from "@/utils/displayTime";
import type { PreviewResult } from "@/types/automationVolume";

interface PreviewPanelProps {
  readonly open: boolean;
  /** Works out the preview when the dialog opens: a draft rule, or a saved one. */
  readonly load: () => Promise<PreviewResult>;
  readonly onClose: () => void;
  readonly title?: string | undefined;
}

const Stat: React.FC<{ readonly label: string; readonly value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
    <dd className="text-xl font-semibold tabular-nums">{value}</dd>
    <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</dt>
  </div>
);

export const PreviewPanel: React.FC<PreviewPanelProps> = ({ open, load, onClose, title }) => {
  const run = useMutation({ mutationFn: load });

  // The preview runs once each time the dialog opens, on the rule as it is then.
  useEffect(() => {
    if (open) {run.mutate();}
  }, [open]);

  const result = run.data;
  const error =
    run.error instanceof ApiError
      ? run.error.message
      : run.error
        ? "The preview could not be worked out. Try again in a moment."
        : null;

  return (
    <ConfirmDialog
      open={open}
      wide
      hideCancel
      tone="primary"
      title={title ?? "What this rule would have done in the last 30 days"}
      message="Nothing is sent or changed. This only counts, using the same checks the rule runs."
      confirmText="Close"
      onConfirm={onClose}
      onCancel={onClose}
    >
      <div className="mt-4 space-y-4 text-left" aria-live="polite">
        {run.isPending && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Looking through the last 30 days…
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-semibold text-destructive">
            {error}
          </p>
        )}
        {result && (
          <>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Would have run" value={String(result.would_run)} />
              <Stat label="Looked at" value={String(result.events_examined)} />
              <Stat label="Average a day" value={String(result.average_per_day)} />
              <Stat label="Busiest day" value={String(result.peak_per_day)} />
            </dl>
            {result.warnings.length > 0 && (
              <ul className="space-y-1.5" aria-label="Warnings">
                {result.warnings.map((warning) => (
                  <li key={warning} className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-800 dark:text-amber-300">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /> {warning}
                  </li>
                ))}
              </ul>
            )}
            {result.would_run === 0 && result.no_history.length === 0 && (
              <p className="text-sm text-muted-foreground">
                It would not have run on anything in the last 30 days. If that is not what you expect, check the conditions.
              </p>
            )}
            {result.actions.length > 0 && result.would_run > 0 && (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Each time it would</h4>
                <ul className="space-y-1 text-sm">
                  {result.actions.map((action, i) => (
                    <li key={`${action.action_type}-${i}`}>
                      {action.label} <span className="text-muted-foreground">× {action.times}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.samples.length > 0 && (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  The latest {result.samples.length}
                </h4>
                <ul className="divide-y divide-border/60 rounded-lg border border-border text-sm">
                  {result.samples.map((sample, i) => (
                    <li key={`${sample.occurred_at}-${i}`} className="flex items-center justify-between gap-3 px-3 py-1.5">
                      <span className="min-w-0 truncate">{sample.filename ?? sample.trigger}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{formatTimestampDate(sample.occurred_at)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </ConfirmDialog>
  );
};
