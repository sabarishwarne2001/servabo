import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  INPUT,
  SELECT,
  SURFACE,
} from "@/components/ui/primitives";
import StatusPill from "@/components/ui/StatusPill";
import { errorMessage } from "@/services/api/errors";
import {
  acceptSuggestion,
  confirmDeductor,
  dismissSuggestion,
  importSuggestionTemplate,
  listDeductors,
  listSuggestions,
  listTaxProfiles,
  previewSuggestionTemplate,
  scanSuggestions,
  scanZohoSuggestions,
  suggestionTemplate,
  type Deductor,
  type Suggestion,
  type TemplatePreview,
} from "@/services/api/trinetra";
import { saveBlob } from "./download";
import { rupees } from "./format";

const SOURCE_WORDS: Readonly<Record<string, string>> = {
  PRINTED_HINT: "Printed on the invoice",
  TEMPLATE: "Your expected-TDS template",
  ZOHO: "Zoho Books (unverified)",
};

const sourceWords = (source: string): string =>
  SOURCE_WORDS[source] ?? source.toLowerCase().replaceAll("_", " ");

function Sources({
  workspaceId,
  profile,
  onProfile,
}: {
  workspaceId: string;
  profile: string;
  onProfile: (id: string) => void;
}) {
  const cache = useQueryClient();
  const profiles = useQuery({
    queryKey: ["trinetra", workspaceId, "profiles"],
    queryFn: () => listTaxProfiles(workspaceId),
  });
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [skip, setSkip] = useState(true);
  const refresh = () => void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
  const scan = useMutation({
    mutationFn: () => scanSuggestions(workspaceId, profile),
    onSuccess: refresh,
  });
  const zoho = useMutation({
    mutationFn: () => scanZohoSuggestions(workspaceId, profile),
    onSuccess: refresh,
  });
  const template = useMutation({
    mutationFn: async (format: "csv" | "xlsx") =>
      saveBlob(
        await suggestionTemplate(workspaceId, format),
        `servabo-expected-tds-template.${format}`,
      ),
  });
  const check = useMutation({
    mutationFn: () => {
      if (!file) {
        throw new Error("Choose the file first.");
      }
      return previewSuggestionTemplate(workspaceId, file, profile);
    },
    onSuccess: setPreview,
  });
  const load = useMutation({
    mutationFn: () => {
      if (!file) {
        throw new Error("Choose the file first.");
      }
      return importSuggestionTemplate(workspaceId, file, profile, skip);
    },
    onSuccess: () => {
      setPreview(null);
      setFile(null);
      refresh();
    },
  });
  const failure = [scan, zoho, template, check, load].find((m) => m.isError);
  return (
    <section
      className={`${SURFACE} space-y-4 p-5`}
      aria-labelledby="suggestion-sources"
      data-testid="trinetra-sources"
    >
      <div>
        <h2 id="suggestion-sources" className="font-semibold">
          Find invoices where a customer withheld tax
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Servabo only suggests. Nothing becomes a case until a person accepts it with a reason. A
          printed or imported figure is not a rate or a section recommendation.
        </p>
      </div>
      <label className="block text-sm sm:max-w-sm">
        Legal entity
        <select
          className={`${SELECT} mt-1`}
          value={profile}
          onChange={(e) => onProfile(e.target.value)}
        >
          <option value="">Choose a profile</option>
          {profiles.data?.items.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} · {p.pan_masked}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          className={BUTTON_SECONDARY}
          disabled={!profile || scan.isPending}
          onClick={() => scan.mutate()}
        >
          Look for TDS printed on invoices
        </button>
        <button
          className={BUTTON_SECONDARY}
          disabled={!profile || zoho.isPending}
          onClick={() => zoho.mutate()}
        >
          Read Zoho Books (read only, unverified)
        </button>
      </div>
      {scan.isSuccess && (
        <p role="status" className="text-sm">
          Looked at your invoices. New suggestions are listed below.
        </p>
      )}
      {zoho.isSuccess && (
        <p role="status" className="text-sm">
          Read Zoho Books. New suggestions are listed below.
        </p>
      )}
      <details className="rounded-lg border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">
          Fill in an expected-TDS template
        </summary>
        <div className="mt-3 space-y-3 text-sm">
          <div className="flex flex-wrap gap-2">
            {(["csv", "xlsx"] as const).map((format) => (
              <button
                key={format}
                type="button"
                className={BUTTON_SECONDARY}
                onClick={() => template.mutate(format)}
              >
                Download the template ({format.toUpperCase()})
              </button>
            ))}
          </div>
          <label className="block">
            The filled template
            <input
              type="file"
              accept=".csv,.xlsx"
              className={`${INPUT} mt-1`}
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setPreview(null);
              }}
            />
          </label>
          <button
            className={BUTTON_SECONDARY}
            disabled={!file || !profile || check.isPending}
            onClick={() => check.mutate()}
          >
            Check each row against your invoices
          </button>
          {preview && (
            <div className="space-y-2" role="region" aria-label="Template check">
              <p className="font-medium">
                {preview.ok} of {preview.rows} rows match exactly one invoice.
              </p>
              <ul className="space-y-1 text-xs">
                {preview.items.map((row) => (
                  <li key={row.row} data-status={row.status}>
                    Row {row.row} · {row.reference} · {rupees(row.amount_micros)} ·{" "}
                    {row.status === "OK" ? "matches one invoice" : (row.reason ?? row.status)}
                  </li>
                ))}
              </ul>
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} />
                Skip the rows that do not match and add the rest as suggestions.
              </label>
              <button
                className={BUTTON_PRIMARY}
                disabled={load.isPending || (!skip && preview.ok < preview.rows)}
                onClick={() => load.mutate()}
              >
                Add as suggestions
              </button>
            </div>
          )}
        </div>
      </details>
      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(failure.error, "That did not work.")}
        </p>
      )}
    </section>
  );
}

function SuggestionCard({
  workspaceId,
  item,
  canDecide,
}: {
  workspaceId: string;
  item: Suggestion;
  canDecide: boolean;
}) {
  const cache = useQueryClient();
  const [mode, setMode] = useState<"accept" | "dismiss" | null>(null);
  const [reason, setReason] = useState("");
  const [tan, setTan] = useState("");
  const [seller, setSeller] = useState(false);
  const done = () => {
    setMode(null);
    setReason("");
    void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
  };
  const accept = useMutation({
    mutationFn: () =>
      acceptSuggestion(workspaceId, item.id, {
        source_confirmation: reason,
        ...(item.needs_tan ? { tan } : {}),
        seller_name_confirmed: seller,
      }),
    onSuccess: done,
  });
  const dismiss = useMutation({
    mutationFn: () => dismissSuggestion(workspaceId, item.id, reason),
    onSuccess: done,
  });
  const active = mode === "accept" ? accept : dismiss;
  return (
    <li className="space-y-2 p-4" data-testid="trinetra-suggestion" data-source={item.source}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium">
            {item.counterparty} · {item.reference}
          </p>
          <p className="text-xs text-muted-foreground">
            {sourceWords(item.source)} · tax year starting {item.year} ·{" "}
            {item.section_text ? `as printed: ${item.section_text}` : "no section printed"} ·{" "}
            {item.needs_tan ? "TAN needed" : item.tan_masked}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-semibold tabular-nums">{rupees(item.amount_micros)}</span>
          <StatusPill
            status={item.status}
            label={
              item.status === "OPEN"
                ? "To confirm"
                : item.status === "ACCEPTED"
                  ? "Accepted"
                  : "Dismissed"
            }
          />
        </div>
      </div>
      {item.decided_reason && (
        <p className="text-xs text-muted-foreground">{item.decided_reason}</p>
      )}
      {canDecide && item.status === "OPEN" && !mode && (
        <div className="flex gap-2">
          <button className={BUTTON_SECONDARY} onClick={() => setMode("accept")}>
            Accept as a case
          </button>
          <button className={BUTTON_SECONDARY} onClick={() => setMode("dismiss")}>
            Dismiss
          </button>
        </div>
      )}
      {mode && (
        <form
          className="space-y-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            (mode === "accept" ? accept : dismiss).mutate();
          }}
        >
          {mode === "accept" && item.needs_tan && (
            <label className="block">
              The customer's TAN (as on their advice)
              <input
                required
                autoComplete="off"
                pattern="[A-Z]{4}[0-9]{5}[A-Z]"
                maxLength={10}
                className={`${INPUT} mt-1`}
                value={tan}
                onChange={(e) => setTan(e.target.value.toUpperCase())}
              />
            </label>
          )}
          <label className="block">
            {mode === "accept"
              ? "Why you accept this (the evidence you checked)"
              : "Why you dismiss this"}
            <textarea
              required
              minLength={10}
              maxLength={1000}
              className={`${INPUT} mt-1`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {mode === "accept" && (
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={seller}
                onChange={(e) => setSeller(e.target.checked)}
              />
              The seller's name on the invoice is a different spelling of this legal entity, and I
              checked it is the same.
            </label>
          )}
          <div className="flex gap-2">
            <button className={BUTTON_PRIMARY} disabled={active.isPending}>
              {mode === "accept" ? "Accept" : "Dismiss"}
            </button>
            <button type="button" className={BUTTON_SECONDARY} onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
          {active.isError && (
            <p role="alert" className="text-destructive">
              {errorMessage(active.error, "That could not be saved.")}
            </p>
          )}
        </form>
      )}
    </li>
  );
}

function Customers({ workspaceId, canDecide }: { workspaceId: string; canDecide: boolean }) {
  const cache = useQueryClient();
  const deductors = useQuery({
    queryKey: ["trinetra", workspaceId, "deductors"],
    queryFn: () => listDeductors(workspaceId),
  });
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const confirm = useMutation({
    mutationFn: (row: Deductor) =>
      confirmDeductor(workspaceId, row.id, { counterparty: name, reason }),
    onSuccess: () => {
      setOpen(null);
      setReason("");
      void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
    },
  });
  const rows = deductors.data?.items ?? [];
  return (
    <section
      className={`${SURFACE} p-5`}
      aria-labelledby="customer-directory"
      data-testid="trinetra-directory"
    >
      <h2 id="customer-directory" className="font-semibold">
        Customers and their TANs
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Which TAN belongs to which customer. Only a masked TAN is kept. A flagged TAN (the same TAN
        under two customers) blocks accepting a suggestion until a person confirms who it is.
      </p>
      {deductors.isPending && (
        <p role="status" className="mt-3 text-sm">
          Loading customers…
        </p>
      )}
      {deductors.isError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          The customers could not be loaded.
        </p>
      )}
      {deductors.data && !rows.length && (
        <p className="mt-3 text-sm text-muted-foreground">
          No customer has a TAN on record yet. They appear as you accept suggestions and import
          statements.
        </p>
      )}
      <ul className="mt-3 divide-y divide-border">
        {rows.map((row) => (
          <li key={row.id} className="py-3" data-status={row.status}>
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                <span className="font-medium">{row.counterparty}</span> ·{" "}
                <span className="font-mono">{row.tan_masked}</span>
                {row.seen_as.length > 1 && (
                  <span className="block text-xs text-muted-foreground">
                    Also seen as: {row.seen_as.join(", ")}
                  </span>
                )}
              </span>
              <span className="flex items-center gap-2">
                <StatusPill
                  status={row.status}
                  label={
                    row.status === "CONFIRMED"
                      ? "Confirmed"
                      : row.status === "FLAGGED"
                        ? "Needs a decision"
                        : "Proposed"
                  }
                />
                {canDecide && row.status !== "CONFIRMED" && (
                  <button
                    className={BUTTON_SECONDARY}
                    onClick={() => {
                      setOpen(row.id);
                      setName(row.counterparty);
                    }}
                  >
                    Confirm
                  </button>
                )}
              </span>
            </div>
            {open === row.id && (
              <form
                className="mt-2 space-y-2 text-sm"
                onSubmit={(e) => {
                  e.preventDefault();
                  confirm.mutate(row);
                }}
              >
                <label className="block">
                  Customer this TAN belongs to
                  <input
                    required
                    maxLength={120}
                    className={`${INPUT} mt-1`}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className="block">
                  Why (what you checked)
                  <textarea
                    required
                    minLength={10}
                    maxLength={1000}
                    className={`${INPUT} mt-1`}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
                <button className={BUTTON_PRIMARY} disabled={confirm.isPending}>
                  Confirm this customer
                </button>
                {confirm.isError && (
                  <p role="alert" className="text-destructive">
                    {errorMessage(confirm.error, "That could not be saved.")}
                  </p>
                )}
              </form>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Suggested expectations (printed on invoices, from a template, from Zoho Books), the person who accepts them, and the customer directory. */
export default function Suggestions({
  workspaceId,
  canDecide,
}: {
  workspaceId: string;
  canDecide: boolean;
}) {
  const [profile, setProfile] = useState("");
  const [status, setStatus] = useState("OPEN");
  const suggestions = useQuery({
    queryKey: ["trinetra", workspaceId, "suggestions", status],
    queryFn: () => listSuggestions(workspaceId, status ? { status } : {}),
  });
  const items = suggestions.data?.items ?? [];
  return (
    <div className="space-y-4">
      {canDecide && <Sources workspaceId={workspaceId} profile={profile} onProfile={setProfile} />}
      <section className={`${SURFACE} overflow-hidden`} aria-labelledby="suggestion-list">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4">
          <h2 id="suggestion-list" className="font-semibold">
            Suggestions
          </h2>
          <label className="text-sm">
            Show
            <select
              className={`${SELECT} ml-2`}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="OPEN">Waiting for a person</option>
              <option value="ACCEPTED">Accepted</option>
              <option value="DISMISSED">Dismissed</option>
              <option value="">All</option>
            </select>
          </label>
        </div>
        {suggestions.isPending && (
          <p role="status" className="p-5 text-sm">
            Loading suggestions…
          </p>
        )}
        {suggestions.isError && (
          <p role="alert" className="p-5 text-sm">
            The suggestions could not be loaded.{" "}
            <button className={BUTTON_SECONDARY} onClick={() => void suggestions.refetch()}>
              Try again
            </button>
          </p>
        )}
        {suggestions.data && !items.length && (
          <p
            className="p-6 text-center text-sm text-muted-foreground"
            data-testid="trinetra-suggestions-empty"
          >
            Nothing is waiting. Look for TDS printed on your invoices, or fill in the template.
          </p>
        )}
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <SuggestionCard
              key={item.id}
              workspaceId={workspaceId}
              item={item}
              canDecide={canDecide}
            />
          ))}
        </ul>
      </section>
      <Customers workspaceId={workspaceId} canDecide={canDecide} />
    </div>
  );
}
