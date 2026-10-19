import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Download, Loader2 } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { downloadValueReceiptPdf, getValueReceipt } from "@/services/api/valueReceipt";
import { valueReceiptKeys } from "@/services/api/queryKeys";
import { formatNumber } from "@/utils/displayTime";
import type { ReceiptFinding, ReceiptHonesty, ReceiptPeriod, ValueReceipt as ValueReceiptData } from "@/types/valueReceipt";

/**
 * Session G — the value receipt: real figures from the customer's own documents, written by the server (rupees in
 * Indian grouping, N-112), shown where a purchase is decided and every month after. Nothing here computes or
 * estimates a figure; a finding that is zero or was not computed never reaches the screen.
 */

/** Owners, admins and the billing role read the receipt; the server refuses everyone else. */
export const canSeeValueReceipt = (role: string | null | undefined): boolean => {
  const upper = String(role ?? "").toUpperCase();
  return upper === "OWNER" || upper === "ADMIN" || upper === "BILLING";
};

export const useValueReceipt = (organizationId: string, period: ReceiptPeriod, enabled = true) =>
  useQuery({
    queryKey: valueReceiptKeys.period(organizationId, period),
    queryFn: () => getValueReceipt(organizationId, period),
    enabled: enabled && Boolean(organizationId),
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

const HONESTY_WORDS: Readonly<Record<ReceiptHonesty, string>> = {
  confirmed: "Confirmed",
  likely: "Likely",
  potential: "Potential",
};

/** "132 documents · 410 pages · 18 assistant answers", leaving out what is zero. */
export const workLine = (receipt: ValueReceiptData): string => {
  const { documents, pages, assistant_answers: answers } = receipt.work;
  const parts = [
    documents > 0 ? `${formatNumber(documents)} ${documents === 1 ? "document" : "documents"} read` : "",
    pages > 0 ? `${formatNumber(pages)} ${pages === 1 ? "page" : "pages"}` : "",
    answers > 0 ? `${formatNumber(answers)} assistant ${answers === 1 ? "answer" : "answers"}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
};

export interface DownloadReceiptPdfProps {
  readonly organizationId: string;
  readonly period: ReceiptPeriod;
  readonly testId: string;
}

/** "Download as PDF": the one-page receipt, to justify the purchase. Fetched as a blob so the request is authorised. */
export const DownloadReceiptPdf: React.FC<DownloadReceiptPdfProps> = ({ organizationId, period, testId }) => {
  const pdf = useMutation({
    mutationFn: () => downloadValueReceiptPdf(organizationId, period),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `servabo-value-receipt-${period}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: () => toast.error("The PDF could not be made. Try again in a moment."),
  });
  return (
    <button
      type="button"
      onClick={() => pdf.mutate()}
      disabled={pdf.isPending}
      data-testid={testId}
      className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline disabled:opacity-60 dark:text-[hsl(var(--primary-on-dark))]"
    >
      {pdf.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Download className="h-3.5 w-3.5" aria-hidden />}
      Download as PDF
    </button>
  );
};

export interface ReceiptFindingsProps {
  readonly findings: readonly ReceiptFinding[];
  readonly onNavigate?: (() => void) | undefined;
  readonly testId: string;
}

export const ReceiptFindings: React.FC<ReceiptFindingsProps> = ({ findings, onNavigate, testId }) => (
  <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid={`${testId}-findings`}>
    {findings.map((finding) => (
      <li
        key={finding.key}
        data-testid={`value-receipt-finding-${finding.key}`}
        className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-3.5 py-2.5"
      >
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-foreground">{finding.label}</p>
          {finding.honesty ? (
            <span className="mt-1 inline-block rounded-full border border-border-strong/60 bg-muted/60 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
              {HONESTY_WORDS[finding.honesty]}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-baseline gap-3">
          {finding.amount_text ? (
            <span className="fp-num text-sm font-semibold text-foreground" data-testid={`value-receipt-amount-${finding.key}`}>
              {finding.amount_text}
            </span>
          ) : null}
          <Link
            to={finding.source}
            onClick={onNavigate}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline dark:text-[hsl(var(--primary-on-dark))]"
          >
            See the evidence <ArrowRight className="h-3 w-3" aria-hidden />
            <span className="sr-only"> for {finding.label}</span>
          </Link>
        </div>
      </li>
    ))}
  </ul>
);

export interface ReceiptBodyProps {
  readonly receipt: ValueReceiptData;
  /** How many findings to show; the rest are on their pages. */
  readonly maxFindings: number;
  readonly onNavigate?: (() => void) | undefined;
  readonly testId: string;
  /** Extra controls under the findings (the PDF link). */
  readonly footer?: React.ReactNode;
}

/** The headline, the findings with their links, and what Business also checks. Nothing when there is nothing. */
export const ReceiptBody: React.FC<ReceiptBodyProps> = ({ receipt, maxFindings, onNavigate, testId, footer }) => {
  const shown = receipt.found.slice(0, maxFindings);
  return (
    <div className="space-y-3" data-testid={testId}>
      {receipt.headline ? (
        <p className="text-sm font-medium leading-relaxed text-foreground" data-testid={`${testId}-headline`}>
          {receipt.headline}
        </p>
      ) : null}
      {shown.length > 0 ? <ReceiptFindings findings={shown} onNavigate={onNavigate} testId={testId} /> : null}
      {receipt.found.length > shown.length ? (
        <p className="text-xs text-muted-foreground">
          {receipt.found.length - shown.length} more {receipt.found.length - shown.length === 1 ? "finding" : "findings"} on their pages.
        </p>
      ) : null}
      {receipt.also_on_business.length > 0 ? (
        <p className="text-xs leading-relaxed text-muted-foreground" data-testid={`${testId}-business`}>
          Business also checks: {receipt.also_on_business.join(", ")}.
        </p>
      ) : null}
      {footer}
    </div>
  );
};

export interface ReceiptCardProps {
  readonly organizationId: string;
  readonly period: ReceiptPeriod;
  readonly title: string;
  readonly testId: string;
  readonly enabled?: boolean;
  readonly maxFindings?: number;
  /** Shown instead of the card when there is nothing to say; the default is one quiet line under the work counts. */
  readonly quietLine?: string;
}

/**
 * A card for the Overview and the plan page. While loading, on an error or for a role that may not read it, it
 * renders nothing: the page it sits on works without it.
 */
export const ReceiptCard: React.FC<ReceiptCardProps> = ({
  organizationId,
  period,
  title,
  testId,
  enabled = true,
  maxFindings = 6,
  quietLine = "Nothing to report yet. Upload invoices and import your GSTR-2B and Servabo will show what it finds here.",
}) => {
  const { data: receipt } = useValueReceipt(organizationId, period, enabled);
  if (!receipt) {
    return null;
  }
  const work = workLine(receipt);
  const hasFindings = receipt.found.length > 0;
  return (
    <section aria-labelledby={`${testId}-title`} className="fp-card p-5" data-testid={testId}>
      <h2 id={`${testId}-title`} className="text-[15px] font-semibold tracking-tight">
        {title}
      </h2>
      {hasFindings ? (
        <div className="mt-3">
          <ReceiptBody receipt={receipt} maxFindings={maxFindings} testId={`${testId}-body`} />
        </div>
      ) : (
        <div className="mt-2 space-y-1">
          {work ? <p className="text-sm text-foreground" data-testid={`${testId}-work`}>{work}</p> : null}
          <p className="text-[13px] text-muted-foreground" data-testid={`${testId}-quiet`}>{quietLine}</p>
          {receipt.also_on_business.length > 0 ? (
            <p className="text-xs leading-relaxed text-muted-foreground" data-testid={`${testId}-body-business`}>
              Business also checks: {receipt.also_on_business.join(", ")}.
            </p>
          ) : null}
        </div>
      )}
      {hasFindings && work ? <p className="mt-3 text-xs text-muted-foreground" data-testid={`${testId}-work`}>{work}</p> : null}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">{receipt.note}</p>
        <DownloadReceiptPdf organizationId={organizationId} period={period} testId={`${testId}-pdf`} />
      </div>
    </section>
  );
};
