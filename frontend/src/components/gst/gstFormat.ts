/**
 * GST Credit's display helpers. Rupees use Indian grouping here, as in Helm (N-137, extends N-112): 12,34,567.
 * Plain TypeScript, no React.
 */
import { formatHelmMoney } from "@/components/helm/money";
import { formatCalendarDate } from "@/utils/displayTime";
import type { GstStatus } from "@/types/gst";
import type { StatusTone } from "@/components/ui/StatusPill";

export const rupees = (micros: number | null | undefined): string => formatHelmMoney(micros, "INR");

export const signedRupees = (micros: number | null | undefined): string =>
  formatHelmMoney(micros, "INR", { signed: true });

export const day = (iso: string | null | undefined): string => formatCalendarDate(iso);

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"] as const;

/** "2026-09" -> "September 2026". */
export const periodLabel = (period: string | null | undefined): string => {
  if (!period) {return "All periods";}
  const [year, month] = period.split("-").map((part) => Number.parseInt(part, 10));
  const name = month ? MONTHS[month - 1] : undefined;
  return year && name ? `${name} ${year}` : period;
};

export const statusTone = (status: GstStatus): StatusTone => {
  switch (status) {
    case "MATCHED":
      return "ok";
    case "MATCHED_WITH_DIFFERENCES":
    case "WAITING_FOR_SUPPLIER":
    case "SUGGESTED":
      return "warn";
    case "NOT_IN_BOOKS":
      return "danger";
    default:
      return "neutral";
  }
};

export const gstinShort = (gstin: string | null | undefined): string => gstin ?? "no GSTIN";

export const runGstFormatSelfCheck = (): string[] => {
  const failures: string[] = [];
  const expect = (label: string, actual: string, wanted: string): void => {
    if (actual !== wanted) {failures.push(`${label}: got ${JSON.stringify(actual)}, wanted ${JSON.stringify(wanted)}`);}
  };
  expect("rupees in lakh grouping", rupees(1_234_567_890_000), "₹12,34,567.89");
  expect("a signed credit note", signedRupees(-18_000_000), "-₹18.00");
  expect("nothing stays a dash", rupees(null), "—");
  expect("a period in words", periodLabel("2026-09"), "September 2026");
  expect("no period", periodLabel(null), "All periods");
  return failures;
};
