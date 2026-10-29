import { SURFACE } from "@/components/ui/primitives";
import type { Cockpit } from "@/services/api/trinetra";
import { rupees } from "./format";
import { CONFIDENCE_HINTS, CONFIDENCE_WORDS, byConfidence } from "./model";
import Tip from "./Tip";

/** The four headline figures, each with where it comes from and as of when, and the gap split by how the statement came in. */
export default function Kpis({ data, sample }: { data: Cockpit; sample: boolean }) {
  const asOf = data.as_of ? data.as_of.slice(0, 10) : null;
  const source = sample
    ? "Synthetic cases made up to show how it works. No real tax data."
    : `The confirmed expectations of your open and closed cases, compared with the active statement snapshots${asOf ? `, as of ${asOf}` : ""}. Only rows a person allocated count as posted.`;
  const cards: readonly (readonly [string, string, string])[] = [
    [
      "Supported expected withholding",
      rupees(data.expected_micros),
      "What a person confirmed customers withheld, from an invoice, advice or accounting record.",
    ],
    [
      "Allocated uploaded postings",
      rupees(data.posted_micros),
      "Statement rows a person allocated to a case. A row nobody allocated is not counted.",
    ],
    [
      "Possible credit gap",
      rupees(data.gap_micros),
      "Expected less posted, where both are known. An item to check, never a refund or money.",
    ],
    [
      "Unresolved cases",
      String(data.unresolved),
      "Cases not yet posted, explained, withdrawn or left unresolved by a person.",
    ],
  ];
  const confidence = byConfidence(data.items);
  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="trinetra-kpis">
        {cards.map(([label, value, meaning]) => (
          <section key={label} className={`${SURFACE} border-t-2 border-t-primary/50 p-5`}>
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              {label}
              <Tip label={`About ${label}`}>{`${meaning} Source: ${source}`}</Tip>
            </p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              {sample
                ? "Synthetic reviewed evidence"
                : asOf
                  ? `As of ${asOf}`
                  : "No statement imported"}
            </p>
          </section>
        ))}
      </div>
      {confidence.length > 0 && (
        <section
          className={`${SURFACE} p-4`}
          aria-label="Possible gap by source confidence"
          data-testid="trinetra-confidence"
        >
          <h2 className="text-sm font-semibold">By how the statement came in</h2>
          <ul className="mt-2 grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-4">
            {confidence.map((row) => (
              <li
                key={row.confidence}
                className="rounded-md border border-border p-3"
                data-confidence={row.confidence}
              >
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  {CONFIDENCE_WORDS[row.confidence]}
                  <Tip label={`About ${CONFIDENCE_WORDS[row.confidence]}`}>
                    {CONFIDENCE_HINTS[row.confidence]}
                  </Tip>
                </span>
                <span className="mt-1 block font-semibold tabular-nums">
                  {rupees(row.gapMicros.toString())}
                </span>
                <span className="text-xs text-muted-foreground">
                  {row.cases} {row.cases === 1 ? "case" : "cases"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
