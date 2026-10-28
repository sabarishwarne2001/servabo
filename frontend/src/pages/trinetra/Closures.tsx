import { useQuery } from "@tanstack/react-query";
import { SURFACE } from "@/components/ui/primitives";
import { getClosureLedger } from "@/services/api/trinetra";
import { rupees } from "./format";

/** TDS now visible in your statement: evidence that a credit appears, by month. Never cash, never a refund, never added to GST or cash figures. */
export default function Closures({ workspaceId }: { workspaceId: string }) {
  const result = useQuery({
    queryKey: ["trinetra", workspaceId, "closures"],
    queryFn: () => getClosureLedger(workspaceId),
  });
  const data = result.data;
  const days = (value: unknown) =>
    typeof value === "number" ? `${value.toFixed(1)} days` : "Not yet measured";
  return (
    <section
      className={`${SURFACE} space-y-4 p-5`}
      aria-labelledby="closure-ledger"
      data-testid="trinetra-closures"
    >
      <div>
        <h2 id="closure-ledger" className="font-semibold">
          TDS now visible in your statement
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {data?.ledger_note ??
            "Evidence that a credit appears in your statement. It is not cash, a refund or money saved."}
        </p>
      </div>
      {result.isPending && (
        <p role="status" className="text-sm">
          Loading the closure ledger…
        </p>
      )}
      {result.isError && (
        <p role="alert" className="text-sm text-destructive">
          The closure ledger could not be loaded.
        </p>
      )}
      {data && (
        <>
          <dl className="grid gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">This month</dt>
              <dd className="text-lg font-semibold tabular-nums">
                {rupees(data.now_visible_this_month_micros ?? "0")}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">This year</dt>
              <dd className="text-lg font-semibold tabular-nums">
                {rupees(data.now_visible_this_year_micros ?? "0")}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">In all</dt>
              <dd className="text-lg font-semibold tabular-nums">
                {rupees(data.now_visible_total_micros)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Cases</dt>
              <dd className="text-lg font-semibold">{data.now_visible_cases}</dd>
            </div>
          </dl>
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Typical time to close a case (median)</dt>
              <dd className="font-medium">{days(data.measured_cycle_days_median)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Average</dt>
              <dd className="font-medium">{days(data.measured_cycle_days_mean)}</dd>
            </div>
          </dl>
          <p className="text-xs text-muted-foreground">{String(data.cycle_note ?? "")}</p>
          {data.months.length > 0 ? (
            <table className="w-full text-left text-sm">
              <caption className="sr-only">TDS now visible, by month</caption>
              <thead>
                <tr>
                  <th className="pr-3">Month</th>
                  <th className="pr-3">Cases</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {data.months.map((m) => (
                  <tr key={m.month}>
                    <td className="pr-3">{m.month}</td>
                    <td className="pr-3">{m.cases}</td>
                    <td className="tabular-nums">{rupees(m.amount_micros)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nothing yet. A case counts here once an accountant confirms its tax is in a later
              statement.
            </p>
          )}
        </>
      )}
    </section>
  );
}
