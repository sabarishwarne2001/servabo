/**
 * Session J — "Test & preview".
 *
 * Two questions in one place. "Try it on a document": pick a recent document and see which way the conditions go, with
 * the reason for each, and what every step would do, with the message it would send filled in from that document.
 * "The last 30 days": how often it would have fired, on what, and a warning when it would be noisy. Both are read-only on
 * the server: nothing is sent, run or written.
 */

import React, { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { ApiError } from "@/services/api/errors";
import { workItemApi } from "@/services/api/workItem";
import { workItemKeys } from "@/services/api/queryKeys";
import { formatTimestampDate } from "@/utils/displayTime";
import type { DraftTestResult, PreviewResult } from "@/types/automationVolume";
import { inputClass } from "./StepCard";

interface TestPreviewDialogProps {
  readonly open: boolean;
  readonly workspaceId: string;
  /** Works out the 30-day preview: a draft rule, or a saved one. */
  readonly loadPreview: () => Promise<PreviewResult>;
  /** Tries the rule on one document. Omitted for a saved rule shown from the home page. */
  readonly tryOnDocument?: ((workItemId: string) => Promise<DraftTestResult>) | undefined;
  readonly onClose: () => void;
  readonly title?: string | undefined;
}

type Tab = "document" | "history";

const Stat: React.FC<{ readonly label: string; readonly value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-border bg-muted/30 px-3 py-2">
    <dd className="text-xl font-semibold tabular-nums">{value}</dd>
    <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</dt>
  </div>
);

const messageOf = (error: unknown): string =>
  error instanceof ApiError ? error.message : "That could not be worked out. Try again in a moment.";

const RENDER_LABELS: Readonly<Record<string, string>> = { title: "Title", subject: "Subject", message: "Message", body: "Body", reason: "Reason" };

const DocumentTab: React.FC<{
  readonly workspaceId: string;
  readonly open: boolean;
  readonly tryOnDocument: (workItemId: string) => Promise<DraftTestResult>;
}> = ({ workspaceId, open, tryOnDocument }) => {
  const [workItemId, setWorkItemId] = useState("");
  const documents = useQuery({
    queryKey: workItemKeys.list(workspaceId, { page: 1, pageSize: 100 }),
    queryFn: async () => (await workItemApi.getWorkItems(workspaceId, { page: 1, pageSize: 100 })).items,
    enabled: open && Boolean(workspaceId),
    staleTime: 30_000,
  });
  const run = useMutation({ mutationFn: (id: string) => tryOnDocument(id) });
  const result = run.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[14rem] flex-1">
          <label htmlFor="try-document" className="mb-1 block text-xs font-semibold">Pick a recent document</label>
          <select
            id="try-document"
            value={workItemId}
            onChange={(e) => {
              setWorkItemId(e.target.value);
              run.reset();
            }}
            className={inputClass(false)}
          >
            <option value="">{documents.isLoading ? "Loading documents…" : "Choose a document…"}</option>
            {(documents.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.original_filename}</option>
            ))}
          </select>
        </div>
        <button
          type="button"
          disabled={!workItemId || run.isPending}
          onClick={() => run.mutate(workItemId)}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {run.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Try it
        </button>
      </div>
      {documents.isError && <p role="alert" className="text-sm text-destructive">The documents could not be loaded.</p>}
      {run.isError && <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-semibold text-destructive">{messageOf(run.error)}</p>}
      {result && (
        <div className="space-y-3" aria-live="polite">
          <p className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${
            result.matched ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300" : "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300"
          }`}>
            {result.matched ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
            {result.matched
              ? `The conditions are met for ${result.document ?? "this document"}: the Then steps would run.`
              : result.branch === "otherwise"
                ? `The conditions are not met for ${result.document ?? "this document"}: the Otherwise steps would run.`
                : `The conditions are not met for ${result.document ?? "this document"}: nothing would run.`}
          </p>
          {result.conditions.length > 0 && (
            <ul className="space-y-1 text-sm" aria-label="What each condition decided">
              {result.conditions.map((condition, i) => (
                <li key={i} className={condition.matched ? "text-emerald-700 dark:text-emerald-400" : "text-foreground"}>
                  {condition.matched ? "✓" : "✗"} {condition.reason}
                </li>
              ))}
            </ul>
          )}
          {result.steps.length > 0 && (
            <ol className="space-y-2" aria-label="What each step would do">
              {result.steps.map((step) => (
                <li key={step.index} className="rounded-lg border border-border p-3">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                    <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">#{step.index}</span>
                    {step.label}
                    {!step.ok && <span className="inline-flex items-center gap-1 text-xs text-destructive"><AlertTriangle className="h-3 w-3" aria-hidden="true" /> {step.problem}</span>}
                  </p>
                  {Object.entries(step.rendered).map(([key, text]) => (
                    <p key={key} className="mt-1.5 rounded-md bg-muted/40 px-2.5 py-1.5 text-xs">
                      <span className="font-semibold text-muted-foreground">{RENDER_LABELS[key] ?? key}: </span>
                      <span className="whitespace-pre-wrap break-words">{text || "(empty)"}</span>
                    </p>
                  ))}
                  {step.idempotent === false && (
                    <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-muted-foreground">
                      <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" /> Sends something people notice. Nothing was sent now.
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
          {result.event === null && (
            <p className="text-xs text-muted-foreground">
              No recorded event for this document, so the trigger&rsquo;s own facts (severity, amounts) are blank in the messages.
            </p>
          )}
        </div>
      )}
    </div>
  );
};

const HistoryTab: React.FC<{ readonly open: boolean; readonly load: () => Promise<PreviewResult> }> = ({ open, load }) => {
  const run = useMutation({ mutationFn: load });
  useEffect(() => {
    if (open) {run.mutate();}
  }, [open]);
  const result = run.data;
  return (
    <div className="space-y-4" aria-live="polite">
      {run.isPending && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Looking through the last 30 days…
        </p>
      )}
      {run.isError && <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-semibold text-destructive">{messageOf(run.error)}</p>}
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
                  <li key={`${action.action_type}-${i}`}>{action.label} <span className="text-muted-foreground">× {action.times}</span></li>
                ))}
              </ul>
            </div>
          )}
          {result.samples.length > 0 && (
            <div>
              <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">The latest {result.samples.length}</h4>
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
  );
};

export const TestPreviewDialog: React.FC<TestPreviewDialogProps> = ({ open, workspaceId, loadPreview, tryOnDocument, onClose, title }) => {
  const [tab, setTab] = useState<Tab>(tryOnDocument ? "document" : "history");
  useEffect(() => {
    if (open) {setTab(tryOnDocument ? "document" : "history");}
  }, [open, tryOnDocument]);

  return (
    <ConfirmDialog
      open={open}
      wide
      hideCancel
      tone="primary"
      title={title ?? "Test & preview"}
      message="Nothing is sent, run or changed. This only shows what the rule would do, using the same checks it runs."
      confirmText="Close"
      onConfirm={onClose}
      onCancel={onClose}
    >
      <div className="mt-4 text-left">
        {tryOnDocument && (
          <div role="tablist" aria-label="Test and preview" className="mb-4 flex gap-1 border-b border-border">
            {([["document", "Try it on a document"], ["history", "The last 30 days"]] as const).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-semibold ${
                  tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        {tab === "document" && tryOnDocument ? (
          <DocumentTab workspaceId={workspaceId} open={open} tryOnDocument={tryOnDocument} />
        ) : (
          <HistoryTab open={open && tab === "history"} load={loadPreview} />
        )}
      </div>
    </ConfirmDialog>
  );
};
