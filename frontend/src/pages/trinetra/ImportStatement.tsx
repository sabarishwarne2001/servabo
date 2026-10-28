import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  INPUT,
  SELECT,
  SURFACE,
} from "@/components/ui/primitives";
import { ApiError, errorMessage } from "@/services/api/errors";
import {
  importStatementFile,
  listTaxProfiles,
  previewStatementFile,
  statementTemplate,
  type FilePreview,
  type TrinetraAccess,
} from "@/services/api/trinetra";
import { saveBlob } from "./download";
import { rupees } from "./format";

/** What an AIS column can mean, in the words the reviewer picks from (the server's own roles). */
export const AIS_ROLES: readonly (readonly [string, string])[] = [
  ["source", "Deductor name (and TAN)"],
  ["tan", "Deductor TAN"],
  ["code", "Information code (section or table item)"],
  ["description", "Description"],
  ["date", "Transaction date"],
  ["paid", "Amount paid or credited"],
  ["deducted", "Tax amount (used for matching)"],
  ["status", "Booking status"],
];

interface AisColumns {
  proposed: Record<string, number | null>;
  chosen: Record<string, number | null>;
  columns: string[];
}

const asColumns = (raw: unknown): AisColumns | null => {
  const value = raw as Partial<AisColumns> | null | undefined;
  return value && Array.isArray(value.columns) && value.chosen ? (value as AisColumns) : null;
};

/** The columns the reviewer may choose from: from the preview, or from a refusal that asked for the choice. */
const columnsOf = (preview: FilePreview | null, error: unknown): AisColumns | null => {
  if (preview) {
    return asColumns(preview.columns);
  }
  return error instanceof ApiError && error.code === "TRINETRA_AMBIGUOUS_COLUMNS"
    ? asColumns(error.details.columns)
    : null;
};

const toMapping = (
  chosen: Record<string, number | null>,
  picked: Record<string, string>,
): Record<string, number | null> => ({
  ...chosen,
  ...Object.fromEntries(
    Object.entries(picked).map(([role, index]) => [role, index === "" ? null : Number(index)]),
  ),
});

/** Statements without typing: the Servabo template, a Form 26AS / Form 168 text file or an AIS CSV. Preview first; nothing is saved until the reviewer confirms. */
export default function ImportStatement({
  workspaceId,
  access,
}: {
  workspaceId: string;
  access: TrinetraAccess;
}) {
  const cache = useQueryClient();
  const profiles = useQuery({
    queryKey: ["trinetra", workspaceId, "profiles"],
    queryFn: () => listTaxProfiles(workspaceId),
  });
  const [profile, setProfile] = useState("");
  const [year, setYear] = useState("2025");
  const [pan, setPan] = useState("");
  const [reader, setReader] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [refusal, setRefusal] = useState<unknown>(null);
  const columns = columnsOf(preview, refusal);
  const input = () =>
    file && profile
      ? {
          file,
          profileId: profile,
          year: Number(year),
          pan,
          ...(reader ? { reader } : {}),
          ...(Object.keys(mapping).length && columns
            ? { mapping: toMapping(columns.chosen, mapping) }
            : {}),
        }
      : null;
  const forget = () => {
    setPreview(null);
    setConfirmed(false);
  };
  const check = useMutation({
    mutationFn: async () => {
      const body = input();
      if (!body) {
        throw new Error("Choose the legal entity and the file first.");
      }
      return previewStatementFile(workspaceId, body);
    },
    onSuccess: (data) => {
      setPreview(data);
      setRefusal(null);
      setConfirmed(false);
    },
    onError: (error) => {
      setPreview(null);
      setRefusal(error);
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      const body = input();
      if (!body || !preview) {
        throw new Error("Preview the file first.");
      }
      return importStatementFile(workspaceId, { ...body, expectedSha256: preview.sha256 });
    },
    onSuccess: () => {
      forget();
      setFile(null);
      void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
    },
  });
  const template = useMutation({
    mutationFn: async (format: "csv" | "xlsx") =>
      saveBlob(
        await statementTemplate(workspaceId, format),
        `servabo-statement-template.${format}`,
      ),
  });
  const ais = columns;
  const failed = preview
    ? preview.checks.some((c) => !c.ok) || preview.file_pan_matches === false
    : false;
  return (
    <section
      className={`${SURFACE} space-y-4 p-5`}
      aria-labelledby="import-statement"
      data-testid="trinetra-import"
    >
      <div>
        <h2 id="import-statement" className="font-semibold">
          Import your tax statement
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Fill in the Servabo template, or upload the text of Form 26AS or Form 168, or an AIS CSV.
          You see everything Servabo read before anything is saved. Never enter portal credentials;
          Servabo never logs in to the tax portal for you.
        </p>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="Servabo template">
        {(["csv", "xlsx"] as const).map((format) => (
          <button
            key={format}
            type="button"
            className={BUTTON_SECONDARY}
            disabled={template.isPending}
            onClick={() => template.mutate(format)}
          >
            Download the template ({format.toUpperCase()})
          </button>
        ))}
      </div>
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          check.mutate();
        }}
      >
        <label className="text-sm">
          Legal entity
          <select
            required
            className={`${SELECT} mt-1`}
            value={profile}
            onChange={(e) => {
              setProfile(e.target.value);
              forget();
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
        <label className="text-sm">
          Tax year starting
          <input
            required
            type="number"
            min={2000}
            max={2100}
            value={year}
            className={`${INPUT} mt-1`}
            onChange={(e) => {
              setYear(e.target.value);
              forget();
            }}
          />
          <span className="text-xs text-muted-foreground">
            April to March. The file's own label is shown back to you as it states it.
          </span>
        </label>
        <label className="text-sm">
          Confirm the entity's PAN
          <input
            required
            autoComplete="off"
            pattern="[A-Z]{5}[0-9]{4}[A-Z]"
            maxLength={10}
            className={`${INPUT} mt-1`}
            value={pan}
            onChange={(e) => {
              setPan(e.target.value.toUpperCase());
              forget();
            }}
          />
        </label>
        <label className="text-sm">
          How to read it
          <select
            className={`${SELECT} mt-1`}
            value={reader}
            onChange={(e) => {
              setReader(e.target.value);
              setMapping({});
              forget();
            }}
          >
            <option value="">Detect from the file</option>
            {access.statement_readers
              .filter((r) => r.key !== "human-transcription-v1")
              .map((r) => (
                <option key={r.key} value={r.key}>
                  {r.label}
                  {r.official && !r.verified ? " (unverified)" : ""}
                </option>
              ))}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          The file (CSV, Excel or the text download)
          <input
            required
            type="file"
            accept=".csv,.xlsx,.txt,text/csv,text/plain"
            className={`${INPUT} mt-1`}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setMapping({});
              forget();
            }}
          />
        </label>
        <div className="sm:col-span-2">
          <button className={BUTTON_SECONDARY} disabled={check.isPending || !file || !profile}>
            {check.isPending ? "Reading…" : "Preview what the file says"}
          </button>
        </div>
      </form>
      {check.isError && (
        <p role="alert" className="text-sm text-destructive" data-testid="trinetra-import-error">
          {errorMessage(check.error, "The file could not be read.")}
        </p>
      )}
      {ais && (
        <div className="space-y-2" data-testid="trinetra-import-mapping">
          <p className="text-sm font-medium">Which column means what</p>
          <p className="text-xs text-muted-foreground">
            Servabo found these by heading. Change any that are wrong, then preview again.
          </p>
          <table className="w-full text-sm">
            <thead className="sr-only">
              <tr>
                <th scope="col">Meaning</th>
                <th scope="col">Column in your file</th>
              </tr>
            </thead>
            <tbody>
              {AIS_ROLES.map(([role, label]) => (
                <tr key={role}>
                  <th scope="row" className="w-1/2 py-1 pr-3 text-left font-normal">
                    {label}
                  </th>
                  <td>
                    <select
                      aria-label={`Column for ${label}`}
                      className={SELECT}
                      value={mapping[role] ?? String(ais.chosen[role] ?? "")}
                      onChange={(e) => setMapping({ ...mapping, [role]: e.target.value })}
                    >
                      <option value="">Not in this file</option>
                      {ais.columns.map((name, index) => (
                        <option key={index} value={String(index)}>
                          {name || `Column ${index + 1}`}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            className={BUTTON_SECONDARY}
            disabled={check.isPending}
            onClick={() => check.mutate()}
          >
            Preview again with this mapping
          </button>
        </div>
      )}

      {preview && (
        <div
          className="space-y-4 rounded-lg border border-border p-4"
          role="region"
          aria-label="Preview of the statement"
          data-testid="trinetra-import-preview"
        >
          <div>
            <p className="font-medium">{preview.reader_label}</p>
            <p
              className={`mt-1 text-sm ${preview.official && !preview.verified ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"}`}
              data-testid="trinetra-import-notice"
            >
              {preview.notice}
            </p>
          </div>
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Rows read</dt>
              <dd className="font-medium">{preview.rows}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Tax amount in all</dt>
              <dd className="font-medium tabular-nums">{rupees(preview.total_micros)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">The file says its tax year is</dt>
              <dd className="font-medium">{preview.tax_year_label ?? "Not stated"}</dd>
            </div>
          </dl>
          {!preview.year_matches && (
            <p role="alert" className="text-sm text-destructive">
              The file's tax-year label does not match the year you chose ({year}). Years are never
              mixed or converted.
            </p>
          )}
          {preview.file_pan_matches === false && (
            <p role="alert" className="text-sm text-destructive">
              The PAN printed in the file is not this legal entity's. Nothing can be imported.
            </p>
          )}
          <ul className="space-y-1 text-sm" aria-label="Checks against the file's own totals">
            {preview.checks.map((c) => (
              <li key={c.name} data-ok={String(c.ok)}>
                <span className="font-medium">{c.ok ? "Passed" : "Failed"}:</span> {c.name}.{" "}
                {c.detail}
              </li>
            ))}
          </ul>
          {preview.ignored.length > 0 && (
            <p className="text-sm text-muted-foreground">Left out: {preview.ignored.join("; ")}.</p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="mb-1 text-left text-xs text-muted-foreground">
                Each deductor, with its TAN masked
              </caption>
              <thead>
                <tr>
                  <th className="pr-3">Deductor TAN</th>
                  <th className="pr-3">Rows</th>
                  <th>Tax amount</th>
                </tr>
              </thead>
              <tbody>
                {preview.deductors.map((d) => (
                  <tr key={d.tan_masked}>
                    <td className="pr-3 font-mono">{d.tan_masked}</td>
                    <td className="pr-3">{d.rows}</td>
                    <td className="tabular-nums">{rupees(d.total_micros)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              First {preview.sample.length} rows, as read
            </summary>
            <ol className="mt-2 space-y-1 text-xs">
              {preview.sample.map((r) => (
                <li key={r.line_no}>
                  Line {r.line_no} · {r.tan_masked} · {r.section ?? "no section printed"} ·{" "}
                  {r.on ?? "no date printed"} · {r.status ?? "no status"} ·{" "}
                  {rupees(r.amount_micros)}
                </li>
              ))}
            </ol>
          </details>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              required
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I checked the legal entity, the year, the rows and the amounts against the statement I
            hold.
          </label>
          <button
            type="button"
            className={BUTTON_PRIMARY}
            disabled={!confirmed || failed || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Importing…" : "Import this statement"}
          </button>
        </div>
      )}
      {save.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(save.error, "The statement could not be imported.")}
        </p>
      )}
      {save.isSuccess && !preview && (
        <p role="status" className="text-sm" data-testid="trinetra-import-done">
          Statement imported. Your cases were compared with it again.
        </p>
      )}
    </section>
  );
}
