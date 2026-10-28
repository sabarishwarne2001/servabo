/**
 * Final session 2A (Phase 2): the server's safety jobs on the Background jobs console.
 *
 * The nightly sweeps (retention, erasure, reminders, ERP retries), the backups, the weekly restore drill and the uptime
 * heartbeat run from cron on the server, not inside the app, so a stopped cron used to be silent. Each run now reports
 * to the app; this panel lists every job with its last success and turns red when one is late (STALE) or has never
 * reported (NEVER_RAN). The same state is emailed to OPERATOR_ALERT_EMAILS once a day. RUNBOOK 9.6.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

import { HINT, SCROLL_X, SECTION_TITLE, SURFACE, TABLE_HEAD, TABLE_ROW } from "@/components/ui/primitives";
import { errorMessage } from "@/services/api/errors";
import { getSafetyJobs, platformJobKeys } from "@/services/api/platformJobs";
import type { SafetyJobStatus } from "@/types/platformJobs";
import { formatTimestamp } from "@/utils/displayTime";

const STATE_WORDS: Record<SafetyJobStatus["state"], string> = {
  OK: "On time",
  STALE: "Late",
  NEVER_RAN: "Never reported",
  WAITING: "Not yet due",
  UNWATCHED: "Switched off here",
};

const late = (state: SafetyJobStatus["state"]): boolean => state === "STALE" || state === "NEVER_RAN";

const deadline = (hours: number): string => (hours < 1 ? `${Math.round(hours * 60)} min` : hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`);

export const SafetyJobsPanel: React.FC = () => {
  const query = useQuery({ queryKey: platformJobKeys.safety(), queryFn: getSafetyJobs });
  const data = query.data;
  const lateJobs = (data?.jobs ?? []).filter((job) => late(job.state));

  return (
    <section
      className={`${SURFACE} ${SCROLL_X} p-4 ${data?.degraded ? "border-destructive" : ""}`}
      tabIndex={0}
      aria-label="Safety jobs on the server"
      data-testid="safety-jobs"
      data-degraded={data?.degraded ? "true" : "false"}
    >
      <h2 className={SECTION_TITLE}>Safety jobs on the server</h2>
      <p className={HINT}>
        The sweeps, backups, restore drill and uptime check that cron runs on the server. Each reports its runs here; a late one
        is emailed once a day.
      </p>
      {query.isLoading ? <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div> : null}
      {query.isError ? <p role="alert" className="mt-2 text-sm text-destructive">{errorMessage(query.error, "The safety jobs could not be loaded.")}</p> : null}
      {data ? (
        <>
          {data.degraded ? (
            <p role="alert" className="mt-2 flex items-start gap-2 text-sm font-medium text-destructive" data-testid="safety-jobs-alert">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {lateJobs.length === 1 ? "1 job is late" : `${lateJobs.length} jobs are late`}: {lateJobs.map((job) => job.label).join(", ")}.
              Check cron on the server and run the job once by hand (the command is in its row; RUNBOOK 9.6).
            </p>
          ) : (
            <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden />Every watched job has reported in time.
            </p>
          )}
          <table className="mt-2 w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD}>
                <th className="py-2 pr-3">Job</th><th className="pr-3">State</th><th className="pr-3">Last success</th>
                <th className="pr-3">Must succeed every</th><th className="pr-3">Last report</th><th className="pr-3">Run it by hand</th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.map((job) => (
                <tr key={job.name} className={TABLE_ROW} data-testid="safety-job-row" data-state={job.state}>
                  <td className="py-2 pr-3">
                    <span className="font-medium">{job.label}</span>
                    <span className="block font-mono text-xs text-muted-foreground">{job.name} · {job.schedule}</span>
                  </td>
                  <td className={`pr-3 ${late(job.state) ? "font-semibold text-destructive" : ""}`}>{STATE_WORDS[job.state]}</td>
                  <td className="whitespace-nowrap pr-3">{job.last_success_at ? formatTimestamp(job.last_success_at) : "—"}</td>
                  <td className="pr-3">{deadline(job.deadline_hours)}</td>
                  <td className="max-w-xs pr-3">
                    <span className="line-clamp-2 break-words text-xs" title={job.last_detail ?? ""}>
                      {job.last_outcome ? `${job.last_outcome.toLowerCase()}${job.last_detail ? `: ${job.last_detail}` : ""}` : "—"}
                    </span>
                  </td>
                  <td className="pr-3"><code className="break-all text-xs">{job.run}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </section>
  );
};
