/**
 * Session J — the builder's canvas: the rule drawn as a flow.
 *
 * When (the trigger) -> Only if (the conditions, a Yes / No fork) -> Then (the Yes steps) and Otherwise (the No steps).
 * Each box is a button: choosing it opens that part of the rule in the inspector. The canvas only draws and selects; every
 * edit happens in the inspector, so the keyboard and screen-reader path is the same forms as before.
 */

import React from "react";
import { AlertTriangle, Check, CirclePlus, Filter, GitBranch, Play, Zap } from "lucide-react";

import type { FlowCatalog } from "@/types/automationFlow";
import { ActionIcon } from "./ActionIcon";
import {
  actionLabel,
  findAction,
  conditionText,
  issuesFor,
  triggerLabel,
  type ActionDraft,
  type CardIssue,
  type CardKey,
  type FlowDraft,
} from "./flowModel";

export interface Selection {
  readonly card: CardKey;
  /** The step the person pointed at inside Then / Otherwise. */
  readonly index: number | null;
}

interface FlowCanvasProps {
  readonly draft: FlowDraft;
  readonly catalog: FlowCatalog;
  readonly selection: Selection;
  readonly onSelect: (selection: Selection) => void;
  readonly issues: readonly CardIssue[];
}

const TONES = {
  trigger: { bar: "bg-amber-500", icon: "text-amber-600 dark:text-amber-400", chip: "bg-amber-500/10" },
  conditions: { bar: "bg-violet-500", icon: "text-violet-600 dark:text-violet-300", chip: "bg-violet-500/10" },
  actions: { bar: "bg-emerald-500", icon: "text-emerald-600 dark:text-emerald-400", chip: "bg-emerald-500/10" },
  else: { bar: "bg-slate-400", icon: "text-slate-500 dark:text-slate-400", chip: "bg-slate-500/10" },
} as const;

const Line: React.FC<{ readonly tall?: boolean }> = ({ tall = false }) => (
  <span aria-hidden="true" className={`mx-auto block w-px bg-border ${tall ? "h-8" : "h-5"}`} />
);

const IssueBadge: React.FC<{ readonly count: number }> = ({ count }) =>
  count > 0 ? (
    <span
      className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-full bg-destructive/10 px-1.5 py-0.5 text-[10px] font-semibold text-destructive"
      title={`${count} thing${count === 1 ? "" : "s"} to fix`}
    >
      <AlertTriangle className="h-3 w-3" aria-hidden="true" /> {count}
    </span>
  ) : null;

const NodeBox: React.FC<{
  readonly kind: keyof typeof TONES;
  readonly title: string;
  readonly icon: React.ReactNode;
  readonly selected: boolean;
  readonly issueCount: number;
  readonly onClick: () => void;
  readonly children: React.ReactNode;
  readonly name: string;
}> = ({ kind, title, icon, selected, issueCount, onClick, children, name }) => (
  <button
    type="button"
    onClick={onClick}
    aria-pressed={selected}
    aria-label={name}
    data-testid={`flow-node-${kind}`}
    className={`group relative w-full overflow-hidden rounded-xl border bg-card text-left shadow-sm transition-shadow hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
      selected ? "border-primary ring-2 ring-primary/25" : issueCount ? "border-destructive/50" : "border-border"
    }`}
  >
    <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 ${TONES[kind].bar}`} />
    <span className="flex items-center gap-2 px-4 pt-3">
      <span className={`flex h-6 w-6 items-center justify-center rounded-md ${TONES[kind].chip} ${TONES[kind].icon}`} aria-hidden="true">
        {icon}
      </span>
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</span>
      <IssueBadge count={issueCount} />
    </span>
    <span className="block px-4 pb-3 pt-1.5 text-sm font-medium leading-snug">{children}</span>
  </button>
);

const StepRows: React.FC<{
  readonly card: "actions" | "else";
  readonly steps: readonly ActionDraft[];
  readonly catalog: FlowCatalog;
  readonly selection: Selection;
  readonly issues: readonly CardIssue[];
  readonly onSelect: (selection: Selection) => void;
}> = ({ card, steps, catalog, selection, issues, onSelect }) => (
  <ol className="space-y-1.5">
    {steps.map((step, index) => {
      const own = issues.filter((issue) => issue.index === index).length;
      const active = selection.card === card && selection.index === index;
      return (
        <li key={step.uid}>
          <button
            type="button"
            aria-label={`Step ${index + 1} of ${card === "actions" ? "Then" : "Otherwise"}: ${actionLabel(catalog, step.action_type)}`}
            aria-pressed={active}
            onClick={() => onSelect({ card, index })}
            className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-xs font-semibold transition-colors ${
              active ? "border-primary bg-primary/10" : own ? "border-destructive/50 bg-destructive/5" : "border-border bg-background hover:bg-muted/50"
            }`}
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-[10px] text-muted-foreground">
              {index + 1}
            </span>
            <span className="shrink-0 text-muted-foreground">
              <ActionIcon actionType={step.action_type} word={findAction(catalog, step.action_type)?.icon} />
            </span>
            <span className="min-w-0 flex-1 truncate">{actionLabel(catalog, step.action_type)}</span>
            {own > 0 && <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />}
          </button>
        </li>
      );
    })}
  </ol>
);

const Branch: React.FC<{
  readonly kind: "actions" | "else";
  readonly label: string;
  readonly title: string;
  readonly steps: readonly ActionDraft[];
  readonly catalog: FlowCatalog;
  readonly selection: Selection;
  readonly issues: readonly CardIssue[];
  readonly onSelect: (selection: Selection) => void;
  readonly empty: string;
  readonly addLabel: string;
}> = ({ kind, label, title, steps, catalog, selection, issues, onSelect, empty, addLabel }) => {
  const selected = selection.card === kind && selection.index === null;
  return (
    <div className="flex min-w-0 flex-col">
      <span
        className={`mx-auto mb-1 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
          kind === "actions" ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" : "bg-slate-500/15 text-slate-600 dark:text-slate-300"
        }`}
      >
        {kind === "actions" && <Check className="h-3 w-3" aria-hidden="true" />} {label}
      </span>
      <Line />
      <NodeBox
        kind={kind}
        title={title}
        icon={kind === "actions" ? <Play className="h-3.5 w-3.5" /> : <GitBranch className="h-3.5 w-3.5" />}
        selected={selected}
        issueCount={issues.length}
        onClick={() => onSelect({ card: kind, index: null })}
        name={`${title}: ${steps.length === 0 ? empty : `${steps.length} step${steps.length === 1 ? "" : "s"}`}`}
      >
        {steps.length === 0 ? <span className="text-muted-foreground">{empty}</span> : <span>{steps.length} step{steps.length === 1 ? "" : "s"} in order</span>}
      </NodeBox>
      {steps.length > 0 && (
        <div className="mt-2 px-1">
          <StepRows card={kind} steps={steps} catalog={catalog} selection={selection} issues={issues} onSelect={onSelect} />
        </div>
      )}
      <button
        type="button"
        onClick={() => onSelect({ card: kind, index: null })}
        className="mx-auto mt-2 inline-flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-[11px] font-semibold text-muted-foreground hover:border-primary hover:text-primary"
      >
        <CirclePlus className="h-3.5 w-3.5" aria-hidden="true" /> {addLabel}
      </button>
    </div>
  );
};

export const FlowCanvas: React.FC<FlowCanvasProps> = ({ draft, catalog, selection, onSelect, issues }) => {
  const conditions = draft.groups.flatMap((group) => group.conditions);
  const hasConditions = conditions.length > 0;
  const at = (card: CardKey) => selection.card === card && selection.index === null;
  const triggerNames = draft.triggers.map((key) => triggerLabel(catalog, key));
  const conditionLines = conditions.slice(0, 3).map((condition) => conditionText(catalog, condition));

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col px-4 py-6" data-testid="flow-canvas">
      <div className="mx-auto w-full max-w-sm">
        <NodeBox
          kind="trigger"
          title="When"
          icon={<Zap className="h-3.5 w-3.5" />}
          selected={at("trigger")}
          issueCount={issuesFor(issues, "trigger").length}
          onClick={() => onSelect({ card: "trigger", index: null })}
          name={`When: ${triggerNames.length ? triggerNames.join(" or ") : "choose what starts the rule"}`}
        >
          {triggerNames.length ? (
            <span>{triggerNames.join(" or ")}</span>
          ) : (
            <span className="text-muted-foreground">Choose what starts the rule</span>
          )}
        </NodeBox>
        <Line />
        <NodeBox
          kind="conditions"
          title="Only if"
          icon={<Filter className="h-3.5 w-3.5" />}
          selected={at("conditions")}
          issueCount={issuesFor(issues, "conditions").length}
          onClick={() => onSelect({ card: "conditions", index: null })}
          name={`Only if: ${hasConditions ? conditionLines.join("; ") : "no conditions, it runs every time"}`}
        >
          {hasConditions ? (
            <span className="block space-y-0.5">
              {conditionLines.map((line, i) => (
                <span key={i} className="block truncate">{line}</span>
              ))}
              {conditions.length > conditionLines.length && (
                <span className="block text-xs text-muted-foreground">and {conditions.length - conditionLines.length} more</span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground">No conditions: it runs every time</span>
          )}
        </NodeBox>
      </div>

      {hasConditions ? (
        <>
          <Line />
          <span aria-hidden="true" className="mx-auto block h-4 w-1/2 rounded-t-xl border-x border-t border-border" />
          <div className="grid grid-cols-1 gap-x-6 gap-y-6 sm:grid-cols-2">
            <Branch
              kind="actions" label="Yes" title="Then" steps={draft.actions} catalog={catalog} selection={selection}
              issues={issuesFor(issues, "actions")} onSelect={onSelect}
              empty="Add what the rule does" addLabel="Add a step"
            />
            <Branch
              kind="else" label="No" title="Otherwise" steps={draft.else_actions} catalog={catalog} selection={selection}
              issues={issuesFor(issues, "else")} onSelect={onSelect}
              empty="Nothing happens" addLabel="Add an otherwise step"
            />
          </div>
        </>
      ) : (
        <div className="mx-auto w-full max-w-sm">
          <Branch
            kind="actions" label="Every time" title="Then" steps={draft.actions} catalog={catalog} selection={selection}
            issues={issuesFor(issues, "actions")} onSelect={onSelect}
            empty="Add what the rule does" addLabel="Add a step"
          />
        </div>
      )}
    </div>
  );
};
