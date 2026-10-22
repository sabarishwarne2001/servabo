/**
 * ARCH-37 / Session J — the rule in one sentence, and what still blocks saving. Each open item jumps to the box that
 * needs it on the canvas. (The save button lives in the builder's header.)
 */

import React from "react";
import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";

import type { CardIssue, CardKey } from "./flowModel";

const CARD_TITLES: Readonly<Record<CardKey, string>> = {
  general: "Details",
  trigger: "When",
  conditions: "Only if",
  actions: "Then",
  else: "Otherwise",
};

interface SummaryRailProps {
  readonly sentence: string;
  readonly issues: readonly CardIssue[];
  /** False until the first save attempt; open issues are then listed neutrally, not red. */
  readonly attempted: boolean;
  readonly dirty: boolean;
  readonly onJump: (card: CardKey, index: number | null) => void;
}

export const SummaryRail: React.FC<SummaryRailProps> = ({ sentence, issues, attempted, dirty, onJump }) => (
  <aside className="mx-auto w-full max-w-3xl px-4 pt-4" aria-label="Rule summary">
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">This rule</h3>
      <p className="mt-1.5 text-sm leading-relaxed" aria-live="polite">{sentence}</p>
      <div className="mt-3 border-t border-border/60 pt-3">
        {issues.length === 0 ? (
          <p className="flex items-center gap-2 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Ready to save
          </p>
        ) : (
          <>
            {attempted ? (
              <p className="flex items-center gap-2 text-xs font-semibold text-destructive">
                <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                {issues.length} {issues.length === 1 ? "thing" : "things"} to fix
              </p>
            ) : (
              <p className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                <CircleDashed className="h-4 w-4" aria-hidden="true" />
                {issues.length} {issues.length === 1 ? "thing" : "things"} left before it can be saved
              </p>
            )}
            <ul className="mt-2 space-y-1">
              {issues.slice(0, 6).map((issue, index) => (
                <li key={index}>
                  <button
                    type="button"
                    onClick={() => onJump(issue.card, issue.card === "actions" || issue.card === "else" ? issue.index : null)}
                    className="block w-full rounded px-1.5 py-1 text-left text-xs hover:bg-muted"
                  >
                    <span className="font-semibold">
                      {CARD_TITLES[issue.card]}
                      {issue.index !== null && (issue.card === "actions" || issue.card === "else") ? ` #${issue.index + 1}` : ""}:
                    </span>{" "}
                    {issue.message}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        {dirty && <p className="mt-2 text-[11px] text-muted-foreground">Unsaved changes</p>}
      </div>
    </div>
  </aside>
);
