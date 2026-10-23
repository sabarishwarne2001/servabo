/**
 * Where an e-invoice value came from (Final session 1, 3D, N-140).
 *
 * An Indian e-invoice carries a QR code with the supplier and buyer GSTIN, the number, the date, the value and the IRN. Servabo reads it
 * and says so: each field it supplied or checked wears "From the e-invoice QR code", the IRN has a copy button, and one line says
 * whether the code's signature was checked:
 *   - "signature not checked"      no NIC public key is configured (`EINVOICE_QR_PUBLIC_KEY_PEM`), so the code is a second opinion;
 *   - "signature checked"          the key is configured and the signature verifies, so the code's values win over the model's;
 *   - "signature does not match"   a key is configured and the signature fails, in the warning colour; the model's values stay.
 * Where the model and the code disagree both values are shown and one is marked as the one used.
 */
import React from "react";
import { AlertTriangle, Copy, QrCode, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import type { EinvoiceQr, EinvoiceSignature } from "@/types/workItem";

export const SIGNATURE_WORDS: Readonly<Record<EinvoiceSignature, string>> = {
  not_checked: "signature not checked",
  checked: "signature checked",
  does_not_match: "signature does not match",
};

const TONES: Readonly<Record<EinvoiceSignature, string>> = {
  not_checked: "border-border bg-muted/40 text-muted-foreground",
  checked: "border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  does_not_match: "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-200",
};

/** The fields this code supplied, confirmed or disagreed on. */
export const qrFields = (qr: EinvoiceQr | null | undefined): ReadonlySet<string> =>
  new Set(qr ? [...qr.filled, ...qr.confirmed, ...qr.overridden, ...qr.conflicts.map((c) => c.field)] : []);

export const QrFieldBadge: React.FC = () => (
  <span
    className="inline-flex items-center gap-0.5 rounded border border-primary/25 bg-primary/10 px-1 text-[10px] font-semibold text-primary"
    data-testid="qr-field-badge"
  >
    <QrCode className="h-2.5 w-2.5" aria-hidden />
    From the e-invoice QR code
  </span>
);

const text = (value: unknown): string => (value === null || value === undefined || value === "" ? "—" : String(value));

/** Both values where the model and the code differ. */
export const QrConflict: React.FC<{ readonly qr: EinvoiceQr; readonly field: string }> = ({ qr, field }) => {
  const conflict = qr.conflicts.find((c) => c.field === field);
  if (!conflict) {
    return null;
  }
  return (
    <span className="mt-1 block rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-[11px] leading-relaxed" data-testid="qr-conflict">
      The e-invoice QR code says <strong>{text(conflict.qr)}</strong>; the page was read as <strong>{text(conflict.model)}</strong>.{" "}
      {conflict.used === "qr" ? "The code’s value is used." : "The page’s reading is kept until the signature can be checked."}
    </span>
  );
};

export const EinvoiceQrStrip: React.FC<{ readonly qr: EinvoiceQr }> = ({ qr }) => {
  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(qr.irn);
      toast.success("IRN copied.");
    } catch {
      toast.error("The IRN could not be copied. Select it and copy it by hand.");
    }
  };
  const Icon = qr.signature === "does_not_match" ? AlertTriangle : qr.signature === "checked" ? ShieldCheck : QrCode;
  return (
    <div className="space-y-1.5 border-b border-border bg-muted/20 px-4 py-2.5 text-xs" data-testid="einvoice-qr-strip">
      <p className="flex flex-wrap items-center gap-1.5">
        <QrCode className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
        <span className="font-semibold">E-invoice QR code</span>
        <span className="text-muted-foreground">IRN</span>
        <code className="max-w-full break-all rounded bg-muted px-1.5 py-0.5 text-[11px]" data-testid="einvoice-irn">{qr.irn}</code>
        <button
          type="button"
          onClick={() => void copy()}
          aria-label="Copy the IRN"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-1.5 py-0.5 hover:bg-accent"
        >
          <Copy className="h-3 w-3" aria-hidden /> Copy
        </button>
      </p>
      <p
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold ${TONES[qr.signature]}`}
        data-testid="einvoice-signature"
        data-state={qr.signature}
      >
        <Icon className="h-3 w-3" aria-hidden />
        {SIGNATURE_WORDS[qr.signature]}
      </p>
      <p className="leading-relaxed text-muted-foreground">{qr.note}</p>
    </div>
  );
};
