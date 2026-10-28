import { rupees } from "./format";
import { barPercent, waterfall } from "./model";
import type { CreditCase } from "@/services/api/trinetra";

/** Invoice gross, cash received, tax withheld, posted in the statement and what is left to check: bars for the eye, a table for everyone. */
export default function Waterfall({ item }: { item: CreditCase }) {
  const steps = waterfall(item);
  return (
    <section aria-labelledby={`waterfall-${item.id}`} data-testid="trinetra-waterfall">
      <h3 id={`waterfall-${item.id}`} className="text-sm font-semibold">
        How the amounts add up
      </h3>
      <table className="mt-2 w-full text-sm">
        <caption className="sr-only">
          Amount waterfall from the invoice to what is left to check
        </caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Step</th>
            <th scope="col">Amount</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((step) => (
            <tr key={step.key} className="align-top" data-step={step.key}>
              <th scope="row" className="w-1/2 py-1.5 pr-3 text-left font-normal">
                <span className="block">{step.label}</span>
                <span className="block text-xs text-muted-foreground">{step.note}</span>
              </th>
              <td className="py-1.5">
                <span className="block text-right font-medium tabular-nums">
                  {step.micros === null ? "Not known" : rupees(step.micros.toString())}
                </span>
                <span className="mt-1 block h-1.5 overflow-hidden rounded bg-muted" aria-hidden>
                  <span
                    className={`block h-full rounded ${step.key === "gap" ? "bg-destructive/70" : "bg-primary/70"}`}
                    style={{ width: `${barPercent(steps, step)}%` }}
                  />
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
