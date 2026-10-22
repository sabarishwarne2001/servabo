import React, { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import GstDrawer from "@/components/gst/GstDrawer";
import { day, gstinShort, rupees, statusTone } from "@/components/gst/gstFormat";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import StatusPill from "@/components/ui/StatusPill";
import { BUTTON_SECONDARY, HINT, INPUT, SCROLL_X, SURFACE, TABLE_HEAD, TABLE_ROW } from "@/components/ui/primitives";
import { errorMessage } from "@/services/api/errors";
import { getGstReminder, listGstLines, listGstSuppliers, sendGstReminder } from "@/services/api/gst";
import type { GstLineFilters } from "@/services/api/gst";
import { gstKeys } from "@/services/api/queryKeys";
import { GST_STATUS_LABEL, IMS_LABEL } from "@/types/gst";
import type { GstLine, GstStatus, GstSupplier, ImsAction } from "@/types/gst";

export interface TabProps {
  readonly workspaceId: string;
  readonly gstin: string | null;
  readonly period: string | null;
  readonly canDecide: boolean;
}

const PAGE = 25;

const Pager: React.FC<{ readonly offset: number; readonly total: number; readonly onChange: (offset: number) => void }> = ({
  offset,
  total,
  onChange,
}) =>
  total <= PAGE ? null : (
    <div className="flex items-center justify-between gap-3 px-4 py-2 text-xs text-muted-foreground">
      <span>
        {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
      </span>
      <span className="flex gap-2">
        <button type="button" className={BUTTON_SECONDARY} disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE))}>
          Previous
        </button>
        <button type="button" className={BUTTON_SECONDARY} disabled={offset + PAGE >= total} onClick={() => onChange(offset + PAGE)}>
          Next
        </button>
      </span>
    </div>
  );

// --------------------------------------------------------------------------------------------- suppliers

const ReminderDialog: React.FC<{
  readonly workspaceId: string;
  readonly gstin: string;
  readonly supplier: GstSupplier;
  readonly canSend: boolean;
  readonly onClose: () => void;
}> = ({ workspaceId, gstin, supplier, canSend, onClose }) => {
  const draft = useQuery({
    queryKey: [...gstKeys.all(workspaceId), "reminder", gstin, supplier.supplier_gstin],
    queryFn: () => getGstReminder(workspaceId, supplier.supplier_gstin ?? "", gstin),
    enabled: Boolean(supplier.supplier_gstin),
  });
  const send = useMutation({
    mutationFn: () => sendGstReminder(workspaceId, supplier.supplier_gstin ?? "", gstin),
    onSuccess: (result) => {
      if (result.sent) {toast.success(`Sent to ${result.to}.`);}
      else {toast.message(result.note ?? "Nothing was sent.");}
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error, "The reminder could not be sent.")),
  });
  const data = draft.data;
  const message = data
    ? `${data.subject ?? ""}\n\n${data.text ?? data.note ?? ""}`
    : draft.isError
      ? errorMessage(draft.error, "The draft could not be made.")
      : "Drafting…";
  return (
    <ConfirmDialog
      open
      tone="primary"
      title={`Reminder to ${supplier.supplier_name ?? supplier.supplier_gstin ?? "the supplier"}`}
      message={`${data?.to ? `To: ${data.to}\n\n` : ""}${message}${data && !data.to ? `\n\n${data.note ?? ""}` : ""}`}
      confirmText={canSend && data?.can_send ? "Send to the known contact" : "Close"}
      cancelText={canSend && data?.can_send ? "Not now" : "Close"}
      hideCancel={!(canSend && data?.can_send)}
      loading={send.isPending}
      onConfirm={() => (canSend && data?.can_send ? send.mutate() : onClose())}
      onCancel={onClose}
    />
  );
};

export const SuppliersTab: React.FC<TabProps> = ({ workspaceId, gstin, period, canDecide }) => {
  const [offset, setOffset] = useState(0);
  const [reminder, setReminder] = useState<GstSupplier | null>(null);
  const query = useQuery({
    queryKey: [...gstKeys.suppliers(workspaceId, gstin, period), offset],
    queryFn: () => listGstSuppliers(workspaceId, { gstin, period }, offset, PAGE),
  });
  const rows = query.data?.items ?? [];
  return (
    <div className={SURFACE} data-testid="gst-suppliers">
      <p className={`${HINT} px-4 pt-3`}>Who has not reported what, oldest first. A reminder is a draft; nothing is sent unless you ask.</p>
      {query.isError ? (
        <p role="alert" className="p-4 text-sm text-destructive">{errorMessage(query.error, "Suppliers could not be loaded.")}</p>
      ) : rows.length === 0 && !query.isLoading ? (
        <p className="p-4 text-sm text-muted-foreground">Every supplier has reported what is in your books.</p>
      ) : (
        <div className={SCROLL_X}>
          <table className="w-full min-w-[760px] text-sm">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className="px-4 py-2.5">Supplier</th>
                <th className="px-4 py-2.5 text-right">Waiting</th>
                <th className="px-4 py-2.5">Oldest waiting</th>
                <th className="px-4 py-2.5 text-right">Not in your books</th>
                <th className="px-4 py-2.5 text-right">Differences</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((supplier) => (
                <tr key={supplier.supplier_gstin ?? supplier.supplier_name ?? "?"} className={TABLE_ROW} data-testid="gst-supplier-row">
                  <td className="px-4 py-3">
                    <div className="font-medium text-foreground">{supplier.supplier_name ?? "Unnamed supplier"}</div>
                    <div className="text-xs text-muted-foreground">{gstinShort(supplier.supplier_gstin)}</div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {supplier.waiting_count > 0 ? (
                      <>
                        {rupees(supplier.waiting_micros)}
                        <div className="text-xs text-muted-foreground">{supplier.waiting_count} invoice{supplier.waiting_count === 1 ? "" : "s"}</div>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3">{day(supplier.oldest_waiting)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{supplier.not_in_books_count || "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{supplier.differences_count || "—"}</td>
                  <td className="px-4 py-3 text-right">
                    {supplier.waiting_count > 0 && supplier.supplier_gstin && gstin ? (
                      <button type="button" className={`${BUTTON_SECONDARY} inline-flex items-center gap-1.5`} onClick={() => setReminder(supplier)}>
                        <Mail className="h-3.5 w-3.5" aria-hidden />
                        Draft a reminder
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager offset={offset} total={query.data?.total ?? 0} onChange={setOffset} />
      {reminder && gstin ? (
        <ReminderDialog workspaceId={workspaceId} gstin={gstin} supplier={reminder} canSend={canDecide} onClose={() => setReminder(null)} />
      ) : null}
    </div>
  );
};

// --------------------------------------------------------------------------------------------- invoices

const CHIPS: readonly { readonly label: string; readonly statuses?: readonly GstStatus[] }[] = [
  { label: "All" },
  { label: "Matched", statuses: ["MATCHED"] },
  { label: "Differences", statuses: ["MATCHED_WITH_DIFFERENCES"] },
  { label: "Suggested", statuses: ["SUGGESTED"] },
  { label: "Waiting for supplier", statuses: ["WAITING_FOR_SUPPLIER"] },
  { label: "Not in your books", statuses: ["NOT_IN_BOOKS"] },
  { label: "Not eligible", statuses: ["NOT_ELIGIBLE"] },
  { label: "Reverse charge", statuses: ["REVERSE_CHARGE"] },
  { label: "Notes", statuses: ["NOTE"] },
];

const LineRow: React.FC<{ readonly line: GstLine; readonly onOpen: (line: GstLine) => void; readonly showIms?: boolean }> = ({
  line,
  onOpen,
  showIms = true,
}) => (
  <tr className={`${TABLE_ROW} cursor-pointer`} onClick={() => onOpen(line)} data-testid="gst-line-row" data-status={line.status}>
    <td className="px-4 py-3">
      <StatusPill status={line.status} tone={statusTone(line.status)} label={GST_STATUS_LABEL[line.status]} />
      {line.risk?.at_risk ? <div className="mt-1 text-[11px] text-destructive dark:text-red-300">180-day risk</div> : null}
    </td>
    <td className="px-4 py-3">
      <button
        type="button"
        className="text-left font-medium text-foreground underline-offset-2 hover:underline"
        onClick={(event) => {
          event.stopPropagation();
          onOpen(line);
        }}
      >
        {line.number ?? "No number"}
      </button>
      <div className="text-xs text-muted-foreground">{line.supplier_name ?? line.supplier_gstin ?? "Unknown supplier"}</div>
    </td>
    <td className="px-4 py-3">{day(line.date)}</td>
    <td className="px-4 py-3 text-right tabular-nums">{rupees(line.value_micros)}</td>
    <td className="px-4 py-3 text-right tabular-nums">{rupees(line.itc_micros)}</td>
    {showIms ? <td className="px-4 py-3 text-xs">{line.ims_action ? IMS_LABEL[line.ims_action] : "—"}</td> : null}
  </tr>
);

export const InvoicesTab: React.FC<TabProps> = ({ workspaceId, gstin, period, canDecide }) => {
  const [chip, setChip] = useState(0);
  const [offset, setOffset] = useState(0);
  // A result of the global search opens this list already narrowed: ?supplier=<name or GSTIN> or ?number=<invoice number>.
  const [params] = useSearchParams();
  const [supplier, setSupplier] = useState(() => params.get("supplier") ?? "");
  const [number, setNumber] = useState(() => params.get("number") ?? "");
  const [atRisk, setAtRisk] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const active = CHIPS[chip] ?? CHIPS[0]!;
  const filters = useMemo<GstLineFilters>(
    () => ({
      gstin,
      period,
      ...(active.statuses ? { status: active.statuses } : {}),
      ...(supplier ? { supplier } : {}),
      ...(number ? { q: number } : {}),
      atRisk,
      offset,
      limit: PAGE,
    }),
    [active.statuses, atRisk, gstin, number, offset, period, supplier],
  );
  const query = useQuery({ queryKey: gstKeys.lines(workspaceId, filters), queryFn: () => listGstLines(workspaceId, filters) });
  const rows = query.data?.items ?? [];
  return (
    <div className="space-y-3" data-testid="gst-invoices">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by status">
        {CHIPS.map((c, index) => (
          <button
            key={c.label}
            type="button"
            aria-pressed={index === chip}
            onClick={() => {
              setChip(index);
              setOffset(0);
            }}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
              index === chip ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted-foreground">
          Supplier
          <input className={`${INPUT} mt-1 block`} value={supplier} onChange={(e) => { setSupplier(e.target.value); setOffset(0); }} placeholder="Name or GSTIN" />
        </label>
        <label className="text-xs text-muted-foreground">
          Number
          <input className={`${INPUT} mt-1 block`} value={number} onChange={(e) => { setNumber(e.target.value); setOffset(0); }} placeholder="Invoice number" />
        </label>
        <label className="flex items-center gap-2 pb-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={atRisk} onChange={(e) => { setAtRisk(e.target.checked); setOffset(0); }} />
          Only invoices near the 180-day rule
        </label>
      </div>
      <div className={SURFACE}>
        {query.isError ? (
          <p role="alert" className="p-4 text-sm text-destructive">{errorMessage(query.error, "Invoices could not be loaded.")}</p>
        ) : rows.length === 0 && !query.isLoading ? (
          <p className="p-4 text-sm text-muted-foreground">Nothing matches these filters.</p>
        ) : (
          <div className={SCROLL_X}>
            <table className="w-full min-w-[820px] text-sm">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Invoice</th>
                  <th className="px-4 py-2.5">Date</th>
                  <th className="px-4 py-2.5 text-right">Invoice value</th>
                  <th className="px-4 py-2.5 text-right">Credit</th>
                  <th className="px-4 py-2.5">In the portal</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((line) => (
                  <LineRow key={line.id} line={line} onOpen={(l) => setOpen(l.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager offset={offset} total={query.data?.total ?? 0} onChange={setOffset} />
      </div>
      {open ? <GstDrawer workspaceId={workspaceId} lineId={open} canDecide={canDecide} onClose={() => setOpen(null)} /> : null}
    </div>
  );
};

// --------------------------------------------------------------------------------------------- IMS

const IMS_ORDER: readonly ImsAction[] = ["PENDING", "ACCEPT", "REJECT"];

const ImsChip: React.FC<{
  readonly workspaceId: string;
  readonly gstin: string | null;
  readonly period: string | null;
  readonly action: ImsAction;
  readonly active: boolean;
  readonly onPick: () => void;
}> = ({ workspaceId, gstin, period, action, active, onPick }) => {
  const filters = { gstin, period, ims: action, limit: 1 };
  const query = useQuery({ queryKey: gstKeys.lines(workspaceId, filters), queryFn: () => listGstLines(workspaceId, filters) });
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onPick}
      className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
        active ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
      }`}
    >
      {IMS_LABEL[action]} ({query.data?.total ?? 0})
    </button>
  );
};

export const ImsTab: React.FC<TabProps> = ({ workspaceId, gstin, period, canDecide }) => {
  const [action, setAction] = useState<ImsAction>("PENDING");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const filters = { gstin, period, ims: action, offset, limit: PAGE };
  const query = useQuery({ queryKey: gstKeys.lines(workspaceId, filters), queryFn: () => listGstLines(workspaceId, filters) });
  const rows = query.data?.items ?? [];
  return (
    <div className="space-y-3" data-testid="gst-ims-tab">
      <p className={HINT}>
        What to do on the GST portal&apos;s Invoice Management System, and why. These are recommendations, not tax advice: you act on the
        portal, and your chartered accountant has the last word.
      </p>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Recommended action">
        {IMS_ORDER.map((a) => (
          <ImsChip
            key={a}
            workspaceId={workspaceId}
            gstin={gstin}
            period={period}
            action={a}
            active={a === action}
            onPick={() => {
              setAction(a);
              setOffset(0);
            }}
          />
        ))}
      </div>
      <div className={SURFACE}>
        {rows.length === 0 && !query.isLoading ? (
          <p className="p-4 text-sm text-muted-foreground">Nothing to {IMS_LABEL[action].toLowerCase()} right now.</p>
        ) : (
          <div className={SCROLL_X}>
            <table className="w-full min-w-[820px] text-sm">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="px-4 py-2.5">Invoice</th>
                  <th className="px-4 py-2.5">Date</th>
                  <th className="px-4 py-2.5 text-right">Credit</th>
                  <th className="px-4 py-2.5">Why</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((line) => (
                  <tr key={line.id} className={`${TABLE_ROW} cursor-pointer`} onClick={() => setOpen(line.id)} data-testid="gst-ims-row">
                    <td className="px-4 py-3">
                      <div className="font-medium text-foreground">{line.number ?? "No number"}</div>
                      <div className="text-xs text-muted-foreground">{line.supplier_name ?? line.supplier_gstin ?? "Unknown supplier"}</div>
                    </td>
                    <td className="px-4 py-3">{day(line.date)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{rupees(line.itc_micros)}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{line.ims_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager offset={offset} total={query.data?.total ?? 0} onChange={setOffset} />
      </div>
      {open ? <GstDrawer workspaceId={workspaceId} lineId={open} canDecide={canDecide} onClose={() => setOpen(null)} /> : null}
    </div>
  );
};
