import React, { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { periodLabel } from "@/components/gst/gstFormat";
import { BUTTON_PRIMARY, HINT, SURFACE } from "@/components/ui/primitives";
import { errorMessage } from "@/services/api/errors";
import { importGstReturn } from "@/services/api/gst";
import { gstKeys } from "@/services/api/queryKeys";
import type { GstImportResponse, GstImportResult } from "@/types/gst";

const SECTION_LABEL: Readonly<Record<string, string>> = {
  b2b: "invoices (B2B)", b2ba: "amended invoices", cdnr: "credit/debit notes", cdnra: "amended notes",
  isd: "ISD", isda: "ISD amendments", impg: "imports of goods", impgsez: "SEZ imports", ecom: "e-commerce",
  ecoma: "e-commerce amendments",
};

export const ImportResult: React.FC<{ readonly result: GstImportResult }> = ({ result }) => (
  <li className="rounded-lg border border-border/70 bg-muted/30 p-3 text-sm" data-testid="gst-import-result">
    <p className="font-medium text-foreground">
      {result.status === "UNCHANGED"
        ? `${periodLabel(result.period)}: this exact file was already imported, nothing changed.`
        : `${periodLabel(result.period)} for ${result.gstin}: ${result.record_count} record${result.record_count === 1 ? "" : "s"} ${
            result.status === "REPLACED" ? "(replaces the earlier import of this period)" : "imported"
          }.`}
    </p>
    <p className={HINT}>
      {Object.entries(result.counts).map(([section, n]) => `${n} ${SECTION_LABEL[section] ?? section}`).join(" · ") || "No records"}
      {result.version ? ` · version ${result.version}` : ""}
    </p>
    {result.problems.length > 0 ? (
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-amber-700 dark:text-amber-300" aria-label="Problems found">
        {result.problems.map((problem) => (
          <li key={problem.code}>
            {problem.message}
            {problem.examples.length ? ` (for example ${problem.examples.slice(0, 3).join(", ")})` : ""}
          </li>
        ))}
      </ul>
    ) : null}
  </li>
);

/** "Import GSTR-2B": a drop zone for .json and .zip, with the outcome in words. */
export const GstImport: React.FC<{ readonly workspaceId: string; readonly disabledReason?: string | null }> = ({
  workspaceId,
  disabledReason = null,
}) => {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [response, setResponse] = useState<GstImportResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (file: File) => importGstReturn(workspaceId, file),
    onSuccess: (data) => {
      setResponse(data);
      setFailure(null);
      void queryClient.invalidateQueries({ queryKey: gstKeys.all(workspaceId) });
      toast.success(data.imported > 0 ? "GSTR-2B imported." : "Nothing new in that file.");
    },
    onError: (error) => {
      setResponse(null);
      setFailure(errorMessage(error, "The file could not be imported."));
    },
  });

  const pick = (files: FileList | null): void => {
    const file = files?.[0];
    if (file) {upload.mutate(file);}
  };

  return (
    <section className={`${SURFACE} space-y-3 p-4`} aria-labelledby="gst-import-title" data-testid="gst-import">
      <h2 id="gst-import-title" className="text-[15px] font-semibold text-foreground">
        Import GSTR-2B
      </h2>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          if (!disabledReason) {pick(event.dataTransfer.files);}
        }}
        className={`flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-6 text-center transition ${
          over ? "border-primary bg-primary/5" : "border-border-strong/70"
        }`}
      >
        {upload.isPending ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
        ) : (
          <FileUp className="h-5 w-5 text-muted-foreground" aria-hidden />
        )}
        <p className="text-sm text-foreground">Drop the GSTR-2B file here (.json, or a .zip holding it)</p>
        <input
          ref={input}
          type="file"
          accept=".json,.zip,application/json,application/zip"
          className="sr-only"
          aria-label="GSTR-2B file"
          data-testid="gst-import-input"
          disabled={Boolean(disabledReason) || upload.isPending}
          onChange={(event) => {
            pick(event.target.files);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className={BUTTON_PRIMARY}
          disabled={Boolean(disabledReason) || upload.isPending}
          onClick={() => input.current?.click()}
        >
          {upload.isPending ? "Reading…" : "Choose a file"}
        </button>
        {disabledReason ? <p className={HINT}>{disabledReason}</p> : null}
      </div>
      <div aria-live="polite">
        {failure ? (
          <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive dark:text-red-300" data-testid="gst-import-error">
            {failure}
          </p>
        ) : null}
        {response ? (
          <ul className="space-y-2" aria-label="Import result">
            {response.results.map((result) => (
              <ImportResult key={result.return_id} result={result} />
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
};

export default GstImport;
