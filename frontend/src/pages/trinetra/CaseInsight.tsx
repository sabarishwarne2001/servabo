import { Check, CircleAlert, Minus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { SURFACE } from "@/components/ui/primitives";
import StatusPill from "@/components/ui/StatusPill";
import {
  getCreditDetail,
  type CaseDetail,
  type CreditCase,
  type MatchCheck,
} from "@/services/api/trinetra";
import { formatTimestamp } from "@/utils/displayTime";
import { rupees } from "./format";
import {
  CONFIDENCE_HINTS,
  CONFIDENCE_WORDS,
  confidenceOf,
  daysOpen,
  evidenceChecklist,
  statusTone,
  statusWords,
} from "./model";
import Waterfall from "./Waterfall";

const CHECK_WORDS = { true: "Agrees", false: "Differs", null: "Not printed on one side" } as const;

const checkIcon = (agrees: boolean | null) =>
  agrees === true ? (
    <Check className="h-4 w-4 text-emerald-600" aria-hidden />
  ) : agrees === false ? (
    <CircleAlert className="h-4 w-4 text-destructive" aria-hidden />
  ) : (
    <Minus className="h-4 w-4 text-muted-foreground" aria-hidden />
  );

const checkValue = (check: MatchCheck, side: "case_value" | "statement_value"): string => {
  const value = check[side];
  if (value === null) {
    return check.key === "deductor" ? "Compared as a key" : "Not printed";
  }
  return check.key === "amount" ? rupees(value) : value;
};

/** The case, explained: how the amounts add up, the evidence on the table, why each statement row is or is not its match, and what happened. */
export default function CaseInsight({
  workspaceId,
  item,
  timeline = true,
}: {
  workspaceId: string;
  item: CreditCase;
  timeline?: boolean;
}) {
  const detail = useQuery<CaseDetail>({
    queryKey: ["trinetra", workspaceId, "case", item.id],
    queryFn: () => getCreditDetail(workspaceId, item.id),
  });
  const data: CreditCase = detail.data ?? item;
  const confidence = confidenceOf(data.statement_reader);
  const checklist = evidenceChecklist(data);
  return (
    <div className="space-y-5" data-testid="trinetra-insight">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill
          status={data.status}
          tone={statusTone(data.status)}
          label={statusWords(data.status)}
        />
        <span className="text-xs text-muted-foreground">
          {daysOpen(data.age_days)} · revision {data.revision}
        </span>
      </div>
      <Waterfall item={data} />
      <section aria-labelledby={`checklist-${item.id}`} data-testid="trinetra-checklist">
        <h3 id={`checklist-${item.id}`} className="text-sm font-semibold">
          Evidence on the table
        </h3>
        <ul className="mt-2 space-y-1.5 text-sm">
          {checklist.map((entry) => (
            <li key={entry.key} className="flex items-start gap-2" data-state={entry.state}>
              <span className="mt-0.5" aria-hidden>
                {entry.state === "done" ? (
                  <Check className="h-4 w-4 text-emerald-600" />
                ) : entry.state === "stale" ? (
                  <CircleAlert className="h-4 w-4 text-amber-600" />
                ) : (
                  <Minus className="h-4 w-4 text-muted-foreground" />
                )}
              </span>
              <span>
                {entry.label}
                <span className="sr-only">
                  {entry.state === "done"
                    ? " (present)"
                    : entry.state === "stale"
                      ? " (changed since it was confirmed)"
                      : " (missing)"}
                </span>
                <span className="block text-xs text-muted-foreground">{entry.note}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby={`why-${item.id}`} data-testid="trinetra-why">
        <h3 id={`why-${item.id}`} className="text-sm font-semibold">
          Why this match
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Statement read as: {data.statement_reader?.label ?? CONFIDENCE_WORDS[confidence]}.{" "}
          {CONFIDENCE_HINTS[confidence]}
        </p>
        {detail.isPending && (
          <p role="status" className="mt-2 text-sm">
            Loading the comparison…
          </p>
        )}
        {detail.isError && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            The comparison could not be loaded.
          </p>
        )}
        {detail.data && !(detail.data.match_explanations ?? []).length && (
          <p className="mt-2 text-sm text-muted-foreground">
            No statement row has the same deductor, tax year and amount yet. An absent row does not
            establish missing tax credit.
          </p>
        )}
        {(detail.data?.match_explanations ?? []).map((row) => (
          <div
            key={`${row.snapshot_id}-${row.line_id}`}
            className={`${SURFACE} mt-2 p-3`}
            data-role={row.role}
          >
            <p className="text-sm font-medium">
              Statement row {Number(row.line_id) + 1} ·{" "}
              {row.role === "allocated"
                ? `allocated ${rupees(row.allocated_micros)}`
                : "a possible match to confirm"}
            </p>
            <p className="text-xs text-muted-foreground">
              Read by: {row.reader ?? "your typing"}
              {row.reader_verified ? "" : " (unverified reader)"} · rule {row.rule_version}
            </p>
            <ul className="mt-2 divide-y divide-border text-sm">
              {row.checks.map((check) => (
                <li
                  key={check.key}
                  className="grid grid-cols-[auto_1fr] gap-x-2 py-1.5"
                  data-check={check.key}
                  data-agrees={String(check.agrees)}
                >
                  {checkIcon(check.agrees)}
                  <span>
                    <span className="font-medium">{check.label}</span>:{" "}
                    {CHECK_WORDS[String(check.agrees) as "true" | "false" | "null"]}
                    <span className="block text-xs text-muted-foreground">
                      Your case: {checkValue(check, "case_value")} · Statement:{" "}
                      {checkValue(check, "statement_value")}
                    </span>
                    <span className="block text-xs text-muted-foreground">{check.note}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
      {timeline && (
        <section aria-labelledby={`timeline-${item.id}`} data-testid="trinetra-timeline">
          <h3 id={`timeline-${item.id}`} className="text-sm font-semibold">
            What happened
          </h3>
          <ol className="mt-2 space-y-2 border-l border-border pl-4 text-sm">
            {(detail.data?.events ?? []).map((event) => (
              <li key={event.revision}>
                <p className="font-medium">
                  Revision {event.revision} · {event.action.toLowerCase().replaceAll("_", " ")}
                </p>
                <p className="text-xs text-muted-foreground">{formatTimestamp(event.at)}</p>
                <p className="text-xs">{event.reason}</p>
              </li>
            ))}
            {detail.data && !detail.data.events.length && (
              <li className="text-muted-foreground">Nothing has been decided yet.</li>
            )}
          </ol>
        </section>
      )}
    </div>
  );
}
