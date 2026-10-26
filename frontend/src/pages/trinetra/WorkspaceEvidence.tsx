import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BUTTON_PRIMARY, INPUT, SELECT, SURFACE } from "@/components/ui/primitives";
import {
  createTaxProfile,
  listTaxProfiles,
  createCredit,
  importReviewedStatement,
  previewReviewedStatement,
} from "@/services/api/trinetra";
import SourcePicker from "./SourcePicker";
import { rupees } from "./format";
import { errorMessage } from "@/services/api/errors";

export default function WorkspaceEvidence({ workspaceId }: { workspaceId: string }) {
  const cache = useQueryClient();
  const [tab, setTab] = useState("profile");
  const [profile, setProfile] = useState("");
  const [source, setSource] = useState("");
  const [year, setYear] = useState("2025");
  const [rows, setRows] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<{
    signature: string;
    data: Awaited<ReturnType<typeof previewReviewedStatement>>;
  } | null>(null);
  const profiles = useQuery({
    queryKey: ["trinetra", workspaceId, "profiles"],
    queryFn: () => listTaxProfiles(workspaceId),
  });
  const save = useMutation({
    mutationFn: async (form: FormData) => {
      const value = (name: string) => String(form.get(name) ?? "");
      if (tab === "profile") {
        return createTaxProfile(workspaceId, { name: value("name"), pan: value("pan") });
      }
      if (tab === "credit") {
        return createCredit(workspaceId, {
          profile_id: profile,
          work_item_id: source,
          year: Number(year),
          counterparty: value("counterparty"),
          reference: value("reference"),
          tan: value("tan"),
          amount: value("amount"),
          source_confirmation: value("reason"),
        });
      }
      const parsed = rows
        .split("\n")
        .filter((r) => r.trim())
        .map((line) => {
          const [tan, amount, reference, ...extra] = line.split(",");
          if (!tan || !amount || !reference || extra.length) {
            throw new Error("Each row needs TAN, amount and reference, separated by commas.");
          }
          return { tan: tan.trim(), amount: amount.trim(), reference: reference.trim() };
        });
      const body = {
        profile_id: profile,
        source_work_item_id: source,
        year: Number(year),
        pan: value("pan"),
        confirmed,
        rows: parsed,
      };
      const signature = JSON.stringify(body);
      if (!preview || preview.signature !== signature) {
        const data = await previewReviewedStatement(workspaceId, body);
        setPreview({ signature, data });
        return { preview: true };
      }
      return importReviewedStatement(workspaceId, {
        ...body,
        source_version: preview.data.source_version,
      });
    },
    onSuccess: (result) => {
      if ("preview" in result) {
        return;
      }
      setPreview(null);
      setConfirmed(false);
      void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
    },
  });
  return (
    <details className={`${SURFACE} p-5`}>
      <summary className="cursor-pointer font-semibold">Add reviewed evidence</summary>
      <p className="mt-3 text-sm text-muted-foreground">
        Upload source documents through Documents first. These controls record a human review; they
        do not parse or verify an official tax statement. Never enter portal credentials.
      </p>
      <label className="mt-4 block text-sm">
        Evidence task
        <select
          className={`${SELECT} mt-1`}
          value={tab}
          onChange={(e) => {
            setTab(e.target.value);
            save.reset();
          }}
        >
          <option value="profile">Legal entity profile</option>
          <option value="credit">Confirmed withholding expectation</option>
          <option value="statement">Reviewed statement transcription</option>
        </select>
      </label>
      <form
        className="mt-4 grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(new FormData(e.currentTarget));
        }}
      >
        {tab === "profile" ? (
          <>
            <label className="text-sm">
              Legal entity name
              <input required name="name" maxLength={120} className={`${INPUT} mt-1`} />
            </label>
            <label className="text-sm">
              Entity PAN
              <input
                required
                name="pan"
                autoComplete="off"
                pattern="[A-Z]{5}[0-9]{4}[A-Z]"
                maxLength={10}
                className={`${INPUT} mt-1`}
              />
            </label>
          </>
        ) : (
          <>
            <label className="text-sm">
              Legal entity
              <select
                required
                className={`${SELECT} mt-1`}
                value={profile}
                onChange={(e) => {
                  setProfile(e.target.value);
                  setConfirmed(false);
                  setPreview(null);
                }}
              >
                <option value="">Choose a profile</option>
                {profiles.data?.items.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.pan_masked}
                  </option>
                ))}
              </select>
            </label>
            <SourcePicker
              workspaceId={workspaceId}
              value={source}
              required
              onChange={(value) => {
                setSource(value);
                setConfirmed(false);
                setPreview(null);
              }}
            />
            <label className="text-sm">
              Financial / tax year starting
              <input
                required
                type="number"
                min={2000}
                max={2100}
                value={year}
                onChange={(e) => {
                  setYear(e.target.value);
                  setConfirmed(false);
                  setPreview(null);
                }}
                className={`${INPUT} mt-1`}
              />
              <span className="text-xs text-muted-foreground">
                April to March. Historical financial year and assessment year are different.
              </span>
            </label>
            {tab === "credit" ? (
              <>
                <label className="text-sm">
                  Customer
                  <input name="counterparty" required maxLength={120} className={`${INPUT} mt-1`} />
                </label>
                <label className="text-sm">
                  Invoice reference
                  <input name="reference" required maxLength={100} className={`${INPUT} mt-1`} />
                </label>
                <label className="text-sm">
                  Deductor TAN
                  <input
                    name="tan"
                    required
                    autoComplete="off"
                    pattern="[A-Z]{4}[0-9]{5}[A-Z]"
                    className={`${INPUT} mt-1`}
                  />
                </label>
                <label className="text-sm">
                  Supported expected deduction (INR)
                  <input
                    name="amount"
                    required
                    inputMode="decimal"
                    pattern="[0-9]+(\.[0-9]{1,2})?"
                    className={`${INPUT} mt-1`}
                  />
                </label>
                <label className="text-sm sm:col-span-2">
                  Evidence and reason
                  <textarea
                    name="reason"
                    required
                    minLength={10}
                    maxLength={1000}
                    className={`${INPUT} mt-1`}
                    placeholder="Identify the approved source of the expectation. A payment shortfall alone is insufficient."
                  />
                </label>
              </>
            ) : (
              <>
                <label className="text-sm">
                  Confirm source entity PAN
                  <input
                    name="pan"
                    required
                    autoComplete="off"
                    pattern="[A-Z]{5}[0-9]{4}[A-Z]"
                    className={`${INPUT} mt-1`}
                    onChange={() => setConfirmed(false)}
                  />
                </label>
                <label className="text-sm sm:col-span-2">
                  Reviewed rows: TAN, amount in INR, source reference
                  <textarea
                    required
                    rows={5}
                    maxLength={100000}
                    value={rows}
                    onChange={(e) => {
                      setRows(e.target.value);
                      setConfirmed(false);
                      setPreview(null);
                    }}
                    className={`${INPUT} mt-1`}
                  />
                  <span className="text-xs text-muted-foreground">
                    One row per posting. No currency symbols or grouping commas. At most 500 rows.
                    Unsupported official files must be reviewed outside this transcription form.
                  </span>
                </label>
                <label className="flex gap-2 text-sm sm:col-span-2">
                  <input
                    type="checkbox"
                    required
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  I checked the selected entity, year, every amount and source reference against the
                  uploaded evidence.
                </label>
              </>
            )}
          </>
        )}
        {preview && (
          <p role="status" className="sm:col-span-2 rounded border border-border p-4">
            Scope preview: {preview.data.pan_masked} · {preview.data.period} · {preview.data.rows}{" "}
            postings · {rupees(preview.data.total_micros)}. Check this scope before importing.
          </p>
        )}
        <div className="sm:col-span-2">
          <button className={BUTTON_PRIMARY} disabled={save.isPending}>
            {save.isPending
              ? "Working…"
              : tab === "statement"
                ? preview
                  ? "Import reviewed snapshot"
                  : "Preview transcription"
                : "Save reviewed evidence"}
          </button>
          {save.isSuccess && !preview && (
            <p role="status" className="mt-2 text-sm">
              Evidence saved.
            </p>
          )}
          {save.isError && (
            <p role="alert" className="mt-2 text-sm text-destructive">
              {errorMessage(save.error, "The evidence could not be saved.")}
            </p>
          )}
        </div>
      </form>
    </details>
  );
}
