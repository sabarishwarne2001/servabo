/**
 * Final session 2A (N-191) — Recoveries: the money Servabo found, followed until it is recovered.
 *
 * Three columns, Found → Being fixed → Verified, and the closed issues below. Each issue shows the engine's stored
 * figure, its due date from the law or the terms, its owner and the engines' own next actions (links: nothing here
 * moves money). Only evidence verifies an issue; a person may close one as "Not money" with a reason, which is never
 * counted. "Found" and "Recovered, verified" are separate figures and are never added together.
 *
 * A plan without Recoveries sees the counts and what was found, with the upgrade moment.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ExternalLink, HandCoins, Lock, RefreshCw, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { formatHelmMoney } from "@/components/helm/money";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingScreen } from "@/components/common/LoadingScreen";
import PageHeader from "@/components/ui/PageHeader";
import StatusPill, { type StatusTone } from "@/components/ui/StatusPill";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  FIELD_LABEL,
  HINT,
  INPUT,
  SECTION_TITLE,
  SELECT,
  SURFACE,
} from "@/components/ui/primitives";
import { CAPABILITY } from "@/constants/capabilities";
import { useActiveWorkspace } from "@/hooks/useActiveWorkspace";
import { useTenant } from "@/hooks/useTenant";
import { useUpgradePrompt } from "@/hooks/useUpgradePrompt";
import { helmPath, workspacePath } from "@/routes/tenantPaths";
import { errorMessage } from "@/services/api/errors";
import { recoveryKeys } from "@/services/api/queryKeys";
import {
  MIN_REASON,
  checkRecoveries,
  closeRecoveryNotMoney,
  getRecovery,
  listRecoveries,
  reopenRecovery,
  setRecoveryDueDate,
  setRecoveryOwner,
  type RecoveryAmount,
  type RecoveryIssue,
  type RecoveryState,
} from "@/services/api/recoveries";
import { listWorkspaceMembers } from "@/services/api/workspaces";
import { formatCalendarDate } from "@/utils/displayTime";

const WRITE_ROLES = new Set(["ADMIN", "CONTRIBUTOR"]);

const COLUMNS: readonly { readonly state: RecoveryState; readonly title: string; readonly hint: string }[] = [
  { state: "FOUND", title: "Found", hint: "Nobody owns these yet." },
  { state: "BEING_FIXED", title: "Being fixed", hint: "Someone owns it, or the supplier was asked." },
  { state: "VERIFIED", title: "Verified", hint: "Closed by evidence, never by a click." },
];

const STATE_LABEL: Record<RecoveryState, string> = {
  FOUND: "Found",
  BEING_FIXED: "Being fixed",
  VERIFIED: "Verified",
  NOT_MONEY: "Not money",
  CLOSED: "Closed",
};

const STATE_TONE: Record<RecoveryState, StatusTone> = {
  FOUND: "warn",
  BEING_FIXED: "info",
  VERIFIED: "ok",
  NOT_MONEY: "neutral",
  CLOSED: "neutral",
};

const OUTCOME_LABEL: Record<string, string> = {
  ITC_SECURED: "GST credit secured",
  OVERCHARGE_RECOVERED: "Overcharge recovered",
  DUPLICATE_BLOCKED: "Duplicate payment blocked",
  LATE_FEE_AVOIDED: "Late fee avoided",
  DISCOUNT_CAPTURED: "Early-payment discount captured",
};

const money = (amounts: readonly RecoveryAmount[]): string =>
  amounts.length === 0 ? "—" : amounts.map((a) => formatHelmMoney(a.amount_micros, a.currency)).join(" · ");

const exposure = (issue: RecoveryIssue): string =>
  issue.exposure_micros !== null && issue.exposure_micros !== undefined && issue.currency
    ? formatHelmMoney(issue.exposure_micros, issue.currency)
    : "Amount not read";

const Figure: React.FC<{ readonly label: string; readonly value: string; readonly note?: string | undefined; readonly testId: string }> = ({
  label,
  value,
  note,
  testId,
}) => (
  <div className={`${SURFACE} space-y-1 p-4`} data-testid={testId}>
    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
    <p className="text-lg font-semibold text-foreground">{value}</p>
    {note ? <p className={HINT}>{note}</p> : null}
  </div>
);

const IssueCard: React.FC<{ readonly issue: RecoveryIssue; readonly selected: boolean; readonly onOpen: () => void }> = ({
  issue,
  selected,
  onOpen,
}) => (
  <li>
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={selected}
      data-testid="recovery-card"
      className={`w-full rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted/60 ${
        selected ? "border-primary bg-muted/60" : "border-border bg-card"
      }`}
    >
      <span className="block text-xs text-muted-foreground">{issue.kind_label}</span>
      <span className="mt-0.5 block font-medium text-foreground">{issue.title}</span>
      <span className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        <span>{exposure(issue)}</span>
        {issue.due_date ? <span>Due {formatCalendarDate(issue.due_date)}</span> : null}
        <span>{issue.owner_email ? `Owner: ${issue.owner_email}` : "No owner"}</span>
      </span>
    </button>
  </li>
);

const IssueDetail: React.FC<{
  readonly workspaceId: string;
  readonly issueId: string;
  readonly orgSlug: string;
  readonly workspaceSlug: string;
  readonly canEdit: boolean;
  readonly onClose: () => void;
}> = ({ workspaceId, issueId, orgSlug, workspaceSlug, canEdit, onClose }) => {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: recoveryKeys.detail(workspaceId, issueId),
    queryFn: () => getRecovery(workspaceId, issueId),
  });
  const members = useQuery({
    queryKey: ["workspace-members", workspaceId],
    queryFn: () => listWorkspaceMembers(workspaceId),
    enabled: canEdit,
  });
  const [reason, setReason] = useState("");
  const [due, setDue] = useState("");

  const done = (issue: RecoveryIssue): void => {
    queryClient.setQueryData(recoveryKeys.detail(workspaceId, issueId), issue);
    void queryClient.invalidateQueries({ queryKey: recoveryKeys.list(workspaceId) });
  };
  const failed = (error: unknown): void => {
    toast.error(errorMessage(error, "That did not work."));
    void queryClient.invalidateQueries({ queryKey: recoveryKeys.all(workspaceId) });
  };
  const owner = useMutation({
    mutationFn: (userId: string | null) => setRecoveryOwner(workspaceId, issueId, userId, detail.data?.version ?? 0),
    onSuccess: done,
    onError: failed,
  });
  const dueDate = useMutation({
    mutationFn: (value: string | null) => setRecoveryDueDate(workspaceId, issueId, value, detail.data?.version ?? 0),
    onSuccess: (issue) => {
      setDue("");
      done(issue);
    },
    onError: failed,
  });
  const notMoney = useMutation({
    mutationFn: () => closeRecoveryNotMoney(workspaceId, issueId, reason.trim(), detail.data?.version ?? 0),
    onSuccess: (issue) => {
      setReason("");
      done(issue);
      toast.success("Closed. It is never counted as recovered.");
    },
    onError: failed,
  });
  const reopen = useMutation({
    mutationFn: () => reopenRecovery(workspaceId, issueId, detail.data?.version ?? 0),
    onSuccess: done,
    onError: failed,
  });

  if (detail.isLoading) {
    return <p className={`${SURFACE} p-4 text-sm text-muted-foreground`}>Loading the issue…</p>;
  }
  if (detail.isError || !detail.data) {
    return <p className={`${SURFACE} p-4 text-sm text-destructive`}>{errorMessage(detail.error, "This issue could not be loaded.")}</p>;
  }
  const issue = detail.data;
  const outcomes = issue.outcomes ?? [];
  const open = issue.state === "FOUND" || issue.state === "BEING_FIXED";
  const busy = owner.isPending || dueDate.isPending || notMoney.isPending || reopen.isPending;
  // Organization owners and admins reach every workspace as derived admins (no membership row): they can own an issue too.
  const people = [...new Map((members.data?.items ?? []).filter((m) => m.status === "ACTIVE")
    .map((m) => [m.user.id, m] as const)).values()];
  const word = issue.kind === "STATEMENT_DIFFERENCE" ? "Explained" : "Not money";
  const href = (scope: string, path: string): string =>
    scope === "helm" ? `${helmPath(orgSlug)}/${path}` : `${workspacePath(orgSlug, workspaceSlug)}/${path}`;

  return (
    <section className={`${SURFACE} space-y-4 p-5`} aria-labelledby="recovery-detail-title" data-testid="recovery-detail">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">{issue.kind_label}</p>
          <h2 id="recovery-detail-title" className={SECTION_TITLE}>
            {issue.title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill status={issue.state} tone={STATE_TONE[issue.state]} label={STATE_LABEL[issue.state]} />
          <button type="button" className={BUTTON_SECONDARY} onClick={onClose}>
            Close
          </button>
        </div>
      </div>

      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">At stake</dt>
          <dd className="font-medium text-foreground" data-testid="recovery-exposure">{exposure(issue)}</dd>
          {issue.found_exposure_micros !== null && issue.found_exposure_micros !== undefined && issue.currency
            && issue.found_exposure_micros !== issue.exposure_micros ? (
              <dd className={HINT}>When found: {formatHelmMoney(issue.found_exposure_micros, issue.currency)}</dd>
            ) : null}
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Due</dt>
          <dd className="font-medium text-foreground">{formatCalendarDate(issue.due_date, "No date")}</dd>
          {issue.due_basis ? <dd className={HINT}>{issue.due_basis}</dd> : null}
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Found</dt>
          <dd className="font-medium text-foreground">{formatCalendarDate(issue.first_found_at)}</dd>
          {issue.document ? <dd className={HINT}>{issue.document}</dd> : null}
        </div>
      </dl>

      {issue.close_reason ? (
        <p className="rounded-md bg-muted px-3 py-2 text-sm" data-testid="recovery-reason">
          {issue.close_reason}
        </p>
      ) : null}
      {outcomes.length > 0 ? (
        <div className="space-y-1" data-testid="recovery-outcomes">
          <p className={FIELD_LABEL}>Recovered, verified</p>
          <ul className="space-y-1 text-sm">
            {outcomes.map((o) => (
              <li key={`${o.category}-${o.occurred_on}`}>
                {OUTCOME_LABEL[o.category] ?? o.category}: <strong>{formatHelmMoney(o.amount_micros, o.currency)}</strong> on{" "}
                {formatCalendarDate(o.occurred_on)}
                {o.counted_by === "HELM" ? <span className={HINT}> (Helm proved it; counted once)</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : issue.state === "VERIFIED" ? (
        <p className={HINT}>Verified by evidence, with no money of its own to count (it is resolved, not recovered).</p>
      ) : null}

      <div className="space-y-1">
        <p className={FIELD_LABEL}>Next steps</p>
        <ul className="flex flex-wrap gap-2">
          {issue.next_actions.map((action) => (
            <li key={action.key}>
              <Link to={href(action.scope, action.path)} className={`${BUTTON_SECONDARY} inline-flex items-center gap-1.5`}>
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                {action.label}
              </Link>
            </li>
          ))}
        </ul>
        <p className={HINT}>These open the pages where the work is done. Recoveries never pays, approves or releases anything.</p>
      </div>

      {canEdit && open ? (
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-1">
            <span className={FIELD_LABEL}>Owner</span>
            <select
              className={SELECT}
              value={issue.owner_user_id ?? ""}
              disabled={busy}
              onChange={(e) => owner.mutate(e.target.value || null)}
              data-testid="recovery-owner"
            >
              <option value="">No owner</option>
              {people.map((m) => (
                <option key={m.user.id} value={m.user.id}>
                  {m.user.email}
                </option>
              ))}
            </select>
          </label>
          {!issue.due_date || issue.due_set_by_person ? (
            <div className="space-y-1">
              <label className={FIELD_LABEL} htmlFor="recovery-due">
                Due date (the law and the terms give none)
              </label>
              <div className="flex gap-2">
                <input id="recovery-due" type="date" className={INPUT} value={due} onChange={(e) => setDue(e.target.value)} />
                <button type="button" className={BUTTON_SECONDARY} disabled={busy || !due} onClick={() => dueDate.mutate(due)}>
                  Set
                </button>
              </div>
            </div>
          ) : null}
          <div className="space-y-1 md:col-span-2">
            <label className={FIELD_LABEL} htmlFor="recovery-reason-input">
              Close as {word.toLowerCase()}
            </label>
            <textarea
              id="recovery-reason-input"
              className={INPUT}
              rows={2}
              maxLength={2000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={issue.kind === "STATEMENT_DIFFERENCE" ? "How the difference is explained" : "Why this is not money to recover"}
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className={BUTTON_SECONDARY}
                disabled={busy || reason.trim().length < MIN_REASON}
                onClick={() => notMoney.mutate()}
                data-testid="recovery-not-money"
              >
                {word}
              </button>
              <span className={HINT}>At least {MIN_REASON} characters. It is recorded and never counted as recovered.</span>
            </div>
          </div>
        </div>
      ) : null}
      {canEdit && issue.state === "NOT_MONEY" ? (
        <button type="button" className={`${BUTTON_SECONDARY} inline-flex items-center gap-1.5`} disabled={busy} onClick={() => reopen.mutate()}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          Reopen
        </button>
      ) : null}
    </section>
  );
};

export const Recoveries: React.FC = () => {
  const workspace = useActiveWorkspace();
  const { state } = useTenant();
  const queryClient = useQueryClient();
  const workspaceId = workspace?.workspaceId ?? "";
  const organizationId = workspace?.organizationId ?? "";
  const ready = state.status === "ready";
  const orgSlug = ready ? state.organization.organization_slug : "";
  const workspaceSlug = ready ? state.workspace.slug : "";
  const orgRole = ready ? String(state.organizationRole) : "MEMBER";
  const upgrade = useUpgradePrompt(organizationId, orgSlug, orgRole);
  const canEdit = WRITE_ROLES.has(String(workspace?.role ?? "").toUpperCase());
  const [selected, setSelected] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  useEffect(() => {
    document.title = "Recoveries · Servabo";
  }, []);

  const view = useQuery({
    queryKey: recoveryKeys.list(workspaceId),
    queryFn: () => listRecoveries(workspaceId),
    enabled: Boolean(workspaceId),
    staleTime: 10_000,
  });
  const check = useMutation({
    mutationFn: () => checkRecoveries(workspaceId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: recoveryKeys.all(workspaceId) });
      const changed = result.found + result.verified + result.not_money + result.closed + result.reopened;
      toast.success(changed ? `Checked: ${result.found} found, ${result.verified} verified.` : "Checked: nothing changed.");
    },
    onError: (error) => toast.error(errorMessage(error, "The check could not be run.")),
  });

  const byState = useMemo(() => {
    const groups: Record<string, RecoveryIssue[]> = {};
    for (const issue of view.data?.items ?? []) {
      (groups[issue.state] ??= []).push(issue);
    }
    return groups;
  }, [view.data]);

  if (!workspace || view.isLoading) {
    return <LoadingScreen />;
  }
  if (view.isError || !view.data) {
    return (
      <div className="p-6">
        <ErrorState
          title="Recoveries could not be loaded"
          description={errorMessage(view.error, "The server did not answer. Check your connection and try again.")}
          onRetry={() => void view.refetch()}
        />
      </div>
    );
  }
  const { summary, included } = view.data;
  const closed = [...(byState.NOT_MONEY ?? []), ...(byState.CLOSED ?? [])];

  return (
    <div className="space-y-5 p-6" data-testid="recoveries-page">
      <PageHeader
        icon={HandCoins}
        eyebrow="Money"
        title="Recoveries"
        description="The money Servabo found in your documents, followed until evidence shows it was recovered."
        actions={
          included && canEdit ? (
            <button
              type="button"
              className={`${BUTTON_SECONDARY} inline-flex items-center gap-1.5`}
              onClick={() => check.mutate()}
              disabled={check.isPending}
              data-testid="recoveries-check"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${check.isPending ? "animate-spin" : ""}`} aria-hidden />
              Check now
            </button>
          ) : undefined
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Figure
          testId="recoveries-found"
          label="Found, still open"
          value={money(summary.found)}
          note={`${(summary.counts.FOUND ?? 0) + (summary.counts.BEING_FIXED ?? 0)} open issue(s)`}
        />
        <Figure
          testId="recoveries-needs-owner"
          label="Need an owner"
          value={`${summary.needs_owner.count}`}
          note={summary.needs_owner.amounts.length ? `${money(summary.needs_owner.amounts)} at stake` : undefined}
        />
        <Figure
          testId="recoveries-recovered"
          label="Recovered, verified"
          value={included ? money(summary.recovered_verified) : "—"}
          note={included ? `${summary.recovered_count} outcome(s), each with its evidence` : undefined}
        />
      </div>
      <p className={HINT}>Found and recovered are separate figures: they are never added together.</p>

      {!included ? (
        <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="recoveries-lock-title" data-testid="recoveries-preview-lock">
          <div className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-muted-foreground" aria-hidden />
            <h2 id="recoveries-lock-title" className={SECTION_TITLE}>
              Follow every issue until it is recovered
            </h2>
          </div>
          <p className="text-sm text-muted-foreground">
            The figures above are real. Business and Enterprise turn each one into an issue with an owner and a due date, close it only
            when evidence shows the money came back (a later GSTR-2B, a credit note, a payment on time) and count what was recovered,
            once.
          </p>
          <button type="button" className={BUTTON_PRIMARY} onClick={() => upgrade.prompt(CAPABILITY.recoveries, "Recoveries")}>
            See Business
          </button>
          {upgrade.dialog}
        </section>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-3" data-testid="recoveries-board">
            {COLUMNS.map((column) => {
              const items = byState[column.state] ?? [];
              return (
                <section key={column.state} aria-labelledby={`col-${column.state}`} data-testid={`recoveries-column-${column.state}`}>
                  <div className="mb-2 flex items-baseline justify-between">
                    <h2 id={`col-${column.state}`} className={SECTION_TITLE}>
                      {column.title} <span className="text-muted-foreground">({items.length})</span>
                    </h2>
                  </div>
                  <p className={`${HINT} mb-2`}>{column.hint}</p>
                  {items.length ? (
                    <ul className="space-y-2">
                      {items.map((issue) => (
                        <IssueCard key={issue.id} issue={issue} selected={selected === issue.id} onOpen={() => setSelected(issue.id)} />
                      ))}
                    </ul>
                  ) : (
                    <p className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">Nothing here.</p>
                  )}
                </section>
              );
            })}
          </div>

          {selected ? (
            <IssueDetail
              key={selected}
              workspaceId={workspaceId}
              issueId={selected}
              orgSlug={orgSlug}
              workspaceSlug={workspaceSlug}
              canEdit={canEdit}
              onClose={() => setSelected(null)}
            />
          ) : null}

          <section className="space-y-2" aria-labelledby="recoveries-closed-title">
            <button
              type="button"
              className={BUTTON_SECONDARY}
              aria-expanded={showClosed}
              onClick={() => setShowClosed((value) => !value)}
              id="recoveries-closed-title"
            >
              {showClosed ? "Hide" : "Show"} closed without money ({closed.length})
            </button>
            {showClosed ? (
              <ul className="space-y-2" data-testid="recoveries-closed">
                {closed.map((issue) => (
                  <IssueCard key={issue.id} issue={issue} selected={selected === issue.id} onOpen={() => setSelected(issue.id)} />
                ))}
              </ul>
            ) : null}
          </section>
        </>
      )}
    </div>
  );
};

export default Recoveries;
