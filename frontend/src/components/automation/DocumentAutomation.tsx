/**
 * Session J — "Why didn't my rule run?" on a document.
 *
 * For each rule in the workspace: did it run on this document, was it held back, or which condition failed and with
 * what value. Read-only, and it uses the same checks the rules run. An administrator can also run a rule that has the
 * "Run by hand" trigger on this document.
 */

import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, CircleSlash, Loader2, PauseCircle, Play, XCircle } from "lucide-react";
import { toast } from "sonner";

import { useActiveWorkspace } from "@/hooks/useActiveWorkspace";
import { canManageAutomation } from "@/permissions/workspacePermissions";
import { ApiError } from "@/services/api/errors";
import { automationApi } from "@/services/api/automation";
import { automationKeys } from "@/services/api/queryKeys";
import type { WorkspaceRole } from "@/types/tenancy";
import type { ExplainOutcome, RuleExplanation } from "@/types/automationVolume";

const OUTCOME_STYLE: Readonly<Record<ExplainOutcome, { readonly label: string; readonly tone: string; readonly icon: React.ReactNode }>> = {
  ran: { label: "Ran", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400", icon: <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> },
  held_back: { label: "Held back", tone: "bg-amber-500/15 text-amber-800 dark:text-amber-300", icon: <PauseCircle className="h-3.5 w-3.5" aria-hidden="true" /> },
  failed: { label: "Failed", tone: "bg-destructive/10 text-destructive", icon: <XCircle className="h-3.5 w-3.5" aria-hidden="true" /> },
  off: { label: "Switched off", tone: "bg-muted text-muted-foreground", icon: <CircleSlash className="h-3.5 w-3.5" aria-hidden="true" /> },
  not_triggered: { label: "Not triggered", tone: "bg-muted text-muted-foreground", icon: <CircleSlash className="h-3.5 w-3.5" aria-hidden="true" /> },
  conditions_not_met: { label: "Conditions not met", tone: "bg-amber-500/15 text-amber-800 dark:text-amber-300", icon: <XCircle className="h-3.5 w-3.5" aria-hidden="true" /> },
  no_actions: { label: "Nothing ran", tone: "bg-muted text-muted-foreground", icon: <CircleSlash className="h-3.5 w-3.5" aria-hidden="true" /> },
};

const MANUAL_TRIGGER_LABEL = "Run by hand on one document";

const RuleRow: React.FC<{ readonly rule: RuleExplanation }> = ({ rule }) => {
  const [open, setOpen] = useState(false);
  const style = OUTCOME_STYLE[rule.outcome];
  return (
    <li className="rounded-lg border border-border bg-card p-3" data-testid="explain-rule">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="min-w-0 truncate text-sm font-semibold">{rule.rule_name}</h4>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${style.tone}`}>
          {style.icon} {style.label}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        When: {rule.triggers.length ? rule.triggers.join(" or ") : "no trigger"}
      </p>
      <p className="mt-1.5 text-sm">{rule.verdict}</p>
      {rule.conditions.length > 0 && (
        <>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
            className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
          >
            <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
            {open ? "Hide the checks" : "Show the checks"}
          </button>
          {open && (
            <ul className="mt-2 space-y-1 text-xs" aria-label={`Checks for ${rule.rule_name}`}>
              {rule.conditions.map((condition, i) => (
                <li key={i} className={condition.matched ? "text-emerald-700 dark:text-emerald-400" : "text-foreground"}>
                  {condition.matched ? "✓" : "✗"} {condition.reason}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  );
};

export const DocumentAutomation: React.FC<{ readonly workItemId: string }> = ({ workItemId }) => {
  const workspace = useActiveWorkspace();
  const workspaceId = workspace?.workspaceId ?? "";
  const queryClient = useQueryClient();
  const canManage = canManageAutomation((workspace?.role ?? "VIEWER") as WorkspaceRole);
  const [manualRule, setManualRule] = useState("");

  const explain = useQuery({
    queryKey: automationKeys.explain(workspaceId, workItemId),
    queryFn: () => automationApi.explainDocument(workspaceId, workItemId),
    enabled: Boolean(workspaceId && workItemId),
    staleTime: 10_000,
  });

  const run = useMutation({
    mutationFn: (ruleId: string) => automationApi.runRuleByHand(workspaceId, ruleId, workItemId),
    onSuccess: async () => {
      toast.success("Queued. It appears in Run history within a few seconds.");
      setManualRule("");
      await queryClient.invalidateQueries({ queryKey: automationKeys.explain(workspaceId, workItemId) });
    },
    onError: (error: unknown) => toast.error(error instanceof ApiError ? error.message : "The rule could not be run."),
  });

  if (explain.isLoading) {
    return <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status"><Loader2 className="h-4 w-4 animate-spin" /> Checking each rule against this document…</p>;
  }
  if (explain.isError || !explain.data) {
    const forbidden = explain.error instanceof ApiError && explain.error.status === 403;
    return (
      <p className="text-sm text-muted-foreground" role={forbidden ? "status" : "alert"}>
        {forbidden ? "Only people who can edit documents here can see how the automation rules treat this one." : "The automation checks could not be loaded."}
      </p>
    );
  }

  const rules = explain.data.rules;
  const manual = rules.filter((r) => r.is_active && r.triggers.includes(MANUAL_TRIGGER_LABEL));

  return (
    <section className="space-y-4" aria-label="Automation on this document">
      <div>
        <h3 className="text-sm font-semibold">How your automation rules treat this document</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          For each rule: did it run, was it held back, or which condition was not met and with what value. This only reads; nothing here changes the document.
        </p>
      </div>
      {rules.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          This workspace has no automation rules yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {rules.map((rule) => <RuleRow key={rule.rule_id} rule={rule} />)}
        </ul>
      )}
      {canManage && manual.length > 0 && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-border bg-muted/20 p-3">
          <div className="min-w-[14rem] flex-1">
            <label htmlFor="manual-rule" className="mb-1 block text-xs font-semibold">Run a rule on this document</label>
            <select
              id="manual-rule"
              value={manualRule}
              onChange={(e) => setManualRule(e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="">Choose a rule…</option>
              {manual.map((rule) => <option key={rule.rule_id} value={rule.rule_id}>{rule.rule_name}</option>)}
            </select>
          </div>
          <button
            type="button"
            disabled={!manualRule || run.isPending}
            onClick={() => run.mutate(manualRule)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />} Run now
          </button>
        </div>
      )}
    </section>
  );
};

export default DocumentAutomation;
