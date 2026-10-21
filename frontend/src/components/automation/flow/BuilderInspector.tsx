/**
 * Session J — the builder's inspector: the form for whatever box is selected on the canvas.
 *
 * Three tabs, as in the design the founder shared: Configuration (the form), Input / output (what flows into the step and
 * what it does, in words), Advanced (the rule's own settings: priority, what to do on a failure, the hourly limit, the
 * cooldown, a note for the version history).
 */

import React, { useEffect, useRef, useState } from "react";
import { History, Info } from "lucide-react";

import type { FlowCatalog } from "@/types/automationFlow";
import { ActionsCard } from "./ActionsCard";
import { ConditionsCard } from "./ConditionsCard";
import type { Selection } from "./FlowCanvas";
import {
  commonEventFields,
  findAction,
  findTrigger,
  issuesFor,
  type CardIssue,
  type FlowDraft,
} from "./flowModel";
import { IssueText, inputClass } from "./StepCard";
import { TriggerCard } from "./TriggerCard";

type Tab = "configuration" | "io" | "advanced";

const TAB_LABELS: Readonly<Record<Tab, string>> = {
  configuration: "Configuration",
  io: "Input / output",
  advanced: "Advanced",
};

const HEADINGS: Readonly<Record<string, string>> = {
  trigger: "When",
  conditions: "Only if",
  actions: "Then",
  else: "Otherwise",
  general: "Rule settings",
};

interface BuilderInspectorProps {
  readonly catalog: FlowCatalog;
  readonly draft: FlowDraft;
  readonly update: (patch: Partial<FlowDraft>) => void;
  readonly selection: Selection;
  readonly issues: readonly CardIssue[];
  readonly disabled: boolean;
  readonly isEdit: boolean;
  readonly onOpenHistory?: (() => void) | undefined;
  readonly defaultRunsPerHour: number;
  readonly onUpgrade?: ((capability: string, feature: string) => void) | undefined;
}

const Field: React.FC<{
  readonly id: string;
  readonly label: string;
  readonly help?: string;
  readonly issues?: readonly CardIssue[];
  readonly children: React.ReactNode;
}> = ({ id, label, help, issues = [], children }) => (
  <div>
    <label htmlFor={id} className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</label>
    {children}
    {help && <p className="mt-1 text-[11px] text-muted-foreground">{help}</p>}
    <IssueText issues={issues} />
  </div>
);

export const BuilderInspector: React.FC<BuilderInspectorProps> = ({
  catalog, draft, update, selection, issues, disabled, isEdit, onOpenHistory, defaultRunsPerHour, onUpgrade,
}) => {
  const [tab, setTab] = useState<Tab>("configuration");
  const panel = useRef<HTMLDivElement | null>(null);
  const aside = useRef<HTMLElement | null>(null);
  const first = useRef(true);
  const hasConditions = draft.groups.some((g) => g.conditions.length > 0);
  const general = issuesFor(issues, "general");

  // Choosing a box on the canvas shows its form; choosing a step scrolls to it.
  useEffect(() => {
    setTab("configuration");
  }, [selection.card]);
  // On a phone the inspector sits below the canvas: choosing a box brings its form into view.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1023px)").matches) {
      aside.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selection]);
  useEffect(() => {
    if (selection.index === null || (selection.card !== "actions" && selection.card !== "else")) {return;}
    document.getElementById(`${selection.card}-step-${selection.index}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selection]);

  const heading = HEADINGS[selection.card] ?? "Step";

  const configuration = ((): React.ReactNode => {
    switch (selection.card) {
      case "trigger":
        return (
          <TriggerCard
            bare
            catalog={catalog}
            selected={draft.triggers}
            onChange={(triggers) => update({ triggers })}
            issues={issuesFor(issues, "trigger")}
            disabled={disabled}
            onUpgrade={onUpgrade}
          />
        );
      case "conditions":
        return (
          <ConditionsCard
            bare
            catalog={catalog}
            triggers={draft.triggers}
            groups={draft.groups}
            groupsOperator={draft.groups_operator}
            onChange={(groups, groups_operator) => update({ groups, groups_operator })}
            issues={issuesFor(issues, "conditions")}
            disabled={disabled}
          />
        );
      case "else":
        if (!hasConditions) {
          return (
            <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
              An &ldquo;otherwise&rdquo; step runs when the conditions are not met. Add a condition first; with none, the rule
              runs every time.
            </p>
          );
        }
        return (
          <ActionsCard
            bare
            catalog={catalog}
            card="else"
            step={4}
            triggers={draft.triggers}
            actions={draft.else_actions}
            onChange={(else_actions) => update({ else_actions })}
            issues={issuesFor(issues, "else")}
            disabled={disabled}
            hasConditions={hasConditions}
            focusIndex={selection.index}
          />
        );
      case "actions":
      default:
        return (
          <ActionsCard
            bare
            catalog={catalog}
            card="actions"
            step={3}
            triggers={draft.triggers}
            actions={draft.actions}
            onChange={(actions) => update({ actions })}
            issues={issuesFor(issues, "actions")}
            disabled={disabled}
            hasConditions={hasConditions}
            focusIndex={selection.index}
          />
        );
    }
  })();

  const inputOutput = ((): React.ReactNode => {
    if (selection.card === "trigger") {
      const fields = commonEventFields(catalog, draft.triggers);
      return (
        <div className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            {draft.triggers.length === 0
              ? "Choose a trigger to see what it hands to the rule."
              : "When this happens, the rule is given these facts. You can test any of them under “Only if”, and use them in messages."}
          </p>
          {fields.length > 0 && (
            <ul className="divide-y divide-border/60 rounded-lg border border-border">
              {fields.map((f) => (
                <li key={f.key} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
                  <span className="font-medium">{f.label}</span>
                  <span className="truncate text-xs text-muted-foreground">e.g. {f.example}</span>
                </li>
              ))}
            </ul>
          )}
          {draft.triggers.some((key) => findTrigger(catalog, key)?.has_document) && (
            <p className="text-xs text-muted-foreground">
              It also carries the document, so its fields (invoice number, total, supplier…) can be tested too.
            </p>
          )}
        </div>
      );
    }
    if (selection.card === "conditions") {
      return (
        <p className="text-sm text-muted-foreground">
          The rule reads the facts from the trigger and the document, checks each condition in words you can see in
          &ldquo;Test &amp; preview&rdquo;, and goes down the <strong>Yes</strong> path when they are met, or the <strong>No</strong> path
          when they are not. With no conditions it always takes the Yes path.
        </p>
      );
    }
    const list = selection.card === "else" ? draft.else_actions : draft.actions;
    const chosen = selection.index !== null ? [list[selection.index]] : list;
    if (chosen.length === 0 || chosen.every((entry) => entry === undefined)) {
      return <p className="text-sm text-muted-foreground">Add a step to see what it reads and what it does.</p>;
    }
    return (
      <ul className="space-y-3">
        {chosen.map((entry, i) => {
          const action = entry ? findAction(catalog, entry.action_type) : undefined;
          if (!entry || !action) {return null;}
          return (
            <li key={entry.uid} className="rounded-lg border border-border p-3 text-sm">
              <p className="font-semibold">{action.label}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{action.description}</p>
              <p className="mt-2 flex items-start gap-1.5 text-xs">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                {action.idempotent
                  ? "Safe to run twice: doing it again changes nothing."
                  : "Doing it twice has a visible effect (a message goes out again), so a retry asks first."}
              </p>
              {action.template_fields.length > 0 && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Messages can use values from the trigger and the document with the &ldquo;Insert variable&rdquo; list.
                </p>
              )}
              <span className="sr-only">Step {selection.index !== null ? selection.index + 1 : i + 1}</span>
            </li>
          );
        })}
      </ul>
    );
  })();

  const advanced = (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field id="flow-priority" label="Priority" help="Lower numbers run first." issues={general.filter((i) => i.field === "priority")}>
          <input
            id="flow-priority"
            type="number"
            min={1}
            max={9999}
            disabled={disabled}
            value={Number.isFinite(draft.priority) ? draft.priority : ""}
            onChange={(e) => update({ priority: Number(e.target.value) })}
            className={inputClass(general.some((i) => i.field === "priority"))}
          />
        </Field>
        <Field id="flow-on-error" label="On failure">
          <select
            id="flow-on-error"
            disabled={disabled}
            value={draft.on_error}
            onChange={(e) => update({ on_error: e.target.value === "CONTINUE" ? "CONTINUE" : "HALT" })}
            className={inputClass(false)}
          >
            <option value="HALT">Stop the rule</option>
            <option value="CONTINUE">Keep going</option>
          </select>
        </Field>
      </div>

      <fieldset className="space-y-3 rounded-lg border border-border p-3">
        <legend className="px-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Safe at volume</legend>
        <Field
          id="flow-max-runs"
          label="At most this many runs an hour"
          help={
            defaultRunsPerHour > 0
              ? `Leave empty for the workspace default of ${defaultRunsPerHour}. Runs over the limit are listed in Run history as Skipped, never lost.`
              : "Leave empty for no limit. Runs over a limit are listed in Run history as Skipped, never lost."
          }
          issues={general.filter((i) => i.field === "max_runs_per_hour")}
        >
          <input
            id="flow-max-runs"
            type="number"
            min={1}
            max={100000}
            disabled={disabled}
            value={draft.max_runs_per_hour ?? ""}
            placeholder={defaultRunsPerHour > 0 ? String(defaultRunsPerHour) : "No limit"}
            onChange={(e) => update({ max_runs_per_hour: e.target.value === "" ? null : Number(e.target.value) })}
            className={inputClass(general.some((i) => i.field === "max_runs_per_hour"))}
          />
        </Field>
        <Field
          id="flow-cooldown"
          label="Run at most once per document every (hours)"
          help="Leave empty to let it run every time. Useful when a document changes often."
          issues={general.filter((i) => i.field === "cooldown_hours")}
        >
          <input
            id="flow-cooldown"
            type="number"
            min={1}
            max={8760}
            disabled={disabled}
            value={draft.cooldown_hours ?? ""}
            placeholder="Off"
            onChange={(e) => update({ cooldown_hours: e.target.value === "" ? null : Number(e.target.value) })}
            className={inputClass(general.some((i) => i.field === "cooldown_hours"))}
          />
        </Field>
      </fieldset>

      <Field id="flow-note" label="Note for the history (optional)" help="Kept with this version, so you can see why it changed.">
        <input
          id="flow-note"
          maxLength={200}
          disabled={disabled}
          value={draft.note}
          placeholder="e.g. Raised the bar after month end"
          onChange={(e) => update({ note: e.target.value })}
          className={inputClass(false)}
        />
      </Field>

      {isEdit && onOpenHistory && (
        <button
          type="button"
          onClick={onOpenHistory}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold hover:bg-muted"
        >
          <History className="h-3.5 w-3.5" aria-hidden="true" /> Version history
        </button>
      )}
    </div>
  );

  return (
    <aside ref={aside} className="flex min-h-0 flex-col border-border bg-card lg:border-l" aria-label="Step settings">
      <div className="border-b border-border px-4 pt-3">
        <h3 className="text-sm font-semibold">{heading}</h3>
        <div role="tablist" aria-label="Step settings" className="mt-2 flex gap-1">
          {(Object.keys(TAB_LABELS) as Tab[]).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`inspector-tab-${key}`}
              aria-selected={tab === key}
              aria-controls="inspector-panel"
              onClick={() => setTab(key)}
              className={`-mb-px rounded-t-md border-b-2 px-3 py-1.5 text-xs font-semibold ${
                tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {TAB_LABELS[key]}
            </button>
          ))}
        </div>
      </div>
      <div
        ref={panel}
        id="inspector-panel"
        role="tabpanel"
        aria-labelledby={`inspector-tab-${tab}`}
        className="min-h-0 flex-1 overflow-y-auto p-4"
      >
        {tab === "configuration" ? configuration : tab === "io" ? inputOutput : advanced}
      </div>
    </aside>
  );
};
