/**
 * GST credit across every workspace (Enterprise, `capability.gst_credit_all_workspaces`).
 *
 * One reconciliation per GSTIN: the GSTR-2B returns imported in any workspace, matched with the purchase invoices
 * of every workspace that holds that GSTIN's purchases. Read-only: importing, deciding and exporting stay in each
 * workspace's own GST credit page. For organization owners, admins and billing; the lists show the workspaces the
 * person can read (billing: the ones it has grants on), the figures are the organization's.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock, ReceiptIndianRupee } from "lucide-react";

import GstFigures from "@/components/gst/GstFigures";
import { day, gstinShort, periodLabel, rupees, statusTone } from "@/components/gst/gstFormat";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingScreen } from "@/components/common/LoadingScreen";
import PageHeader from "@/components/ui/PageHeader";
import StatusPill from "@/components/ui/StatusPill";
import { TabList, panelId, tabId, useUrlTab } from "@/components/ui/Tabs";
import { BUTTON_SECONDARY, HINT, SCROLL_X, SELECT, SURFACE, TABLE_HEAD, TABLE_ROW } from "@/components/ui/primitives";
import { CAPABILITY } from "@/constants/capabilities";
import { useCapabilityAccess } from "@/hooks/useCapabilityAccess";
import { useUpgradePrompt } from "@/hooks/useUpgradePrompt";
import { useResolvedOrganization } from "@/routes/OrganizationGuard";
import { errorMessage } from "@/services/api/errors";
import { getGstOrgSummary, listGstOrgLines, listGstOrgSuppliers } from "@/services/api/gst";
import { gstOrgKeys } from "@/services/api/queryKeys";
import { GST_STATUS_LABEL } from "@/types/gst";
import type { GstStatus } from "@/types/gst";

const TAB_IDS = ["workspaces", "suppliers", "invoices"] as const;
type TabId = (typeof TAB_IDS)[number];
const PAGE = 25;

const CHIPS: readonly { readonly label: string; readonly statuses?: readonly GstStatus[] }[] = [
  { label: "All" },
  { label: "Matched", statuses: ["MATCHED"] },
  { label: "Differences", statuses: ["MATCHED_WITH_DIFFERENCES"] },
  { label: "Waiting for supplier", statuses: ["WAITING_FOR_SUPPLIER"] },
  { label: "Not in your books", statuses: ["NOT_IN_BOOKS"] },
  { label: "Not eligible", statuses: ["NOT_ELIGIBLE"] },
];

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

interface ListProps {
  readonly organizationId: string;
  readonly gstin: string | null;
  readonly period: string | null;
}

const SuppliersList: React.FC<ListProps> = ({ organizationId, gstin, period }) => {
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: [...gstOrgKeys.suppliers(organizationId, gstin, period), offset],
    queryFn: () => listGstOrgSuppliers(organizationId, { gstin, period }, offset, PAGE),
  });
  const rows = query.data?.items ?? [];
  return (
    <div className={SURFACE} data-testid="gst-org-suppliers">
      <p className={`${HINT} px-4 pt-3`}>Who has not reported what, oldest first, across the workspaces you can read.</p>
      {query.isError ? (
        <p role="alert" className="p-4 text-sm text-destructive">{errorMessage(query.error, "Suppliers could not be loaded.")}</p>
      ) : rows.length === 0 && !query.isLoading ? (
        <p className="p-4 text-sm text-muted-foreground">Every supplier has reported what is in your books.</p>
      ) : (
        <div className={SCROLL_X}>
          <table className="w-full min-w-[680px] text-sm">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className="px-4 py-2.5">Supplier</th>
                <th className="px-4 py-2.5 text-right">Waiting</th>
                <th className="px-4 py-2.5">Oldest waiting</th>
                <th className="px-4 py-2.5 text-right">Not in your books</th>
                <th className="px-4 py-2.5 text-right">Differences</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((supplier) => (
                <tr key={supplier.supplier_gstin ?? supplier.supplier_name ?? "?"} className={TABLE_ROW} data-testid="gst-org-supplier-row">
                  <td className="px-4 py-3">
                    <div className="font-medium text-foreground">{supplier.supplier_name ?? "Unnamed supplier"}</div>
                    <div className="text-xs text-muted-foreground">{gstinShort(supplier.supplier_gstin)}</div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {supplier.waiting_count > 0 ? (
                      <>
                        {rupees(supplier.waiting_micros)}
                        <div className="text-xs text-muted-foreground">
                          {supplier.waiting_count} invoice{supplier.waiting_count === 1 ? "" : "s"}
                        </div>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3">{day(supplier.oldest_waiting)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{supplier.not_in_books_count || "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{supplier.differences_count || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager offset={offset} total={query.data?.total ?? 0} onChange={setOffset} />
    </div>
  );
};

const InvoicesList: React.FC<ListProps> = ({ organizationId, gstin, period }) => {
  const [chip, setChip] = useState(0);
  const [offset, setOffset] = useState(0);
  const [workspaceId, setWorkspaceId] = useState("");
  const summary = useQuery({
    queryKey: gstOrgKeys.summary(organizationId, gstin, period),
    queryFn: () => getGstOrgSummary(organizationId, { gstin, period }),
    staleTime: 10_000,
  });
  const active = CHIPS[chip] ?? CHIPS[0]!;
  const filters = useMemo(
    () => ({
      gstin,
      period,
      ...(active.statuses ? { status: active.statuses } : {}),
      ...(workspaceId ? { workspaceId } : {}),
      offset,
      limit: PAGE,
    }),
    [active.statuses, gstin, offset, period, workspaceId],
  );
  const query = useQuery({ queryKey: gstOrgKeys.lines(organizationId, filters), queryFn: () => listGstOrgLines(organizationId, filters) });
  const rows = query.data?.items ?? [];
  return (
    <div className="space-y-3" data-testid="gst-org-invoices">
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
        <label className="ml-auto text-xs text-muted-foreground">
          Workspace
          <select
            className={`${SELECT} ml-2 inline-block min-w-[12rem]`}
            value={workspaceId}
            onChange={(e) => {
              setWorkspaceId(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All workspaces</option>
            {(summary.data?.workspaces ?? []).map((w) => (
              <option key={w.workspace_id} value={w.workspace_id}>{w.workspace_name}</option>
            ))}
          </select>
        </label>
      </div>
      <div className={SURFACE}>
        {query.isError ? (
          <p role="alert" className="p-4 text-sm text-destructive">{errorMessage(query.error, "Invoices could not be loaded.")}</p>
        ) : rows.length === 0 && !query.isLoading ? (
          <p className="p-4 text-sm text-muted-foreground">Nothing here for this filter.</p>
        ) : (
          <div className={SCROLL_X}>
            <table className="w-full min-w-[820px] text-sm">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Invoice</th>
                  <th className="px-4 py-2.5">Workspace</th>
                  <th className="px-4 py-2.5">Date</th>
                  <th className="px-4 py-2.5 text-right">Invoice value</th>
                  <th className="px-4 py-2.5 text-right">Credit</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((line) => (
                  <tr key={line.id} className={TABLE_ROW} data-testid="gst-org-line-row" data-status={line.status}>
                    <td className="px-4 py-3">
                      <StatusPill status={line.status} tone={statusTone(line.status)} label={GST_STATUS_LABEL[line.status]} />
                      {line.risk?.at_risk ? <div className="mt-1 text-[11px] text-destructive dark:text-red-300">180-day risk</div> : null}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-foreground">{line.number ?? "No number"}</div>
                      <div className="text-xs text-muted-foreground">{line.supplier_name ?? line.supplier_gstin ?? "Unknown supplier"}</div>
                    </td>
                    <td className="px-4 py-3">{line.workspace_name ?? "—"}</td>
                    <td className="px-4 py-3">{day(line.date)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{rupees(line.value_micros)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{rupees(line.itc_micros)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager offset={offset} total={query.data?.total ?? 0} onChange={setOffset} />
      </div>
    </div>
  );
};

export const GstCreditOrganization: React.FC = () => {
  const { organizationId, organization, organizationRole } = useResolvedOrganization();
  const access = useCapabilityAccess(organizationId, CAPABILITY.gstCreditAllWorkspaces);
  const upgrade = useUpgradePrompt(organizationId, organization.organization_slug, String(organizationRole));
  const [gstinChoice, setGstinChoice] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>(null);
  const [tab, setTab] = useUrlTab<TabId>(TAB_IDS);
  const sees = String(organizationRole).toUpperCase() === "BILLING";

  useEffect(() => {
    document.title = "GST credit, all workspaces · Servabo";
  }, []);

  const first = useQuery({
    queryKey: gstOrgKeys.summary(organizationId, null, null),
    queryFn: () => getGstOrgSummary(organizationId, {}),
    enabled: access.granted && Boolean(organizationId),
    staleTime: 10_000,
  });
  const gstin = gstinChoice ?? first.data?.gstins[0] ?? null;
  const scoped = useQuery({
    queryKey: gstOrgKeys.summary(organizationId, gstin, period),
    queryFn: () => getGstOrgSummary(organizationId, { gstin, period }),
    enabled: access.granted && Boolean(gstin),
    staleTime: 10_000,
  });
  const summary = scoped.data ?? first.data;
  const tabs = useMemo(
    () =>
      [
        { id: "workspaces" as const, label: "By workspace" },
        { id: "suppliers" as const, label: "Suppliers" },
        { id: "invoices" as const, label: "Invoices" },
      ] as const,
    [],
  );

  const header = (
    <PageHeader
      icon={ReceiptIndianRupee}
      eyebrow="Organization"
      title="GST credit, all workspaces"
      description="One reconciliation per GSTIN: the GSTR-2B returns you imported in any workspace, matched with the purchase invoices of every workspace."
    />
  );

  if (access.isLoading) {return <LoadingScreen />;}
  if (!access.granted) {
    return (
      <div className="space-y-5 p-6" data-testid="gst-org-page">
        {header}
        <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="gst-org-lock" data-testid="gst-org-lock">
          <div className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-muted-foreground" aria-hidden />
            <h2 id="gst-org-lock" className="text-[15px] font-semibold text-foreground">
              Part of the Enterprise plan
            </h2>
          </div>
          <p className="text-sm text-muted-foreground">
            When purchases are booked in several workspaces, this page matches the GSTR-2B for a GSTIN with the invoices of all of
            them. Each workspace&apos;s own GST credit page keeps working on your plan.
          </p>
          <button
            type="button"
            className={BUTTON_SECONDARY}
            onClick={() => upgrade.prompt(CAPABILITY.gstCreditAllWorkspaces, "GST credit across every workspace")}
          >
            See what Enterprise adds
          </button>
        </section>
        {upgrade.dialog}
      </div>
    );
  }
  if (first.isLoading) {return <LoadingScreen />;}
  if (first.isError || !summary) {
    return (
      <div className="p-6">
        <ErrorState
          title="GST credit could not be loaded"
          description={errorMessage(first.error, "The server did not answer. Check your connection and try again.")}
          onRetry={() => void first.refetch()}
        />
      </div>
    );
  }
  const imported = summary.gstins.length > 0;
  return (
    <div className="space-y-5 p-6" data-testid="gst-org-page">
      {header}
      {!imported ? (
        <section className={`${SURFACE} space-y-2 p-6`} data-testid="gst-org-empty">
          <h2 className="text-[15px] font-semibold text-foreground">No GSTR-2B has been imported yet</h2>
          <p className="text-sm text-muted-foreground">
            Import a GSTR-2B on the GST credit page of the workspace that files for the GSTIN. It appears here as soon as it is imported,
            matched with the invoices of every workspace.
          </p>
        </section>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3" data-testid="gst-org-scope">
            <label className="text-xs text-muted-foreground">
              GSTIN
              <select
                className={`${SELECT} mt-1 block min-w-[14rem]`}
                value={gstin ?? ""}
                onChange={(e) => {
                  setGstinChoice(e.target.value);
                  setPeriod(null);
                }}
              >
                {summary.gstins.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted-foreground">
              Period
              <select className={`${SELECT} mt-1 block min-w-[12rem]`} value={period ?? ""} onChange={(e) => setPeriod(e.target.value || null)}>
                <option value="">All imported periods</option>
                {summary.periods.map((p) => (
                  <option key={p} value={p}>{periodLabel(p)}</option>
                ))}
              </select>
            </label>
            {summary.last_import ? (
              <p className={`${HINT} pb-2`}>
                Last import {day(summary.last_import.imported_at)} · {periodLabel(summary.last_import.period)}
              </p>
            ) : null}
          </div>
          <GstFigures figures={summary.figures} />
          <section aria-label="Details" className="space-y-3">
            <TabList tabs={tabs} value={tab} onChange={setTab} label="GST credit, all workspaces" idBase="gst-org" />
            <div role="tabpanel" id={panelId("gst-org", tab)} aria-labelledby={tabId("gst-org", tab)} tabIndex={0}>
              {tab === "workspaces" ? (
                <div className={SURFACE} data-testid="gst-org-workspaces">
                  <p className={`${HINT} px-4 pt-3`}>What each workspace contributes to this GSTIN.</p>
                  <div className={SCROLL_X}>
                    <table className="w-full min-w-[620px] text-sm">
                      <thead className={TABLE_HEAD}>
                        <tr>
                          <th className="px-4 py-2.5">Workspace</th>
                          <th className="px-4 py-2.5 text-right">Lines</th>
                          <th className="px-4 py-2.5 text-right">Claimable now</th>
                          <th className="px-4 py-2.5 text-right">Waiting for suppliers</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.workspaces.map((w) => (
                          <tr key={w.workspace_id} className={TABLE_ROW} data-testid="gst-org-workspace-row">
                            <td className="px-4 py-3 font-medium text-foreground">{w.workspace_name}</td>
                            <td className="px-4 py-3 text-right tabular-nums">{w.lines}</td>
                            <td className="px-4 py-3 text-right tabular-nums">{rupees(w.claimable_micros)}</td>
                            <td className="px-4 py-3 text-right tabular-nums">
                              {w.waiting_count > 0 ? (
                                <>
                                  {rupees(w.waiting_micros)}
                                  <div className="text-xs text-muted-foreground">{w.waiting_count} invoice{w.waiting_count === 1 ? "" : "s"}</div>
                                </>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : tab === "suppliers" ? (
                <SuppliersList organizationId={organizationId} gstin={gstin} period={period} />
              ) : (
                <InvoicesList organizationId={organizationId} gstin={gstin} period={period} />
              )}
            </div>
          </section>
          <p className={HINT} data-testid="gst-org-note">
            {summary.note}
            {sees ? " Lists show the workspaces you have access to." : ""}
          </p>
          <p className={`${HINT} flex items-start gap-2`}>
            <Lock className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
            {summary.disclaimer}
          </p>
        </>
      )}
      {upgrade.dialog}
    </div>
  );
};

export default GstCreditOrganization;
