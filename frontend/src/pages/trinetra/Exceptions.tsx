import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  INPUT,
  SELECT,
  SURFACE,
} from "@/components/ui/primitives";
import { errorMessage } from "@/services/api/errors";
import { listExceptions, pairReversal, type StatementException } from "@/services/api/trinetra";
import { rupees } from "./format";

function Pair({
  workspaceId,
  item,
  onDone,
}: {
  workspaceId: string;
  item: StatementException;
  onDone: () => void;
}) {
  const [positive, setPositive] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      pairReversal(workspaceId, {
        profile_id: item.profile_id,
        snapshot_id: item.snapshot_id,
        positive_line: Number(positive),
        negative_line: Number(item.line_id),
        reason,
      }),
    onSuccess: onDone,
  });
  return (
    <form
      className="mt-3 space-y-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="block">
        The posting this reverses
        <select
          required
          className={`${SELECT} mt-1`}
          value={positive}
          onChange={(e) => setPositive(e.target.value)}
        >
          <option value="">Choose a statement row</option>
          {item.candidates.map((c) => (
            <option key={c.line_id} value={c.line_id}>
              Row {Number(c.line_id) + 1} · {rupees(c.amount_micros)} ·{" "}
              {c.reference ?? "no reference"} · {c.on ?? "no date"}
            </option>
          ))}
        </select>
      </label>
      {!item.candidates.length && (
        <p className="text-muted-foreground">
          No other row of this customer is in the statement, so there is nothing to pair it with.
        </p>
      )}
      <label className="block">
        Why you are sure (what you checked)
        <textarea
          required
          minLength={10}
          maxLength={1000}
          className={`${INPUT} mt-1`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <button className={BUTTON_PRIMARY} disabled={save.isPending || !positive}>
        Pair these rows
      </button>
      {save.isError && (
        <p role="alert" className="text-destructive">
          {errorMessage(save.error, "These rows could not be paired.")}
        </p>
      )}
    </form>
  );
}

/** Reversals and corrections in your statements. Each stays an exception, never netted on its own, until a person pairs it with the row it reverses. */
export default function Exceptions({
  workspaceId,
  canDecide,
}: {
  workspaceId: string;
  canDecide: boolean;
}) {
  const cache = useQueryClient();
  const result = useQuery({
    queryKey: ["trinetra", workspaceId, "exceptions"],
    queryFn: () => listExceptions(workspaceId),
  });
  const [open, setOpen] = useState<string | null>(null);
  const items = result.data?.items ?? [];
  return (
    <section
      className={`${SURFACE} overflow-hidden`}
      aria-labelledby="exception-list"
      data-testid="trinetra-exceptions"
    >
      <div className="border-b border-border p-5">
        <h2 id="exception-list" className="font-semibold">
          Reversals waiting for a person
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {result.data?.note ??
            "A reversal or correction stays an exception until a person pairs it with the row it reverses."}
        </p>
      </div>
      {result.isPending && (
        <p role="status" className="p-5 text-sm">
          Loading exceptions…
        </p>
      )}
      {result.isError && (
        <p role="alert" className="p-5 text-sm">
          The exceptions could not be loaded.{" "}
          <button className={BUTTON_SECONDARY} onClick={() => void result.refetch()}>
            Try again
          </button>
        </p>
      )}
      {result.data && !items.length && (
        <p className="p-6 text-center text-sm text-muted-foreground">
          No reversal is waiting. Every reversal in your statements is paired.
        </p>
      )}
      <ul className="divide-y divide-border">
        {items.map((item) => {
          const key = `${item.snapshot_id}:${item.line_id}`;
          return (
            <li key={key} className="p-4" data-testid="trinetra-exception">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>
                  Statement row {Number(item.line_id) + 1} · {item.section ?? "no section printed"}{" "}
                  · {item.on ?? "no date printed"} · {item.reference ?? "no reference"}
                </span>
                <span className="flex items-center gap-3">
                  <span className="font-semibold tabular-nums">{rupees(item.amount_micros)}</span>
                  {canDecide && (
                    <button
                      className={BUTTON_SECONDARY}
                      onClick={() => setOpen(open === key ? null : key)}
                      aria-expanded={open === key}
                    >
                      Pair with a posting
                    </button>
                  )}
                </span>
              </div>
              {open === key && (
                <Pair
                  workspaceId={workspaceId}
                  item={item}
                  onDone={() => {
                    setOpen(null);
                    void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
                  }}
                />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
