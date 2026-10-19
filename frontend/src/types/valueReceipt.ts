/** Session G — the value receipt: what Servabo found in the organization's own documents, in its own money. */

export type ReceiptPeriod = "trial" | "month";
export type ReceiptHonesty = "confirmed" | "likely" | "potential";

export interface ReceiptFinding {
  readonly key: string;
  /** A plain-English line, e.g. "GST credit waiting on 6 suppliers". */
  readonly label: string;
  /** The amount as the server writes it: "₹2,40,000" (rupees in Indian grouping), "$1,234". Null for a count. */
  readonly amount_text: string | null;
  readonly amount_micros: number | null;
  readonly currency: string | null;
  readonly count: number | null;
  /** The app path of the page that holds the evidence. */
  readonly source: string;
  readonly honesty: ReceiptHonesty | null;
}

export interface ReceiptWork {
  readonly documents: number;
  readonly pages: number;
  readonly assistant_answers: number;
}

export interface ValueReceipt {
  readonly organization_id: string;
  readonly organization_name: string;
  readonly period: ReceiptPeriod;
  readonly period_start: string;
  readonly period_end: string;
  readonly timezone: string;
  readonly work: ReceiptWork;
  readonly found: readonly ReceiptFinding[];
  /** One sentence; null when there is nothing to say. */
  readonly headline: string | null;
  /** For an organization below Business: the names of the checks Business adds. Names only. */
  readonly also_on_business: readonly string[];
  readonly note: string;
}
