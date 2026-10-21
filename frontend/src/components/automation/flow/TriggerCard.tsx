/**
 * ARCH-37 / Session J — step 1: when. A searchable picker over the catalog's triggers, grouped by what they are about.
 * Each entry is a name and one short line; the long description opens on demand. An entry the plan does not include is
 * shown, locked, with the reason.
 */

import React, { useMemo, useState } from "react";
import { ChevronDown, Lock, Search, Zap } from "lucide-react";

import type { FlowCatalog, FlowTrigger } from "@/types/automationFlow";
import type { CardIssue } from "./flowModel";
import { IssueText, StepCard, inputClass } from "./StepCard";

interface TriggerCardProps {
  readonly catalog: FlowCatalog;
  readonly selected: readonly string[];
  readonly onChange: (next: readonly string[]) => void;
  readonly issues: readonly CardIssue[];
  readonly disabled: boolean;
  /** The builder shows the card inside its inspector, which already has a heading. */
  readonly bare?: boolean;
  /** A locked trigger offers "Upgrade", which opens the upgrade dialog naming what it needs. */
  readonly onUpgrade?: ((capability: string, feature: string) => void) | undefined;
}

export const matchesTrigger = (trigger: FlowTrigger, query: string): boolean => {
  const needle = query.trim().toLowerCase();
  if (!needle) {return true;}
  return [trigger.label, trigger.category, trigger.summary ?? "", trigger.description]
    .some((text) => text.toLowerCase().includes(needle));
};

export const TriggerCard: React.FC<TriggerCardProps> = ({ catalog, selected, onChange, issues, disabled, bare = false, onUpgrade }) => {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());

  const byCategory = useMemo(() => {
    const groups = new Map<string, FlowTrigger[]>();
    for (const trigger of catalog.triggers) {
      if (!matchesTrigger(trigger, query) && !selected.includes(trigger.key)) {continue;}
      const list = groups.get(trigger.category) ?? [];
      list.push(trigger);
      groups.set(trigger.category, list);
    }
    return Array.from(groups.entries());
  }, [catalog.triggers, query, selected]);

  const limit = catalog.limits.triggers;
  const toggle = (key: string): void => {
    if (selected.includes(key)) {
      onChange(selected.filter((k) => k !== key));
    } else if (selected.length < limit) {
      onChange([...selected, key]);
    }
  };
  const toggleOpen = (key: string): void =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) {next.delete(key);} else {next.add(key);}
      return next;
    });

  const body = (
    <div className="space-y-4">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <input
          type="search"
          aria-label="Search triggers"
          value={query}
          disabled={disabled}
          placeholder={`Search ${catalog.triggers.length} triggers: invoice, GST, hold, schedule…`}
          onChange={(e) => setQuery(e.target.value)}
          className={`${inputClass(false)} pl-9`}
        />
      </div>
      {byCategory.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground" role="status">
          No trigger matches &ldquo;{query}&rdquo;. Try a shorter word.
        </p>
      )}
      {byCategory.map(([category, triggers]) => (
        <fieldset key={category} className="space-y-2">
          <legend className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{category}</legend>
          <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
            {triggers.map((trigger) => {
              const checked = selected.includes(trigger.key);
              const index = selected.indexOf(trigger.key);
              const locked = !trigger.available;
              const full = !checked && selected.length >= limit;
              const own = issues.filter((issue) => issue.index !== null && issue.index === index);
              const expanded = open.has(trigger.key);
              const line = trigger.summary || trigger.description;
              return (
                <div
                  key={trigger.key}
                  className={`rounded-lg border transition-colors ${
                    checked ? "border-primary bg-primary/5" : "border-border hover:bg-muted/40"
                  }`}
                >
                  {/* The dimming is on the label alone: its text belongs to a disabled checkbox, which needs no contrast. The
                      "Upgrade" and "Details" buttons below are live controls and keep their full contrast. */}
                  <label className={`flex items-start gap-3 p-3 ${locked || full || disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 accent-primary"
                      checked={checked}
                      disabled={disabled || (!checked && (locked || full))}
                      onChange={() => toggle(trigger.key)}
                      aria-describedby={`trigger-desc-${trigger.key}`}
                    />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                        {trigger.label}
                        {locked && (
                          <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
                            <Lock className="h-3 w-3" aria-hidden="true" /> Not in your plan
                          </span>
                        )}
                        {trigger.runs_during_review && (
                          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400">
                            Runs during review
                          </span>
                        )}
                      </span>
                      <span id={`trigger-desc-${trigger.key}`} className="mt-0.5 block text-xs text-muted-foreground">
                        {line}
                      </span>
                      <IssueText issues={own} />
                    </span>
                  </label>
                  {locked && onUpgrade && (trigger.capability || trigger.addon) && (
                    <div className="border-t border-border/60 px-3 py-1.5">
                      <button
                        type="button"
                        onClick={() => onUpgrade(trigger.capability ?? trigger.addon ?? "", trigger.label)}
                        aria-label={`Upgrade to use the trigger: ${trigger.label}`}
                        className="text-[11px] font-semibold text-primary hover:underline"
                      >
                        Upgrade{trigger.unavailable_reason ? `: ${trigger.unavailable_reason}` : ""}
                      </button>
                    </div>
                  )}
                  {trigger.description && trigger.description !== line && (
                    <div className="border-t border-border/60 px-3 py-1.5">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => toggleOpen(trigger.key)}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-muted-foreground hover:text-foreground"
                      >
                        <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
                        {expanded ? "Hide details" : "Details"}
                        <span className="sr-only"> for {trigger.label}</span>
                      </button>
                      {expanded && <p className="mt-1 text-xs text-muted-foreground">{trigger.description}</p>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );

  return (
    <StepCard
      id="flow-step-trigger"
      step={1}
      title="When"
      subtitle={`Choose what starts this rule. Pick up to ${limit}; the rule runs when any of them happens.`}
      icon={<Zap className="h-4 w-4" />}
      issues={issues}
      bare={bare}
    >
      {body}
    </StepCard>
  );
};
