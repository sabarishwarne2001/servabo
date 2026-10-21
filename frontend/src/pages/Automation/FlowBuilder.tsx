/**
 * ARCH-37 / Session J — the flow builder, a full-page editor.
 *
 * The rule is drawn as a flow on the canvas (When -> Only if -> Yes / No -> Then / Otherwise); choosing a box opens its
 * form in the inspector on the right (Configuration, Input / output, Advanced). The header holds the name, the Active
 * switch, "Test & preview" and the save button; the status bar at the bottom says how many steps are configured and
 * whether anything still blocks saving.
 *
 * Everything offered comes from the catalog endpoint. Saving sends the whole rule; the server validates it and returns
 * refusals located by `loc`, which `issuesFromError` places on the box that caused them. Local checks mirror the
 * server's so most mistakes show before a round trip.
 *
 * Keyboard: Ctrl/Cmd+S and Ctrl/Cmd+Enter save, Esc closes. Closing with unsaved changes asks first, in Servabo's own
 * dialog (never `window.confirm`), and so does leaving the page (the browser's own `beforeunload` prompt, the one native
 * exception).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Loader2, Save, X } from "lucide-react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { VersionHistoryDialog } from "@/components/automation/VersionHistoryDialog";
import { BuilderInspector } from "@/components/automation/flow/BuilderInspector";
import { FlowCanvas, type Selection } from "@/components/automation/flow/FlowCanvas";
import {
  draftFromRule,
  emptyDraft,
  issuesFromError,
  issuesFor,
  localIssues,
  payloadFromDraft,
  sameDraft,
  summarize,
  type CardIssue,
  type CardKey,
  type FlowDraft,
} from "@/components/automation/flow/flowModel";
import { PreviewPanel } from "@/components/automation/flow/PreviewPanel";
import { IssueText } from "@/components/automation/flow/StepCard";
import { SummaryRail } from "@/components/automation/flow/SummaryRail";
import { useActiveWorkspaceId } from "@/hooks/useActiveWorkspace";
import { automationApi } from "@/services/api/automation";
import { automationKeys } from "@/services/api/queryKeys";
import type { AutomationRule } from "@/types/automation";

interface FlowBuilderProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly onSaveSuccess: () => void;
  readonly ruleToEdit?: AutomationRule | null;
  readonly ruleToDuplicate?: AutomationRule | null;
  readonly existingRules?: readonly AutomationRule[];
  /** A recipe the person chose: the builder opens with it filled in. */
  readonly initialDraft?: FlowDraft | null;
}

export const FlowBuilder: React.FC<FlowBuilderProps> = ({
  isOpen,
  onClose,
  onSaveSuccess,
  ruleToEdit = null,
  ruleToDuplicate = null,
  existingRules = [],
  initialDraft = null,
}) => {
  const workspaceId = useActiveWorkspaceId();
  const queryClient = useQueryClient();
  const isEdit = ruleToEdit !== null;
  const source = ruleToEdit ?? ruleToDuplicate;

  const catalogQuery = useQuery({
    queryKey: automationKeys.catalog(workspaceId ?? ""),
    queryFn: () => automationApi.getAutomationCatalog(workspaceId ?? ""),
    enabled: isOpen && Boolean(workspaceId),
    staleTime: 60_000,
  });
  const catalog = catalogQuery.data;

  const [draft, setDraft] = useState<FlowDraft>(emptyDraft);
  const [initial, setInitial] = useState<FlowDraft>(emptyDraft);
  const [serverIssues, setServerIssues] = useState<readonly CardIssue[]>([]);
  const [attempted, setAttempted] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selection, setSelection] = useState<Selection>({ card: "trigger", index: null });
  const openedFor = useRef<string | null>(null);
  const nameInput = useRef<HTMLInputElement | null>(null);

  // Load the draft once per opening, after the catalog arrives (legacy action
  // names are resolved through the catalog's aliases).
  useEffect(() => {
    if (!isOpen) {
      openedFor.current = null;
      return;
    }
    if (!catalog) {return;}
    const key = `${source?.id ?? (initialDraft ? "recipe" : "new")}:${isEdit ? "edit" : "dup"}`;
    if (openedFor.current === key) {return;}
    openedFor.current = key;
    const next = source ? draftFromRule(source, catalog, isEdit ? "edit" : "duplicate") : (initialDraft ?? emptyDraft());
    setDraft(next);
    // A recipe is not saved yet: closing it asks first, like any other unsaved rule.
    setInitial(initialDraft && !source ? emptyDraft() : next);
    setServerIssues([]);
    setAttempted(false);
    setPreviewOpen(false);
    setSelection(isEdit ? { card: "actions", index: null } : { card: "trigger", index: null });
  }, [isOpen, catalog, source, isEdit, initialDraft]);

  const update = useCallback((patch: Partial<FlowDraft>): void => {
    setDraft((current) => ({ ...current, ...patch }));
    setServerIssues([]);
  }, []);

  const dirty = catalog ? !sameDraft(draft, initial, catalog) : false;

  const duplicateName = useMemo(() => {
    const name = draft.name.trim().toLowerCase();
    return Boolean(name) && existingRules.some((r) => r.name.trim().toLowerCase() === name && r.id !== ruleToEdit?.id);
  }, [draft.name, existingRules, ruleToEdit]);

  const issues = useMemo<CardIssue[]>(() => {
    const local = catalog ? localIssues(draft, catalog) : [];
    if (duplicateName) {
      local.push({ card: "general", index: null, subIndex: null, field: "name", message: "Another rule already has this name." });
    }
    return [...serverIssues, ...local.filter((l) => !serverIssues.some((s) => s.card === l.card && s.message === l.message))];
  }, [catalog, draft, duplicateName, serverIssues]);
  const shown = attempted ? issues : serverIssues;

  const jump = useCallback((card: CardKey, index: number | null): void => {
    if (card === "general") {
      nameInput.current?.focus();
      return;
    }
    setSelection({ card, index });
  }, []);

  const save = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !catalog) {throw new Error("The workspace is not ready yet.");}
      const payload = payloadFromDraft(draft, catalog);
      return ruleToEdit
        ? automationApi.updateAutomationRule(workspaceId, ruleToEdit.id, payload)
        : automationApi.createAutomationRule(workspaceId, payload);
    },
    onSuccess: async (rule) => {
      toast.success(isEdit ? `Saved “${rule.name}”.` : `Created “${rule.name}”.`);
      if (workspaceId) {await queryClient.invalidateQueries({ queryKey: automationKeys.rules(workspaceId) });}
      setInitial(draft);
      onSaveSuccess();
      onClose();
    },
    onError: (error: unknown) => {
      const located = issuesFromError(error);
      if (located && located.length) {
        setServerIssues(located);
        const first = located[0];
        if (first) {jump(first.card, first.index);}
        toast.error("The rule was not saved. See the highlighted steps.");
      } else {
        toast.error(error instanceof Error ? error.message : "The rule could not be saved.");
      }
    },
  });

  const submit = useCallback((): void => {
    setAttempted(true);
    if (save.isPending) {return;}
    if (issues.length > 0) {
      toast.error("Fix the highlighted steps before saving.");
      const first = issues[0];
      if (first) {jump(first.card, first.index);}
      return;
    }
    save.mutate();
  }, [issues, jump, save]);

  const requestClose = useCallback((): void => {
    if (save.isPending) {return;}
    if (dirty) {
      setDiscardOpen(true);
      return;
    }
    onClose();
  }, [dirty, onClose, save.isPending]);

  useEffect(() => {
    if (!isOpen) {return undefined;}
    const onKey = (event: KeyboardEvent): void => {
      // Behind the discard question or the preview nothing else may act: not Esc, not save.
      if (discardOpen || previewOpen || historyOpen) {return;}
      const mod = event.ctrlKey || event.metaKey;
      if (mod && (event.key === "s" || event.key === "S" || event.key === "Enter")) {
        event.preventDefault();
        submit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        requestClose();
      }
    };
    const onUnload = (event: BeforeUnloadEvent): void => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [isOpen, submit, requestClose, dirty, discardOpen, previewOpen, historyOpen]);

  if (!isOpen) {return null;}

  const busy = save.isPending;
  const general = issuesFor(shown, "general");
  const hasConditions = draft.groups.some((g) => g.conditions.length > 0);
  const stepCount = draft.actions.length + draft.else_actions.length;
  const previewable = Boolean(catalog) && draft.triggers.length > 0 && draft.actions.length > 0 && issues.every((i) => i.card === "general" && i.field === "name");

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-background"
      role="dialog"
      aria-modal="true"
      aria-labelledby="flow-builder-title"
    >
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border bg-card px-4 py-2.5">
        <button
          type="button"
          onClick={requestClose}
          disabled={busy}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Close the flow builder"
        >
          <X className="h-5 w-5" />
        </button>
        <h2 id="flow-builder-title" className="text-sm font-semibold uppercase tracking-wider">
          {isEdit ? "Edit automation" : ruleToDuplicate ? "Duplicate automation" : initialDraft ? "New automation from a recipe" : "New automation"}
        </h2>

        <div className="min-w-[12rem] flex-1 sm:max-w-md">
          <label htmlFor="flow-name" className="sr-only">Name</label>
          <input
            id="flow-name"
            ref={nameInput}
            autoFocus
            disabled={busy}
            maxLength={100}
            value={draft.name}
            placeholder="Name this rule, e.g. Hold invoices above ₹10 lakh"
            onChange={(e) => update({ name: e.target.value })}
            className={`w-full rounded-lg border bg-background px-3 py-1.5 text-sm font-medium focus:outline-none focus:ring-2 ${
              general.some((i) => i.field === "name")
                ? "border-destructive focus:ring-destructive/20"
                : "border-border focus:border-primary focus:ring-primary/20"
            }`}
          />
          <IssueText issues={general.filter((i) => i.field === "name" || i.field === null)} />
        </div>

        <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-semibold">
          <input
            type="checkbox"
            className="h-4 w-4 accent-primary"
            disabled={busy}
            checked={draft.is_active}
            onChange={(e) => update({ is_active: e.target.checked })}
          />
          Active
        </label>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            disabled={busy || !previewable}
            onClick={() => setPreviewOpen(true)}
            title={previewable ? "See what this rule would have done on the last 30 days" : "Choose a trigger and a step first"}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-semibold hover:bg-muted disabled:opacity-50"
          >
            <Eye className="h-4 w-4" aria-hidden="true" /> Test &amp; preview
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !catalog}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
            {isEdit ? "Save changes" : "Create rule"}
          </button>
        </div>
      </header>

      {!catalog ? (
        <div className="flex flex-1 items-center justify-center p-10 text-sm text-muted-foreground" role="status">
          {catalogQuery.isError ? (
            <span className="text-destructive">
              The automation catalog could not be loaded.{" "}
              <button type="button" className="underline" onClick={() => void catalogQuery.refetch()}>Retry</button>
            </span>
          ) : (
            <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Loading triggers and actions…</span>
          )}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_minmax(380px,440px)] lg:overflow-hidden">
          <div className="min-h-0 overflow-y-auto bg-[radial-gradient(hsl(var(--border))_1px,transparent_1px)] [background-size:18px_18px] lg:min-h-0">
            <SummaryRail
              sentence={summarize(draft, catalog)}
              // Every open issue, not only the ones shown on the boxes. Before the first save attempt the boxes stay
              // quiet, but the summary must not call an empty rule ready.
              issues={issues}
              attempted={attempted}
              dirty={dirty}
              onJump={jump}
            />
            <FlowCanvas draft={draft} catalog={catalog} selection={selection} onSelect={setSelection} issues={shown} />
          </div>
          <BuilderInspector
            catalog={catalog}
            draft={draft}
            update={update}
            selection={selection}
            issues={shown}
            disabled={busy}
            isEdit={isEdit}
            onOpenHistory={ruleToEdit ? () => setHistoryOpen(true) : undefined}
            defaultRunsPerHour={catalog.limits.default_runs_per_hour ?? 0}
          />
        </div>
      )}

      <footer
        className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border bg-card px-4 py-2 text-xs text-muted-foreground"
        role="status"
        aria-label="Rule status"
      >
        <span>
          {stepCount} step{stepCount === 1 ? "" : "s"} configured · {hasConditions ? 2 : 1} branch{hasConditions ? "es" : ""} ·{" "}
          {issues.length === 0 ? (
            <span className="font-semibold text-emerald-600 dark:text-emerald-400">No blocking issues</span>
          ) : (
            <span className={attempted ? "font-semibold text-destructive" : "font-semibold"}>
              {issues.length} thing{issues.length === 1 ? "" : "s"} to fix
            </span>
          )}
        </span>
        <span className="ml-auto hidden items-center gap-3 sm:flex">
          {dirty && !busy && <span>Unsaved changes</span>}
          <span><kbd className="rounded border border-border px-1">Ctrl/⌘ S</kbd> save</span>
          <span><kbd className="rounded border border-border px-1">Esc</kbd> close</span>
        </span>
      </footer>

      {workspaceId && (
        <PreviewPanel
          open={previewOpen}
          load={() => (catalog ? automationApi.previewDraft(workspaceId, payloadFromDraft(draft, catalog)) : Promise.reject(new Error("The catalog is not loaded.")))}
          onClose={() => setPreviewOpen(false)}
        />
      )}
      {workspaceId && (
        <VersionHistoryDialog
          open={historyOpen}
          workspaceId={workspaceId}
          rule={ruleToEdit}
          canRestore={false}
          onClose={() => setHistoryOpen(false)}
        />
      )}
      <ConfirmDialog
        open={discardOpen}
        title="Discard your changes?"
        message="The edits you made to this rule will be lost."
        confirmText="Discard changes"
        cancelText="Keep editing"
        tone="danger"
        initialFocus="cancel"
        onConfirm={() => { setDiscardOpen(false); onClose(); }}
        onCancel={() => setDiscardOpen(false)}
      />
    </div>
  );
};

export default FlowBuilder;
