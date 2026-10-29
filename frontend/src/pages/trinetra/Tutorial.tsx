import { useState } from "react";
import { CheckCircle2, Circle, X } from "lucide-react";
import { SURFACE } from "@/components/ui/primitives";
import { tutorialSteps, type TutorialStep } from "./model";
import type { CreditCase } from "@/services/api/trinetra";

const key = (workspaceId: string) => `servabo:trinetra:tutorial:${workspaceId}`;

const remembered = (workspaceId: string): boolean => {
  try {
    return window.localStorage.getItem(key(workspaceId)) === "hidden";
  } catch {
    return false;
  }
};

/** The first-run guide for a live organization: four steps that tick themselves, and can be put away. Never shown for the examples. */
export default function Tutorial({
  workspaceId,
  profiles,
  items,
  hasStatement,
  onOpen,
}: {
  workspaceId: string;
  profiles: number;
  items: readonly CreditCase[];
  hasStatement: boolean;
  onOpen: (tab: TutorialStep["tab"]) => void;
}) {
  const [hidden, setHidden] = useState(() => remembered(workspaceId));
  const steps = tutorialSteps({ profiles, items, hasStatement });
  const done = steps.filter((s) => s.done).length;
  if (done === steps.length) {
    return null;
  }
  const hide = (value: boolean) => {
    setHidden(value);
    try {
      if (value) {
        window.localStorage.setItem(key(workspaceId), "hidden");
      } else {
        window.localStorage.removeItem(key(workspaceId));
      }
    } catch {
      /* the guide simply comes back next time */
    }
  };
  if (hidden) {
    return (
      <p className="text-xs text-muted-foreground">
        <button
          type="button"
          className="font-medium text-primary hover:underline"
          onClick={() => hide(false)}
        >
          Show the TDS credit guide ({done} of {steps.length} done)
        </button>
      </p>
    );
  }
  return (
    <section
      className={`${SURFACE} p-5`}
      aria-labelledby="trinetra-guide"
      data-testid="trinetra-tutorial"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="trinetra-guide" className="text-[15px] font-semibold tracking-tight">
            Check that your customers' TDS reached your statement
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {done} of {steps.length} done. Each step ticks itself. A gap is an item to check, never
            a refund.
          </p>
        </div>
        <button
          type="button"
          aria-label="Put the guide away"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted"
          onClick={() => hide(true)}
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <ol className="mt-4 space-y-3" aria-label="First steps">
        {steps.map((step) => (
          <li key={step.key} className="flex items-start gap-3" data-done={String(step.done)}>
            {step.done ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
            ) : (
              <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span className="text-sm">
              <span className={step.done ? "text-muted-foreground line-through" : ""}>
                {step.title}
              </span>
              <span className="sr-only">{step.done ? " (done)" : " (to do)"}</span>
              <span className="block text-xs text-muted-foreground">{step.hint}</span>
              {!step.done && (
                <button
                  type="button"
                  className="mt-1 text-xs font-medium text-primary hover:underline"
                  onClick={() => onOpen(step.tab)}
                >
                  Open this
                </button>
              )}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
