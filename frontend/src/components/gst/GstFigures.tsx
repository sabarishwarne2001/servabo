import React from "react";
import { ExternalLink } from "lucide-react";

import { rupees } from "@/components/gst/gstFormat";
import { SURFACE } from "@/components/ui/primitives";
import type { GstFigure } from "@/types/gst";

const TONE: Readonly<Record<GstFigure["key"], string>> = {
  claimable_now: "text-emerald-700 dark:text-emerald-300",
  waiting: "text-amber-700 dark:text-amber-300",
  differences: "text-amber-700 dark:text-amber-300",
  at_risk_180: "text-destructive dark:text-red-300",
  not_in_books: "text-foreground",
  not_eligible: "text-muted-foreground",
};

const countWords = (figure: GstFigure): string => {
  const n = figure.count;
  switch (figure.key) {
    case "waiting":
      return `${n} invoice${n === 1 ? "" : "s"} · ${figure.suppliers ?? 0} supplier${figure.suppliers === 1 ? "" : "s"}`;
    case "at_risk_180":
      return `${n} unpaid invoice${n === 1 ? "" : "s"}`;
    case "not_in_books":
      return `${n} record${n === 1 ? "" : "s"} you have not uploaded`;
    case "not_eligible":
      return `${n} record${n === 1 ? "" : "s"}`;
    case "differences":
      return `${n} invoice${n === 1 ? "" : "s"} with a different amount`;
    default:
      return `${n} invoice${n === 1 ? "" : "s"}`;
  }
};

/** The six figures, each with its one-line meaning and a link to the law. Nothing here is invented. */
export const GstFigures: React.FC<{ readonly figures: readonly GstFigure[] }> = ({ figures }) => (
  <section aria-label="GST credit at a glance" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="gst-figures">
    {figures.map((figure) => {
      const count = figure.key === "not_in_books" ? figure.count : null;
      return (
        <article key={figure.key} className={`${SURFACE} flex flex-col gap-2 p-4`} data-testid={`gst-figure-${figure.key}`}>
          <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">{figure.title}</h3>
          <p className={`fp-kpi-figure text-2xl font-semibold tabular-nums ${TONE[figure.key]}`} data-testid={`gst-figure-${figure.key}-value`}>
            {count !== null ? figure.count : rupees(figure.amount_micros)}
          </p>
          <p className="text-xs font-medium text-foreground" data-testid={`gst-figure-${figure.key}-count`}>
            {count !== null ? `${rupees(figure.amount_micros)} of credit at stake` : countWords(figure)}
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">{figure.meaning}</p>
          <a
            href={figure.law.url}
            target="_blank"
            rel="noreferrer noopener"
            className="mt-auto inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline dark:text-[hsl(var(--primary-on-dark))]"
          >
            {figure.law.section}
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        </article>
      );
    })}
  </section>
);

export default GstFigures;
