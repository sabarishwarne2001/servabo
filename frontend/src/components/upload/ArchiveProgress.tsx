/**
 * One zip in the upload tray: a parent row with per-file progress while it is unpacked, then a plain summary
 * (Final session 1, 2A). The batch is read from the server; nothing here decides what was added.
 */
import React, { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileArchive, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";

import ViewPlansAction from "@/components/billing/ViewPlansAction";
import { summariseArchive } from "@/components/upload/archiveSummary";
import { useTenant } from "@/hooks/useTenant";
import { getBatch } from "@/services/api/ingestion";
import { ingestionKeys } from "@/services/api/queryKeys";
import { gstPath } from "@/routes/tenantPaths";

export interface ArchiveProgressProps {
  readonly workspaceId: string;
  readonly batchId: string;
  readonly fileName: string;
  /** Called once when the zip has finished, with how many documents it added. */
  readonly onFinished?: (added: number) => void;
}

export const ArchiveProgress: React.FC<ArchiveProgressProps> = ({ workspaceId, batchId, fileName, onFinished }) => {
  const { state } = useTenant();
  const query = useQuery({
    queryKey: ingestionKeys.batch(workspaceId, batchId),
    queryFn: () => getBatch(workspaceId, batchId),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "COMPLETED" || status === "COMPLETED_WITH_ERRORS" || status === "CANCELLED" ? false : 1500;
    },
    retry: 2,
  });
  const batch = query.data;
  const summary = batch ? summariseArchive(batch) : null;
  const finished = summary?.finished ?? false;
  const added = summary?.added ?? 0;

  useEffect(() => {
    if (finished) {
      onFinished?.(added);
    }
    // onFinished is intentionally not a dependency: it fires once, when the zip finishes.
  }, [finished]);

  const gstLink =
    state.status === "ready" ? gstPath(state.organization.organization_slug, state.workspace.slug) : null;
  const done = summary ? summary.added + summary.notAddedByPlan.length + summary.failed.length : 0;

  return (
    <li
      data-testid="archive-progress"
      className="space-y-2 rounded-lg border border-border/40 bg-muted/20 p-2.5 dark:bg-muted/5"
    >
      <div className="flex items-center gap-3">
        {finished ? (
          summary && (summary.failed.length > 0 || summary.notAddedByPlan.length > 0) ? (
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" aria-hidden />
          ) : (
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" aria-hidden />
          )
        ) : (
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-primary" aria-label="Unpacking" />
        )}
        <FileArchive className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{fileName}</p>
          <p className="text-[11px] text-muted-foreground" data-testid="archive-summary" role="status">
            {query.isError
              ? "The progress could not be read. Reload the page; the documents are still being added."
              : !batch
                ? "Uploaded. Unpacking…"
                : finished
                  ? summary?.sentence
                  : summary && summary.expected > 0
                    ? `Adding documents: ${done} of ${summary.expected}`
                    : "Unpacking…"}
          </p>
        </div>
      </div>

      {finished && summary && summary.skipped.length > 0 && (
        <ul className="space-y-1 pl-8 text-[11px] text-muted-foreground" data-testid="archive-skipped">
          {summary.skipped.map((file) => (
            <li key={`${file.name}:${file.code}`}>
              <span className="font-medium text-foreground">{file.name}</span>: {file.message}{" "}
              {file.code === "GSTR2B" && gstLink && (
                <Link to={gstLink} className="font-semibold text-primary hover:underline">
                  Open the GST credit page
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}

      {finished && summary && summary.notAddedByPlan.length > 0 && (
        <div className="space-y-1 pl-8" data-testid="archive-plan-limit">
          <p className="text-[11px] font-medium text-amber-700 dark:text-amber-400">
            Not added: your plan&apos;s monthly limit. {summary.notAddedByPlan.map((item) => item.filename).join(", ")}
          </p>
          <ViewPlansAction />
        </div>
      )}

      {finished && summary && summary.failed.length > 0 && (
        <ul className="space-y-1 pl-8 text-[11px] text-destructive" data-testid="archive-failed">
          {summary.failed.map((item) => (
            <li key={item.id}>
              <span className="font-medium">{item.filename}</span>: {item.error_detail || "could not be read"}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
};

export default ArchiveProgress;
