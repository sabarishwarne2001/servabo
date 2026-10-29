import { CircleAlert, Clock } from "lucide-react";
import type { CreditCase } from "@/services/api/trinetra";
import { freshness } from "./model";

/** How old the evidence is and how many confirmations lost theirs. Silent when everything is current. */
export default function FreshnessBanner({
  asOf,
  items,
}: {
  asOf: string | null;
  items: readonly CreditCase[];
}) {
  const state = freshness(asOf, items);
  if (state.level === "ok") {
    return null;
  }
  const Icon = state.level === "attention" ? CircleAlert : Clock;
  return (
    <p
      role={state.level === "attention" ? "alert" : "status"}
      data-testid="trinetra-freshness"
      data-level={state.level}
      className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${
        state.level === "attention"
          ? "border-amber-500/40 bg-amber-500/10"
          : "border-border bg-muted/40"
      }`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>{state.message}</span>
    </p>
  );
}
