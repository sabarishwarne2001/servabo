import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { toast } from "sonner";

import { day, rupees } from "@/components/gst/gstFormat";
import StatusPill from "@/components/ui/StatusPill";
import { statusTone } from "@/components/gst/gstFormat";
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY, HINT, SELECT } from "@/components/ui/primitives";
import { errorMessage } from "@/services/api/errors";
import { decideGstRecord, getGstLine, listGstLines, undoGstDecision } from "@/services/api/gst";
import { gstKeys } from "@/services/api/queryKeys";
import { GST_STATUS_LABEL, IMS_LABEL } from "@/types/gst";
import type { GstLineDetail } from "@/types/gst";

type Field = { readonly key: string; readonly label: string; readonly books: number | null | undefined; readonly gstr2b: number | null | undefined };

const fieldsOf = (detail: GstLineDetail): Field[] => {
  const b = detail.books;
  const g = detail.gstr2b;
  return [
    { key: "taxable", label: "Taxable value", books: b?.taxable_micros, gstr2b: g?.taxable_micros },
    { key: "igst", label: "IGST", books: b?.igst_micros, gstr2b: g?.igst_micros },
    { key: "cgst", label: "CGST", books: b?.cgst_micros, gstr2b: g?.cgst_micros },
    { key: "sgst", label: "SGST", books: b?.sgst_micros, gstr2b: g?.sgst_micros },
    { key: "cess", label: "Cess", books: b?.cess_micros, gstr2b: g?.cess_micros },
    { key: "value", label: "Invoice value", books: b?.total_micros, gstr2b: g?.value_micros },
  ];
};

/** One line, the books beside GSTR-2B with the differences highlighted, and the decisions a person can take. */
export const GstDrawer: React.FC<{
  readonly workspaceId: string;
  readonly lineId: string;
  readonly canDecide: boolean;
  readonly onClose: () => void;
}> = ({ workspaceId, lineId, canDecide, onClose }) => {
  const queryClient = useQueryClient();
  const closeRef = useRef<HTMLButtonElement>(null);
  const [linkTo, setLinkTo] = useState("");
  const detailQuery = useQuery({ queryKey: gstKeys.line(workspaceId, lineId), queryFn: () => getGstLine(workspaceId, lineId) });
  const detail = detailQuery.data;
  const waiting = useQuery({
    queryKey: gstKeys.lines(workspaceId, { picker: true }),
    queryFn: () => listGstLines(workspaceId, { status: ["WAITING_FOR_SUPPLIER"], limit: 100 }),
    enabled: canDecide && detail?.status === "NOT_IN_BOOKS" && !detail.decision,
  });

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {onClose();}
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);

  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: gstKeys.all(workspaceId) });
  };
  const decide = useMutation({
    mutationFn: (body: { decision: "CONFIRM" | "NOT_OURS" | "LINK"; work_item_id?: string }) =>
      decideGstRecord(workspaceId, detail?.record_id ?? "", body),
    onSuccess: async () => {
      toast.success("Decision saved.");
      await refresh();
    },
    onError: (error) => toast.error(errorMessage(error, "That decision could not be saved.")),
  });
  const undo = useMutation({
    mutationFn: () => undoGstDecision(workspaceId, detail?.record_id ?? ""),
    onSuccess: async () => {
      toast.success("Decision removed.");
      await refresh();
    },
    onError: (error) => toast.error(errorMessage(error, "That decision could not be removed.")),
  });

  const differing = new Set(detail?.differences.map((d) => d.field) ?? []);
  const body = (
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="gst-drawer-root">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="gst-drawer-title"
        className="relative flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-border bg-background p-5 shadow-xl"
        data-testid="gst-drawer"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="gst-drawer-title" className="truncate text-lg font-semibold text-foreground">
              {detail ? `${detail.number ?? "No number"} · ${detail.supplier_name ?? detail.supplier_gstin ?? "Unknown supplier"}` : "Loading…"}
            </h2>
            {detail ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <StatusPill status={detail.status} tone={statusTone(detail.status)} label={GST_STATUS_LABEL[detail.status]} />
                {detail.decision ? <span className={HINT}>Decided by a person: {detail.decision.replace("_", " ").toLowerCase()}</span> : null}
              </div>
            ) : null}
          </div>
          <button ref={closeRef} type="button" className={BUTTON_GHOST} onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        {detailQuery.isError ? (
          <p role="alert" className="mt-4 text-sm text-destructive">{errorMessage(detailQuery.error, "The line could not be loaded.")}</p>
        ) : null}

        {detail ? (
          <div className="mt-4 space-y-5">
            <p className="text-sm text-muted-foreground">{detail.status_text}</p>

            <table className="w-full text-sm" data-testid="gst-compare">
              <caption className="sr-only">Your books beside GSTR-2B</caption>
              <thead className="text-left text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-semibold">&nbsp;</th>
                  <th className="py-1.5 pr-3 text-right font-semibold">Your books</th>
                  <th className="py-1.5 text-right font-semibold">GSTR-2B</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-border/50">
                  <th scope="row" className="py-1.5 pr-3 text-left font-medium">Number</th>
                  <td className="py-1.5 pr-3 text-right">{detail.books?.number ?? "—"}</td>
                  <td className="py-1.5 text-right">{detail.gstr2b?.number ?? "—"}</td>
                </tr>
                <tr className="border-t border-border/50">
                  <th scope="row" className="py-1.5 pr-3 text-left font-medium">Date</th>
                  <td className="py-1.5 pr-3 text-right">{day(detail.books?.date)}</td>
                  <td className="py-1.5 text-right">{day(detail.gstr2b?.date)}</td>
                </tr>
                {fieldsOf(detail).map((field) => {
                  const off = differing.has(field.key);
                  return (
                    <tr key={field.key} className={`border-t border-border/50 ${off ? "bg-amber-500/10" : ""}`} data-different={off ? "true" : undefined}>
                      <th scope="row" className="py-1.5 pr-3 text-left font-medium">
                        {field.label}
                        {off ? <span className="ml-1.5 text-xs font-normal text-amber-700 dark:text-amber-300">differs</span> : null}
                      </th>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{rupees(field.books)}</td>
                      <td className="py-1.5 text-right tabular-nums">{rupees(field.gstr2b)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {detail.notes.length > 0 ? (
              <ul className="space-y-1 text-xs text-muted-foreground" aria-label="Notes">
                {detail.notes.map((note, index) => (
                  <li key={`${note.code}-${index}`}>
                    {note.label}
                    {note.books || note.gstr2b ? `: books ${note.books ?? "—"}, GSTR-2B ${note.gstr2b ?? "—"}` : ""}
                    {note.detail ? `: ${note.detail}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}

            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Credit</dt>
              <dd className="text-right tabular-nums">{rupees(detail.itc_micros)}</dd>
              {detail.period_first_seen ? (
                <>
                  <dt className="text-muted-foreground">First in GSTR-2B</dt>
                  <dd className="text-right">{detail.period_first_seen}{detail.reported_late ? " (reported late)" : ""}</dd>
                </>
              ) : null}
              {detail.gstr2b?.itc_available === "N" ? (
                <>
                  <dt className="text-muted-foreground">Reason code</dt>
                  <dd className="text-right">{detail.gstr2b.reason ?? "not given"}</dd>
                </>
              ) : null}
              {detail.risk ? (
                <>
                  <dt className="text-muted-foreground">180 days from the invoice date</dt>
                  <dd className="text-right" data-testid="gst-risk">
                    {day(detail.risk.reversal_date)}
                    {detail.risk.paid ? " · paid" : detail.risk.at_risk ? " · unpaid, at risk" : " · not recorded as paid"}
                  </dd>
                  <dt className="text-muted-foreground">Section 16(4) last date</dt>
                  <dd className="text-right">{day(detail.risk.deadline_16_4)}</dd>
                </>
              ) : null}
            </dl>

            {detail.ims_action ? (
              <section className="rounded-lg border border-border/70 bg-muted/30 p-3" aria-label="Recommendation for the GST portal" data-testid="gst-ims">
                <p className="text-sm font-medium text-foreground">In the portal: {IMS_LABEL[detail.ims_action]}</p>
                <p className={HINT}>{detail.ims_reason}</p>
                <p className={`${HINT} mt-1`}>A recommendation, not tax advice. You act on the GST portal; check with your chartered accountant.</p>
              </section>
            ) : null}

            {canDecide && detail.record_id ? (
              <section className="space-y-2" aria-label="Decisions">
                <div className="flex flex-wrap gap-2">
                  {detail.status === "SUGGESTED" ? (
                    <button type="button" className={BUTTON_PRIMARY} disabled={decide.isPending} onClick={() => decide.mutate({ decision: "CONFIRM" })}>
                      Confirm this match
                    </button>
                  ) : null}
                  {!detail.decision && detail.status !== "MATCHED" && detail.status !== "MATCHED_WITH_DIFFERENCES" ? (
                    <button type="button" className={BUTTON_SECONDARY} disabled={decide.isPending} onClick={() => decide.mutate({ decision: "NOT_OURS" })}>
                      Not ours
                    </button>
                  ) : null}
                  {detail.decision ? (
                    <button type="button" className={BUTTON_SECONDARY} disabled={undo.isPending} onClick={() => undo.mutate()}>
                      Undo my decision
                    </button>
                  ) : null}
                </div>
                {detail.status === "NOT_IN_BOOKS" && !detail.decision ? (
                  <div className="flex flex-wrap items-end gap-2">
                    <label className="text-xs text-muted-foreground">
                      Link to one of your invoices
                      <select className={`${SELECT} mt-1 block min-w-[16rem]`} value={linkTo} onChange={(event) => setLinkTo(event.target.value)} aria-label="Link by hand">
                        <option value="">Choose an invoice waiting for its supplier…</option>
                        {(waiting.data?.items ?? []).map((line) => (
                          <option key={line.id} value={line.work_item_id ?? ""}>
                            {line.number ?? "No number"} · {line.supplier_name ?? line.supplier_gstin ?? "?"} · {day(line.date)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button type="button" className={BUTTON_SECONDARY} disabled={!linkTo || decide.isPending} onClick={() => decide.mutate({ decision: "LINK", work_item_id: linkTo })}>
                      Link
                    </button>
                  </div>
                ) : null}
              </section>
            ) : null}
          </div>
        ) : null}
      </aside>
    </div>
  );
  return createPortal(body, document.body);
};

export default GstDrawer;
