/** GST Credit (docs/product/GST-CREDIT.md): the API's shapes. Amounts are micros of rupees. */

export type GstStatus =
  | "MATCHED"
  | "MATCHED_WITH_DIFFERENCES"
  | "SUGGESTED"
  | "WAITING_FOR_SUPPLIER"
  | "NOT_IN_BOOKS"
  | "NOT_ELIGIBLE"
  | "REVERSE_CHARGE"
  | "NOTE";

export type ImsAction = "ACCEPT" | "PENDING" | "REJECT";
export type GstDecisionKind = "CONFIRM" | "NOT_OURS" | "LINK";

export interface GstLaw {
  readonly section: string;
  readonly url: string;
  readonly says: string;
}

export type GstFigureKey =
  | "claimable_now"
  | "waiting"
  | "differences"
  | "at_risk_180"
  | "not_in_books"
  | "not_eligible";

export interface GstFigure {
  readonly key: GstFigureKey;
  readonly title: string;
  readonly meaning: string;
  readonly law: GstLaw;
  readonly amount_micros: number;
  readonly count: number;
  readonly suppliers?: number;
}

export interface GstSummary {
  readonly figures: readonly GstFigure[];
  readonly suggested: number;
  readonly reverse_charge: number;
  readonly notes: number;
  readonly lines: number;
  readonly currency: "INR";
  readonly disclaimer: string;
  readonly gstins: readonly string[];
  readonly periods: readonly string[];
  readonly last_import: null | {
    readonly imported_at: string;
    readonly version: string | null;
    readonly period: string;
    readonly gstin: string;
    readonly generated_on: string | null;
  };
  readonly gstin: string | null;
  readonly period: string | null;
  readonly is_sample: boolean;
  readonly access: { readonly full: boolean; readonly preview: boolean; readonly locked: readonly string[] };
  readonly tolerance_micros: number;
  readonly law: Readonly<Record<"itc" | "days_180" | "time_limit" | "ims" | "gstr2b", GstLaw>>;
}

export interface GstProblem {
  readonly code: string;
  readonly message: string;
  readonly count: number;
  readonly examples: readonly string[];
}

export interface GstImportResult {
  readonly gstin: string;
  readonly period: string;
  readonly version: string | null;
  readonly generated_on: string | null;
  readonly file_name: string;
  readonly record_count: number;
  readonly counts: Readonly<Record<string, number>>;
  readonly problems: readonly GstProblem[];
  readonly status: "IMPORTED" | "REPLACED" | "UNCHANGED";
  readonly message: string;
  readonly return_id: string;
}

export interface GstImportResponse {
  readonly results: readonly GstImportResult[];
  readonly imported: number;
  readonly unchanged: number;
}

export interface GstSupplier {
  readonly supplier_gstin: string | null;
  readonly supplier_name: string | null;
  readonly waiting_count: number;
  readonly waiting_micros: number;
  readonly oldest_waiting: string | null;
  readonly not_in_books_count: number;
  readonly differences_count: number;
  readonly suggested_count: number;
  readonly matched_count: number;
}

export interface GstSupplierPage {
  readonly total: number;
  readonly items: readonly GstSupplier[];
  readonly offset: number;
  readonly limit: number;
}

export interface GstDifference {
  readonly field: string;
  readonly label: string;
  readonly books_micros: number;
  readonly gstr2b_micros: number;
  readonly delta_micros: number;
}

export interface GstNote {
  readonly code: string;
  readonly label?: string;
  readonly books?: string;
  readonly gstr2b?: string;
  readonly detail?: string;
}

export interface GstRisk {
  readonly invoice_date: string;
  readonly reversal_date: string;
  readonly deadline_16_4: string;
  readonly paid: boolean;
  readonly paid_on: string | null;
  readonly age_days: number | null;
  readonly at_risk: boolean;
  readonly days_to_16_4: number | null;
}

export interface GstLine {
  readonly id: string;
  readonly gstin: string;
  readonly record_id: string | null;
  readonly work_item_id: string | null;
  readonly status: GstStatus;
  readonly status_text: string;
  readonly method: string | null;
  readonly supplier_gstin: string | null;
  readonly supplier_name: string | null;
  readonly number: string | null;
  readonly date: string | null;
  readonly value_micros: number | null;
  readonly tax_micros: number | null;
  readonly itc_micros: number | null;
  readonly differences: readonly GstDifference[];
  readonly notes: readonly GstNote[];
  readonly ims_action: ImsAction | null;
  readonly ims_reason: string | null;
  readonly period_first_seen: string | null;
  readonly reported_late: boolean;
  readonly decision: GstDecisionKind | null;
  readonly risk: GstRisk | null;
}

export interface GstLinePage {
  readonly total: number;
  readonly items: readonly GstLine[];
  readonly offset: number;
  readonly limit: number;
}

export interface GstBookSide {
  readonly work_item_id: string;
  readonly filename: string;
  readonly role: string;
  readonly number: string | null;
  readonly date: string | null;
  readonly supplier_name: string | null;
  readonly supplier_gstin: string | null;
  readonly taxable_micros: number | null;
  readonly igst_micros: number | null;
  readonly cgst_micros: number | null;
  readonly sgst_micros: number | null;
  readonly cess_micros: number | null;
  readonly tax_micros: number | null;
  readonly total_micros: number | null;
  readonly irn: string | null;
}

export interface GstRecordSide {
  readonly section: string;
  readonly kind: string;
  readonly period: string;
  readonly supplier_filed_on: string | null;
  readonly number: string | null;
  readonly date: string | null;
  readonly taxable_micros: number | null;
  readonly igst_micros: number;
  readonly cgst_micros: number;
  readonly sgst_micros: number;
  readonly cess_micros: number;
  readonly value_micros: number | null;
  readonly place_of_supply: string | null;
  readonly reverse_charge: boolean;
  readonly itc_available: string | null;
  readonly reason: string | null;
  readonly irn: string | null;
  readonly original_number: string | null;
}

export interface GstLineDetail extends GstLine {
  readonly books: GstBookSide | null;
  readonly gstr2b: GstRecordSide | null;
}

export interface GstReminder {
  readonly supplier_gstin: string;
  readonly supplier_name?: string;
  readonly lines: readonly { number: string; date: string; amount_micros: number; tax_micros: number }[];
  readonly subject: string | null;
  readonly text: string | null;
  readonly to: string | null;
  readonly can_send: boolean;
  readonly note: string | null;
  readonly sent?: boolean;
}

export const GST_STATUS_LABEL: Readonly<Record<GstStatus, string>> = {
  MATCHED: "Matched",
  MATCHED_WITH_DIFFERENCES: "Differences",
  SUGGESTED: "Suggested",
  WAITING_FOR_SUPPLIER: "Waiting for supplier",
  NOT_IN_BOOKS: "Not in your books",
  NOT_ELIGIBLE: "Not eligible",
  REVERSE_CHARGE: "Reverse charge",
  NOTE: "Credit/debit note",
};

export const IMS_LABEL: Readonly<Record<ImsAction, string>> = {
  ACCEPT: "Accept",
  PENDING: "Keep pending",
  REJECT: "Reject",
};
