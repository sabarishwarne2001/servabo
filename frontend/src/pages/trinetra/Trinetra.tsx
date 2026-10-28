import WorkspaceEvidence from "./WorkspaceEvidence";
import CaseReview from "./CaseReview";
import ExportEvidence from "./ExportEvidence";
import CaseDetail from "./CaseDetail";
import ReconciliationRun from "./ReconciliationRun";
import { Link, useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, Search, ShieldCheck, X } from "lucide-react";
import { useActiveWorkspace } from "@/hooks/useActiveWorkspace";
import { useGrantedCapabilities } from "@/hooks/useGrantedCapabilities";
import PageHeader from "@/components/ui/PageHeader";
import StatusPill from "@/components/ui/StatusPill";
import { TabList, TabPanel, useUrlTab, type TabDefinition } from "@/components/ui/Tabs";
import { BUTTON_SECONDARY, INPUT, SELECT, SURFACE } from "@/components/ui/primitives";
import { CAPABILITY } from "@/constants/capabilities";
import { useResolvedTenant } from "@/routes/TenantContext";
import { organizationBillingPath } from "@/routes/tenantPaths";
import { rupees } from "./format";
import { getTrinetraAccess, getTrinetraCockpit, listTaxProfiles } from "@/services/api/trinetra";
import AccessNotice from "./AccessNotice";
import Approvals from "./Approvals";
import CaseInsight from "./CaseInsight";
import Closures from "./Closures";
import Exceptions from "./Exceptions";
import FreshnessBanner from "./FreshnessBanner";
import ImportStatement from "./ImportStatement";
import Kpis from "./Kpis";
import { statusTone, statusWords } from "./model";
import Suggestions from "./Suggestions";
import Tutorial from "./Tutorial";
import Waterfall from "./Waterfall";

const stages = [
  "Invoice",
  "Bank receipt",
  "Deductor evidence",
  "Government statement",
  "Reviewed resolution",
];

function Cockpit() {
  const workspace = useActiveWorkspace();
  const { organization } = useResolvedTenant();
  const id = workspace?.workspaceId ?? "";
  // The examples are the safe start. Someone who chose a view keeps it; a live organization that already has a legal entity
  // lands on its own workspace.
  const [chosen, setChosen] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [year, setYear] = useState("");
  const [entity, setEntity] = useState("");
  const [sort, setSort] = useState("customer");
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const access = useQuery({
    queryKey: ["trinetra", id, "access"],
    queryFn: () => getTrinetraAccess(id),
    enabled: Boolean(id),
  });
  const live = Boolean(access.data?.live_enabled && access.data.entitled);
  const profiles = useQuery({
    queryKey: ["trinetra", id, "profiles"],
    queryFn: () => listTaxProfiles(id),
    enabled: Boolean(id) && live,
  });
  const sample = chosen ?? !(live && (profiles.data?.items.length ?? 0) > 0);
  const setSample = (value: boolean) => setChosen(value);
  const result = useQuery({
    queryKey: ["trinetra", id, "cockpit", sample],
    queryFn: () => getTrinetraCockpit(id, sample),
    enabled: Boolean(id),
  });
  const capabilities = useGrantedCapabilities(workspace?.organizationId ?? "");
  const enterprise = capabilities.granted.has(CAPABILITY.trinetraAllWorkspaces);
  const canWrite = workspace?.role === "ADMIN";
  const showTabs = live && !sample;
  const tabIds = enterprise
    ? (["cases", "statements", "suggestions", "exceptions", "approvals", "closures"] as const)
    : (["cases", "statements", "suggestions", "exceptions", "closures"] as const);
  const [tab, setTab] = useUrlTab(tabIds);
  const tabs: TabDefinition<(typeof tabIds)[number]>[] = [
    { id: "cases", label: "Cases" },
    { id: "statements", label: "Statements" },
    { id: "suggestions", label: "Suggestions" },
    { id: "exceptions", label: "Reversals" },
    ...(enterprise ? [{ id: "approvals" as const, label: "Approvals" }] : []),
    { id: "closures", label: "Closures" },
  ];
  const data = result.data;
  const rows = useMemo(
    () =>
      (data?.items ?? [])
        .filter(
          (r) =>
            (!year || String(r.year) === year) &&
            (!entity || r.profile_id === entity) &&
            (!status || r.status === status) &&
            `${r.reference} ${r.counterparty}`.toLowerCase().includes(query.toLowerCase()),
        )
        .sort((a, b) =>
          sort === "age"
            ? b.age_days - a.age_days
            : sort === "gap"
              ? BigInt(b.gap_micros ?? "0") > BigInt(a.gap_micros ?? "0")
                ? 1
                : -1
              : a.counterparty.localeCompare(b.counterparty),
        ),
    [data, query, status, year, entity, sort],
  );
  const current = data?.items.find((r) => r.id === selected);
  const cases = (
    <>
      {!sample && live && canWrite && <WorkspaceEvidence workspaceId={id} />}
      {!sample && live && canWrite && <ExportEvidence workspaceId={id} />}
      {!sample && live && canWrite && <ReconciliationRun workspaceId={id} />}
      <div className="flex flex-wrap gap-3">
        {!sample && live && (profiles.data?.items.length ?? 0) > 0 && (
          <label className="text-sm">
            Legal entity
            <select
              className={`${SELECT} ml-2`}
              value={entity}
              onChange={(e) => {
                setEntity(e.target.value);
                setPage(0);
              }}
            >
              <option value="">All entities</option>
              {profiles.data?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.pan_masked}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="text-sm">
          Tax period
          <select
            className={`${SELECT} ml-2`}
            value={year}
            onChange={(e) => {
              setYear(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All periods</option>
            {[...new Set(data?.items.map((r) => r.year))].map((y) => (
              <option key={y} value={y}>
                {data?.items.find((r) => r.year === y)?.period ?? y}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Sort cases
          <select
            className={`${SELECT} ml-2`}
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setPage(0);
            }}
          >
            <option value="customer">Customer</option>
            <option value="age">Oldest first</option>
            <option value="gap">Largest possible gap</option>
          </select>
        </label>
      </div>
      {result.isPending ? (
        <p role="status">Loading credit evidence…</p>
      ) : result.isError ? (
        <div role="alert" className={`${SURFACE} p-6`}>
          Credit evidence could not be loaded.{" "}
          <button className={BUTTON_SECONDARY} onClick={() => void result.refetch()}>
            Try again
          </button>
        </div>
      ) : data ? (
        <>
          <Kpis data={data} sample={sample} />
          {!sample && data.outcomes && (
            <section className={`${SURFACE} p-4 text-sm`} aria-label="Measured review outcomes">
              <p className="font-medium">
                TDS now visible in your statement:{" "}
                {rupees(data.outcomes.now_visible_total_micros ?? "0")} ·{" "}
                {data.outcomes.now_visible_cases ?? 0} cases · {data.outcomes.review_minutes}{" "}
                recorded review minutes
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {data.outcomes.ledger_note ?? data.outcomes.note} Confirmed later gap closure:{" "}
                {rupees(data.outcomes.confirmed_gap_closure_micros)} across{" "}
                {data.outcomes.confirmed_cases} reviewed cases.
              </p>
            </section>
          )}
          <ol
            className={`${SURFACE} grid gap-3 p-5 sm:grid-cols-5`}
            aria-label="Five evidence stages"
          >
            {stages.map((stage, i) => (
              <li key={stage} className="flex items-center gap-3 text-sm">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-primary/40 text-primary">
                  {i + 1}
                </span>
                {stage}
              </li>
            ))}
          </ol>
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <section className={`${SURFACE} overflow-hidden`} aria-labelledby="credit-queue">
              <div className="space-y-3 border-b border-border p-5">
                <h2 id="credit-queue" className="font-semibold">
                  Credit exception queue
                </h2>
                <p className="text-sm text-muted-foreground">
                  Amounts, source confidence, and the next evidence to review.
                </p>
                <div className="flex flex-wrap gap-3">
                  <label className="flex min-w-0 flex-1 items-center gap-2">
                    <Search className="h-4 w-4" aria-hidden />
                    <span className="sr-only">Search customer or invoice</span>
                    <input
                      className={INPUT}
                      value={query}
                      placeholder="Customer or invoice reference"
                      onChange={(e) => {
                        setQuery(e.target.value);
                        setPage(0);
                      }}
                    />
                  </label>
                  <label>
                    <span className="sr-only">Exception status</span>
                    <select
                      className={SELECT}
                      value={status}
                      onChange={(e) => {
                        setStatus(e.target.value);
                        setPage(0);
                      }}
                    >
                      <option value="">All exceptions</option>
                      {[...new Set(data.items.map((r) => r.status))].map((s) => (
                        <option key={s} value={s}>
                          {statusWords(s)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
              <ul className="divide-y divide-border">
                {rows.slice(page * 8, page * 8 + 8).map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => setSelected(r.id)}
                      aria-pressed={selected === r.id}
                      className={`grid w-full gap-2 p-4 text-left transition-colors hover:bg-muted/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary sm:grid-cols-[1fr_1fr_auto] ${selected === r.id ? "bg-primary/10" : ""}`}
                    >
                      <span>
                        <span className="block text-sm font-medium">{r.counterparty}</span>
                        <span className="text-xs text-muted-foreground">
                          {r.reference} · {r.period ?? `Year starting ${r.year}`}
                        </span>
                      </span>
                      <span className="text-sm text-muted-foreground">
                        {statusWords(r.status)}
                        <span className="block text-xs">{r.age_days} days open</span>
                      </span>
                      <span className="text-sm font-semibold tabular-nums">
                        {rupees(r.gap_micros)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {!rows.length && (
                <p className="p-8 text-center text-muted-foreground">
                  No cases match these filters.
                </p>
              )}
              <div className="flex items-center justify-between border-t border-border p-4 text-sm">
                <span>{rows.length} cases</span>
                <div className="flex gap-2">
                  <button
                    className={BUTTON_SECONDARY}
                    disabled={!page}
                    onClick={() => setPage(page - 1)}
                  >
                    Previous
                  </button>
                  <button
                    className={BUTTON_SECONDARY}
                    disabled={(page + 1) * 8 >= rows.length}
                    onClick={() => setPage(page + 1)}
                  >
                    Next
                  </button>
                </div>
              </div>
            </section>
            <aside
              className={`${SURFACE} space-y-4 p-5`}
              aria-label="Case insight"
              aria-live="polite"
            >
              <div className="flex justify-between">
                <h2 className="font-semibold">Case insight</h2>
                {current && (
                  <button aria-label="Close case insight" onClick={() => setSelected(null)}>
                    <X className="h-5 w-5" />
                  </button>
                )}
              </div>
              {current ? (
                <>
                  <h3 className="font-medium">{current.counterparty}</h3>
                  <p className="text-xs text-muted-foreground">
                    {current.reference} · {current.period ?? current.year}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill
                      status={current.status}
                      tone={statusTone(current.status)}
                      label={statusWords(current.status)}
                    />
                  </div>
                  <dl className="space-y-3 rounded-lg border border-border p-4">
                    {[
                      ["Supported expected", current.expected_micros],
                      ["Allocated posting", current.posted_micros],
                      ["Possible gap", current.gap_micros],
                      ["Bank receipt", current.bank_micros],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="flex justify-between gap-3 text-sm">
                        <dt>{label}</dt>
                        <dd className="font-medium tabular-nums">
                          {rupees(value as string | null)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <p className="text-sm text-muted-foreground">{current.note}</p>
                  {sample ? (
                    <Waterfall item={current} />
                  ) : (
                    <CaseInsight workspaceId={id} item={current} timeline={false} />
                  )}
                  <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
                    <h3 className="text-sm font-semibold">Next evidence to review</h3>
                    <p className="mt-2 text-sm">
                      {current.status === "POSTED"
                        ? "Ask the accountant to review the source and allocation before drawing a tax conclusion."
                        : "Compare the invoice, deduction advice and uploaded statement. Request clarification from the deductor when records differ."}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {sample
                      ? "Read-only synthetic scenario. No inquiry is sent."
                      : "Review actions require an authorized workspace administrator."}{" "}
                    Rule: {current.rule_version}
                  </p>
                  {!sample && (
                    <Link
                      className={BUTTON_SECONDARY}
                      to={`?case=${encodeURIComponent(current.id)}`}
                    >
                      Compare source documents
                    </Link>
                  )}
                  {!sample && (
                    <CaseReview
                      key={current.id}
                      workspaceId={id}
                      creditId={current.id}
                      canDecide={canWrite}
                    />
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Choose a case to inspect its evidence and amounts.
                </p>
              )}
            </aside>
          </div>
          <p className="text-xs text-muted-foreground">{data.note}</p>
        </>
      ) : null}
    </>
  );
  return (
    <div className="space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Eye}
        eyebrow="TRINETRA"
        title="Credit assurance"
        description="Trace withheld tax from invoice to government statement."
        badge={
          <span className="rounded-full border border-border px-3 py-1 text-xs">
            {sample ? "Illustrative synthetic data" : "Reviewed evidence"}
          </span>
        }
        actions={
          live ? (
            <button
              className={BUTTON_SECONDARY}
              onClick={() => {
                setSample(!sample);
                setSelected(null);
                setPage(0);
              }}
            >
              {sample ? "Your workspace" : "Explore examples"}
            </button>
          ) : undefined
        }
      />
      {access.data && workspace && (
        <AccessNotice
          access={access.data}
          billingPath={organizationBillingPath(organization.organization_slug)}
        />
      )}
      {access.isError && (
        <p role="alert" className={`${SURFACE} p-4 text-sm`}>
          Access to TDS credit could not be checked.{" "}
          <button className={BUTTON_SECONDARY} onClick={() => void access.refetch()}>
            Try again
          </button>
        </p>
      )}
      <section
        className={`${SURFACE} flex gap-3 p-4 text-sm`}
        aria-label="Evidence and availability"
      >
        <ShieldCheck className="h-5 w-5 shrink-0 text-primary" aria-hidden />
        <div>
          <p className="font-medium">
            {sample
              ? "Explore the evidence chain without uploading tax documents"
              : "Evidence reflects the selected imported snapshot"}
          </p>
          <p className="mt-1 text-muted-foreground">
            A gap is an investigation item. It is not a tax refund or a legally claimable credit.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {data?.as_of
              ? `Evidence as of ${data.as_of}. Later postings require a new reviewed snapshot.`
              : "No statement has been imported."}
          </p>
        </div>
      </section>
      {showTabs && data && <FreshnessBanner asOf={data.as_of} items={data.items} />}
      {live && (
        <Tutorial
          workspaceId={id}
          profiles={profiles.data?.items.length ?? 0}
          items={sample ? [] : (data?.items ?? [])}
          hasStatement={!sample && Boolean(data?.as_of)}
          onOpen={(next) => {
            setSample(false);
            setTab(next);
          }}
        />
      )}
      {sample && (
        <details className={`${SURFACE} p-4 text-sm`}>
          <summary className="cursor-pointer font-semibold">
            Getting started with credit evidence
          </summary>
          <ol className="mt-3 list-decimal space-y-2 pl-5">
            <li>
              Confirm the receiving entity and source period. Upload documents through Documents;
              ordinary access, retention and intake limits apply.
            </li>
            <li>
              Record only a supported withholding expectation. Bank shortfalls do not establish TDS;
              tax basis and eligibility may remain unknown.
            </li>
            <li>
              Compare Helm bank receipts, customer advice and accounting evidence. Link the
              originals so another reviewer can inspect them.
            </li>
            <li>
              Import your statement from the Servabo template, a Form 26AS or Form 168 text file, or
              an AIS CSV, after previewing it.
            </li>
            <li>
              Allocate posted amounts with a reason, ask the customer for a document, and export a
              dossier for accountant review.
            </li>
          </ol>
        </details>
      )}
      {showTabs ? (
        <>
          <TabList
            tabs={tabs}
            value={tab}
            onChange={setTab}
            label="TDS credit sections"
            idBase="trinetra"
          />
          <TabPanel idBase="trinetra" id={tab} className="space-y-6">
            {tab === "cases" && cases}
            {tab === "statements" &&
              (access.data ? <ImportStatement workspaceId={id} access={access.data} /> : null)}
            {tab === "suggestions" && <Suggestions workspaceId={id} canDecide={canWrite} />}
            {tab === "exceptions" && <Exceptions workspaceId={id} canDecide={canWrite} />}
            {tab === "approvals" && (
              <Approvals workspaceId={id} organizationId={workspace?.organizationId ?? ""} />
            )}
            {tab === "closures" && <Closures workspaceId={id} />}
          </TabPanel>
        </>
      ) : (
        cases
      )}
    </div>
  );
}

export default function Trinetra() {
  const [params] = useSearchParams();
  const creditId = params.get("case");
  return creditId ? <CaseDetail key={creditId} creditId={creditId} /> : <Cockpit />;
}
