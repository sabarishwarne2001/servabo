import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Download, Lock, ReceiptIndianRupee, ShieldCheck, Sparkles } from "lucide-react";
import { toast } from "sonner";

import GstFigures from "@/components/gst/GstFigures";
import GstImport from "@/components/gst/GstImport";
import { ImsTab, InvoicesTab, SuppliersTab } from "@/components/gst/GstTabs";
import PreviewLock from "@/components/gst/PreviewLock";
import { day, periodLabel, rupees } from "@/components/gst/gstFormat";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingScreen } from "@/components/common/LoadingScreen";
import PageHeader from "@/components/ui/PageHeader";
import { TabList, panelId, tabId, useUrlTab } from "@/components/ui/Tabs";
import { BUTTON_SECONDARY, HINT, SELECT, SURFACE } from "@/components/ui/primitives";
import { CAPABILITY } from "@/constants/capabilities";
import { useActiveWorkspace } from "@/hooks/useActiveWorkspace";
import { useTenant } from "@/hooks/useTenant";
import { useUpgradePrompt } from "@/hooks/useUpgradePrompt";
import { gstPath } from "@/routes/tenantPaths";
import { errorMessage } from "@/services/api/errors";
import { downloadGstWorkbook, getGstSummary } from "@/services/api/gst";
import { buildHelmSample, getHelmOverview, helmKeys } from "@/services/api/helm";
import { gstKeys } from "@/services/api/queryKeys";

const TAB_IDS = ["suppliers", "invoices", "ims"] as const;
type TabId = (typeof TAB_IDS)[number];
const SAMPLE_SLUG = "sample-meridian";
const WRITE_ROLES = new Set(["ADMIN", "CONTRIBUTOR"]);

const STEPS: readonly string[] = [
  "Sign in to the GST portal (gst.gov.in) and open Returns Dashboard.",
  "Choose the financial year and the month, then press Search.",
  "On the GSTR-2B tile choose Download, and pick JSON (Excel will not do).",
  "Drop the downloaded file here. A .zip holding the JSON works too.",
];

const EmptyGst: React.FC<{ readonly onSample: () => void; readonly sampleBusy: boolean; readonly sampleHint: string | null }> = ({
  onSample,
  sampleBusy,
  sampleHint,
}) => (
  <section className={`${SURFACE} space-y-4 p-6`} aria-labelledby="gst-empty-title" data-testid="gst-empty">
    <h2 id="gst-empty-title" className="text-[15px] font-semibold text-foreground">
      See how much GST credit you can claim, and from whom
    </h2>
    <p className="text-sm text-muted-foreground">
      Servabo has already read your purchase invoices. Import your GSTR-2B and it shows what you can claim now, which suppliers have not
      reported your invoices, what differs, and what to do on the GST portal.
    </p>
    <ol className="list-decimal space-y-1 pl-5 text-sm text-foreground" aria-label="How to download GSTR-2B">
      {STEPS.map((step) => (
        <li key={step}>{step}</li>
      ))}
    </ol>
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      Your file stays in your workspace. It is read on our servers, kept with your other documents and never shared. This is a
      recommendation, not tax advice: check with your chartered accountant.
    </p>
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" className={`${BUTTON_SECONDARY} inline-flex items-center gap-1.5`} onClick={onSample} disabled={sampleBusy}>
        <Sparkles className="h-3.5 w-3.5" aria-hidden />
        {sampleBusy ? "Getting the sample ready…" : "Explore with the sample company"}
      </button>
      {sampleHint ? <span className={HINT}>{sampleHint}</span> : null}
    </div>
  </section>
);

export const GstCredit: React.FC = () => {
  const workspace = useActiveWorkspace();
  const { state } = useTenant();
  const navigate = useNavigate();
  const workspaceId = workspace?.workspaceId ?? "";
  const organizationId = workspace?.organizationId ?? "";
  const ready = state.status === "ready";
  const orgSlug = ready ? state.organization.organization_slug : "";
  const orgRole = ready ? String(state.organizationRole) : "MEMBER";
  const upgrade = useUpgradePrompt(organizationId, orgSlug, orgRole);
  const canDecide = WRITE_ROLES.has(String(workspace?.role ?? "").toUpperCase());

  const [gstinChoice, setGstinChoice] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>(null);
  const [tab, setTab] = useUrlTab<TabId>(TAB_IDS);

  const first = useQuery({
    queryKey: gstKeys.summary(workspaceId, null, null),
    queryFn: () => getGstSummary(workspaceId, {}),
    enabled: Boolean(workspaceId),
    staleTime: 10_000,
  });
  const gstin = gstinChoice ?? first.data?.gstins[0] ?? null;
  const scoped = useQuery({
    queryKey: gstKeys.summary(workspaceId, gstin, period),
    queryFn: () => getGstSummary(workspaceId, { gstin, period }),
    enabled: Boolean(workspaceId) && Boolean(gstin),
    staleTime: 10_000,
  });
  const summary = scoped.data ?? first.data;

  useEffect(() => {
    document.title = "GST credit · Servabo";
  }, []);

  // "Explore with the sample company": open it if it exists, else build it (owners and admins) and open it when ready.
  const helm = useQuery({
    queryKey: helmKeys.overview(organizationId),
    queryFn: () => getHelmOverview(organizationId),
    enabled: Boolean(organizationId) && summary !== undefined && summary.gstins.length === 0 && !summary.is_sample,
    retry: false,
    refetchInterval: (q) => (q.state.data?.sample.building ? 3_000 : false),
  });
  const buildSample = useMutation({
    mutationFn: () => buildHelmSample(organizationId),
    onError: (error) => toast.error(errorMessage(error, "The sample company could not be built.")),
  });
  const sampleReady = Boolean(helm.data?.sample.workspace_id);
  useEffect(() => {
    if (buildSample.isSuccess && sampleReady) {navigate(gstPath(orgSlug, SAMPLE_SLUG));}
  }, [buildSample.isSuccess, navigate, orgSlug, sampleReady]);
  const onSample = (): void => {
    if (sampleReady) {navigate(gstPath(orgSlug, SAMPLE_SLUG));}
    else {buildSample.mutate();}
  };
  const sampleBusy = buildSample.isPending || Boolean(helm.data?.sample.building);
  const sampleHint = helm.isError ? "Ask an owner or admin to build the sample company in Helm, then come back." : null;

  const workbook = useMutation({
    mutationFn: () => downloadGstWorkbook(workspaceId, { gstin, period }),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `gst-credit-${gstin ?? "all"}-${period ?? "all"}.xlsx`;
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: (error) => toast.error(errorMessage(error, "The export could not be made.")),
  });

  const full = summary?.access.full ?? false;
  const tabs = useMemo(
    () =>
      [
        { id: "suppliers" as const, label: "Suppliers" },
        { id: "invoices" as const, label: "Invoices" },
        { id: "ims" as const, label: "IMS actions" },
      ] as const,
    [],
  );

  if (!workspace || first.isLoading) {return <LoadingScreen />;}
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
  const waiting = summary.figures.find((f) => f.key === "waiting");
  const lockTeaser = (what: string): string =>
    waiting && waiting.count > 0
      ? `${rupees(waiting.amount_micros)} of GST credit is waiting on ${waiting.suppliers ?? 0} supplier${waiting.suppliers === 1 ? "" : "s"}. ${what}`
      : what;

  return (
    <div className="space-y-5 p-6" data-testid="gst-page">
      <PageHeader
        icon={ReceiptIndianRupee}
        eyebrow="Documents"
        title="GST credit"
        description="Match your purchase invoices with GSTR-2B: what you can claim, who has not reported, and what to do on the GST portal."
        badge={summary.is_sample ? <span className="rounded-full border border-border px-2 py-0.5 text-[11px]">Sample company</span> : undefined}
        actions={
          full && imported ? (
            <button
              type="button"
              className={`${BUTTON_SECONDARY} inline-flex items-center gap-1.5`}
              onClick={() => workbook.mutate()}
              disabled={workbook.isPending || !canDecide}
              title={canDecide ? undefined : "Viewers cannot export"}
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              Export to Excel
            </button>
          ) : undefined
        }
      />

      {imported ? (
        <div className="flex flex-wrap items-end gap-3" data-testid="gst-scope">
          <label className="text-xs text-muted-foreground">
            GSTIN
            <select className={`${SELECT} mt-1 block min-w-[14rem]`} value={gstin ?? ""} onChange={(e) => { setGstinChoice(e.target.value); setPeriod(null); }}>
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
            <p className={`${HINT} pb-2`} data-testid="gst-last-import">
              Last import {day(summary.last_import.imported_at)} · {periodLabel(summary.last_import.period)}
              {summary.last_import.version ? ` · version ${summary.last_import.version}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}

      {!imported ? (
        <EmptyGst onSample={onSample} sampleBusy={sampleBusy} sampleHint={sampleHint} />
      ) : (
        <GstFigures figures={summary.figures} />
      )}

      {summary.is_sample ? (
        <p className={HINT}>You are looking at the invented sample company. It is read-only: import your own GSTR-2B in your own workspace.</p>
      ) : (
        <GstImport workspaceId={workspaceId} disabledReason={canDecide ? null : "Viewers cannot import. Ask a contributor or an admin."} />
      )}

      {imported ? (
        <section aria-label="Details" className="space-y-3">
          <TabList tabs={tabs} value={tab} onChange={setTab} label="GST credit views" idBase="gst" />
          <div role="tabpanel" id={panelId("gst", tab)} aria-labelledby={tabId("gst", tab)} tabIndex={0}>
            {!full ? (
              <PreviewLock
                title={tab === "suppliers" ? "Which suppliers have not reported" : tab === "invoices" ? "Every invoice, side by side with GSTR-2B" : "What to do on the GST portal"}
                teaser={lockTeaser(
                  tab === "suppliers"
                    ? "The supplier list shows who, oldest first, with a drafted reminder."
                    : tab === "invoices"
                      ? "The invoice list shows each one beside GSTR-2B with the differences highlighted."
                      : "IMS actions recommend Accept, Pending or Reject for each record, with the reason.",
                )}
                onUpgrade={() => upgrade.prompt(CAPABILITY.gstCredit, "GST credit: supplier and invoice lists, IMS recommendations and export")}
                organizationId={organizationId}
                organizationSlug={orgSlug}
                isOwner={orgRole.toUpperCase() === "OWNER"}
              />
            ) : tab === "suppliers" ? (
              <SuppliersTab workspaceId={workspaceId} gstin={gstin} period={period} canDecide={canDecide && !summary.is_sample} />
            ) : tab === "invoices" ? (
              <InvoicesTab workspaceId={workspaceId} gstin={gstin} period={period} canDecide={canDecide && !summary.is_sample} />
            ) : (
              <ImsTab workspaceId={workspaceId} gstin={gstin} period={period} canDecide={canDecide && !summary.is_sample} />
            )}
          </div>
        </section>
      ) : null}

      {imported ? (
        <p className={`${HINT} flex items-start gap-2`} data-testid="gst-disclaimer">
          <Lock className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          {summary.disclaimer} Amounts read from your invoices and GSTR-2B; the rounding tolerance is {rupees(summary.tolerance_micros)} per amount.
        </p>
      ) : null}
      {upgrade.dialog}
    </div>
  );
};

export default GstCredit;
