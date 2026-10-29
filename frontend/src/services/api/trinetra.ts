import { apiClient } from "@/services/api/client";

export interface CreditCase {
  id: string;
  profile_id?: string | null;
  review_state?: string;
  gross_micros?: string | null;
  adjusted_gross_micros?: string | null;
  credit_notes_micros?: string;
  advice_micros?: string | null;
  booked_micros?: string | null;
  basis_micros?: string | null;
  basis_source?: string | null;
  statement_reader?: { key: string; label: string; official: boolean; verified: boolean } | null;
  counterparty: string;
  reference: string;
  period?: string;
  year: number;
  status: string;
  revision: number;
  source_current: boolean;
  statement_work_item_id?: string;
  age_days: number;
  review?: {
    owner_id?: string;
    priority?: string;
    root_cause?: string;
    due_on?: string;
    withholding_confirmed?: boolean;
    seller_name_confirmed?: boolean;
    annotations?: { text: string; by: string; at: string; reason: string }[];
    evidence?: {
      work_item_id: string;
      kind: string;
      current: boolean;
      amount_micros?: string | number | null;
    }[];
  };
  expected_micros: string | null;
  posted_micros: string;
  gap_micros: string | null;
  bank_micros: string | null;
  note: string;
  rule_version: string;
  work_item_id?: string;
  as_of: string | null;
}
export interface Cockpit {
  outcomes?: {
    confirmed_gap_closure_micros: string;
    confirmed_cases: number;
    review_minutes: number;
    note: string;
    now_visible_this_month_micros?: string;
    now_visible_this_year_micros?: string;
    now_visible_total_micros?: string;
    now_visible_cases?: number;
    ledger_note?: string;
    measured_cycle_cases?: number;
    measured_cycle_days_median?: number | null;
    measured_cycle_days_mean?: number | null;
    cycle_note?: string;
  };
  is_sample: boolean;
  items: CreditCase[];
  total: number;
  expected_micros: string;
  posted_micros: string;
  gap_micros: string;
  unresolved: number;
  note: string;
  as_of: string | null;
}
const base = (id: string) => `/workspaces/${encodeURIComponent(id)}/trinetra`;
/** How a statement can be read without typing it: the Servabo template, or an official layout that is verified or not yet. */
export interface StatementReader {
  key: string;
  label: string;
  official: boolean;
  verified: boolean;
}
/** Why live TRINETRA is not open for this organization, in the server's words: "off", "not_enrolled" or "not_entitled". */
export interface TrinetraAccess {
  live_enabled: boolean;
  mode: "off" | "pilot" | "on" | string;
  enrolled: boolean;
  enrolled_since?: string | null;
  entitled: boolean;
  official_formats: string[];
  statement_readers: StatementReader[];
}
export const getTrinetraAccess = async (id: string): Promise<TrinetraAccess> =>
  (await apiClient.get(`${base(id)}/access`)).data;
export const getTrinetraCockpit = async (id: string, sample: boolean): Promise<Cockpit> =>
  (await apiClient.get(`${base(id)}/${sample ? "sample" : "summary"}`)).data;
export interface TaxProfile {
  id: string;
  name: string;
  pan_masked: string;
}
export interface MatchCheck {
  key: "deductor" | "entity_and_year" | "section" | "amount" | "reference" | string;
  label: string;
  case_value: string | null;
  statement_value: string | null;
  /** True, false, or null when one side prints nothing (never called a difference). */
  agrees: boolean | null;
  note: string;
}
export interface MatchExplanation {
  snapshot_id: string;
  line_id: string;
  role: "candidate" | "allocated";
  allocated_micros: string | null;
  reader: string | null;
  reader_verified: boolean;
  rule_version: string;
  checks: MatchCheck[];
}
export interface CaseDetail extends CreditCase {
  match_explanations?: MatchExplanation[];
  events_total?: number;
  printed_evidence: {
    amount_micros: string | null;
    deductor_tan_masked: string | null;
    section_label: string | null;
    note: string;
  };
  cash_projection: {
    status: string;
    cash_received_micros: string | null;
    reviewed_withholding_micros: string | null;
    unexplained_micros: string | null;
    overexplained_micros: string | null;
    note: string;
  };
  statement_lines: {
    id: string;
    snapshot_id: string;
    amount_micros: string;
    available_micros: string;
  }[];
  bank_evidence: { id: string; amount_micros: string; on: string }[];
  events: {
    revision: number;
    action: string;
    reason: string;
    at: string;
    actor_id: string | null;
    review_minutes?: number;
  }[];
}
export const listTaxProfiles = async (id: string): Promise<{ items: TaxProfile[] }> =>
  (await apiClient.get(`${base(id)}/profiles`)).data;
export const createTaxProfile = async (
  id: string,
  body: { name: string; pan: string },
): Promise<TaxProfile> => (await apiClient.post(`${base(id)}/profiles`, body)).data;
export const createCredit = async (
  id: string,
  body: Record<string, unknown>,
): Promise<CreditCase> => (await apiClient.post(`${base(id)}/credits`, body)).data;
export const importReviewedStatement = async (
  id: string,
  body: Record<string, unknown>,
): Promise<{ id: string }> => (await apiClient.post(`${base(id)}/reviewed-statements`, body)).data;
export const getCreditDetail = async (id: string, credit: string): Promise<CaseDetail> =>
  (await apiClient.get(`${base(id)}/credits/${encodeURIComponent(credit)}`)).data;
export const decideCredit = async (
  id: string,
  credit: string,
  body: Record<string, unknown>,
): Promise<CreditCase> =>
  (await apiClient.post(`${base(id)}/credits/${encodeURIComponent(credit)}/decisions`, body)).data;
export const getInquiryDraft = async (
  id: string,
  credit: string,
): Promise<{ subject: string; body: string }> =>
  (await apiClient.get(`${base(id)}/credits/${encodeURIComponent(credit)}/inquiry-draft`)).data;
export const exportCreditCases = async (id: string): Promise<Blob> =>
  (await apiClient.get(`${base(id)}/export.csv`, { responseType: "blob" })).data;

export const reconfirmCredit = async (
  id: string,
  credit: string,
  body: Record<string, unknown>,
): Promise<CreditCase> =>
  (await apiClient.post(`${base(id)}/credits/${encodeURIComponent(credit)}/reconfirm`, body)).data;
export const updateCreditReview = async (
  id: string,
  credit: string,
  body: Record<string, unknown>,
): Promise<CreditCase> =>
  (await apiClient.post(`${base(id)}/credits/${encodeURIComponent(credit)}/review`, body)).data;
export const downloadDossier = async (id: string, format: "csv" | "xlsx" | "html"): Promise<Blob> =>
  (await apiClient.get(`${base(id)}/export.${format}`, { responseType: "blob" })).data;
export const previewReviewedStatement = async (
  id: string,
  body: Record<string, unknown>,
): Promise<{
  period: string;
  pan_masked: string;
  rows: number;
  total_micros: string;
  source_version: string;
}> => (await apiClient.post(`${base(id)}/reviewed-statements/preview`, body)).data;

// ------------------------------------------------------------------------------------------------ statements without typing

export interface FilePreview {
  reader: string;
  reader_label: string;
  official: boolean;
  verified: boolean;
  parser_version: string;
  sha256: string;
  tax_year_label: string | null;
  tax_year_kind: string | null;
  year: number;
  year_matches: boolean;
  file_pan_matches: boolean | null;
  rows: number;
  total_micros: string;
  deductors: { tan_masked: string; rows: number; total_micros: string }[];
  mapping: { column: string; meaning: string }[];
  columns: Record<string, unknown> | null;
  checks: { name: string; ok: boolean; detail: string }[];
  ignored: string[];
  sample: {
    line_no: number;
    tan_masked: string;
    section: string | null;
    on: string | null;
    status: string | null;
    amount_micros: string;
  }[];
  notice: string;
}
export interface StatementFileInput {
  file: File;
  profileId: string;
  year: number;
  pan: string;
  reader?: string | undefined;
  /** Which column (by position) means what, for an AIS file the reviewer is correcting: {role: column index or null}. */
  mapping?: Record<string, number | null> | undefined;
}
const statementForm = (input: StatementFileInput): FormData => {
  const form = new FormData();
  form.set("file", input.file);
  form.set("profile_id", input.profileId);
  form.set("year", String(input.year));
  form.set("pan", input.pan);
  if (input.reader) {
    form.set("reader", input.reader);
  }
  if (input.mapping) {
    form.set("mapping", JSON.stringify(input.mapping));
  }
  return form;
};
export const previewStatementFile = async (
  id: string,
  input: StatementFileInput,
): Promise<FilePreview> =>
  (await apiClient.post(`${base(id)}/statement-files/preview`, statementForm(input))).data;
export const importStatementFile = async (
  id: string,
  input: StatementFileInput & { expectedSha256: string },
): Promise<{ id: string; revision: number; active: boolean }> => {
  const form = statementForm(input);
  form.set("confirmed", "true");
  form.set("expected_sha256", input.expectedSha256);
  return (await apiClient.post(`${base(id)}/statement-files`, form)).data;
};
export const statementTemplate = async (id: string, format: "csv" | "xlsx"): Promise<Blob> =>
  (await apiClient.get(`${base(id)}/statement-template.${format}`, { responseType: "blob" })).data;

// ------------------------------------------------------------------------------------------------ suggestions and customers

export interface Suggestion {
  id: string;
  profile_id: string;
  work_item_id: string;
  year: number;
  source: "PRINTED_HINT" | "TEMPLATE" | "ZOHO" | string;
  amount_micros: string;
  tan_masked: string | null;
  needs_tan: boolean;
  section_text: string | null;
  counterparty: string;
  reference: string;
  status: "OPEN" | "ACCEPTED" | "DISMISSED" | string;
  evidence: Record<string, unknown>;
  decided_reason: string | null;
  credit_id: string | null;
  created_at: string;
  note: string;
}
export const listSuggestions = async (
  id: string,
  params: { status?: string; profile_id?: string; year?: number; offset?: number } = {},
): Promise<{ total: number; items: Suggestion[] }> =>
  (await apiClient.get(`${base(id)}/suggestions`, { params })).data;
export const scanSuggestions = async (
  id: string,
  profileId: string,
): Promise<Record<string, unknown>> =>
  (await apiClient.post(`${base(id)}/suggestions/scan`, { profile_id: profileId })).data;
export const scanZohoSuggestions = async (
  id: string,
  profileId: string,
): Promise<Record<string, unknown>> =>
  (await apiClient.post(`${base(id)}/suggestions/zoho/scan`, { profile_id: profileId })).data;
export const acceptSuggestion = async (
  id: string,
  suggestion: string,
  body: {
    source_confirmation: string;
    tan?: string;
    amount?: string;
    seller_name_confirmed?: boolean;
  },
): Promise<CreditCase> =>
  (await apiClient.post(`${base(id)}/suggestions/${encodeURIComponent(suggestion)}/accept`, body))
    .data;
export const dismissSuggestion = async (
  id: string,
  suggestion: string,
  reason: string,
): Promise<Suggestion> =>
  (
    await apiClient.post(`${base(id)}/suggestions/${encodeURIComponent(suggestion)}/dismiss`, {
      reason,
    })
  ).data;
export const suggestionTemplate = async (id: string, format: "csv" | "xlsx"): Promise<Blob> =>
  (await apiClient.get(`${base(id)}/suggestion-template.${format}`, { responseType: "blob" })).data;
export interface Deductor {
  id: string;
  profile_id: string;
  tan_masked: string;
  counterparty: string;
  status: "PROPOSED" | "CONFIRMED" | "FLAGGED" | string;
  seen_as: string[];
  review_reason: string | null;
  updated_at: string;
}
export const listDeductors = async (id: string): Promise<{ items: Deductor[] }> =>
  (await apiClient.get(`${base(id)}/deductors`)).data;
export const confirmDeductor = async (
  id: string,
  deductor: string,
  body: { counterparty: string; reason: string },
): Promise<Deductor> =>
  (await apiClient.post(`${base(id)}/deductors/${encodeURIComponent(deductor)}/confirm`, body))
    .data;

// ------------------------------------------------------------------------------------------------ exceptions and pairings

export interface StatementException {
  profile_id: string;
  snapshot_id: string;
  line_id: string;
  year: number;
  section: string | null;
  on: string | null;
  amount_micros: string;
  reference: string | null;
  /** The same deductor's positive rows in the same statement: what this one could be a reversal of. */
  candidates: {
    line_id: string;
    amount_micros: string;
    reference: string | null;
    on: string | null;
    section: string | null;
  }[];
}
export const listExceptions = async (
  id: string,
): Promise<{ total: number; items: StatementException[]; note: string }> =>
  (await apiClient.get(`${base(id)}/exceptions`)).data;
export const pairReversal = async (
  id: string,
  body: {
    profile_id: string;
    snapshot_id: string;
    positive_line: number;
    negative_line: number;
    reason: string;
  },
): Promise<Record<string, unknown>> => (await apiClient.post(`${base(id)}/pairings`, body)).data;

// ------------------------------------------------------------------------------------------------ inquiries

export interface Inquiry {
  id: string;
  credit_id: string;
  status: "DRAFT" | "APPROVED" | "SENT" | "FAILED" | "REPLIED" | "WITHDRAWN" | string;
  document_kind: "CERTIFICATE" | "DEDUCTOR_ADVICE" | "CORRECTION_RESPONSE" | string;
  subject: string;
  body: string;
  recipient_label: string;
  recipient_masked: string | null;
  approved_by: string | null;
  approved_at: string | null;
  sent_by: string | null;
  sent_at: string | null;
  delivery_state: string | null;
  delivery_detail: string | null;
  override_reason: string | null;
  replied_at: string | null;
  reply_work_item_id: string | null;
  created_at: string;
  note: string;
}
export interface InquiryAllowance {
  used: number;
  limit: number;
  note: string;
}
export const getInquiryAllowance = async (id: string): Promise<InquiryAllowance> =>
  (await apiClient.get(`${base(id)}/inquiries/allowance`)).data;
export const listCaseInquiries = async (
  id: string,
  credit: string,
): Promise<{ items: Inquiry[] }> =>
  (await apiClient.get(`${base(id)}/credits/${encodeURIComponent(credit)}/inquiries`)).data;
export const draftInquiry = async (
  id: string,
  credit: string,
  body: { document_kind: string; subject?: string; body?: string },
): Promise<Inquiry> =>
  (await apiClient.post(`${base(id)}/credits/${encodeURIComponent(credit)}/inquiries`, body)).data;
export const editInquiry = async (
  id: string,
  inquiry: string,
  body: { subject?: string; body?: string; document_kind?: string },
): Promise<Inquiry> =>
  (await apiClient.patch(`${base(id)}/inquiries/${encodeURIComponent(inquiry)}`, body)).data;
export const approveInquiry = async (id: string, inquiry: string): Promise<Inquiry> =>
  (await apiClient.post(`${base(id)}/inquiries/${encodeURIComponent(inquiry)}/approve`, {})).data;
export const sendInquiry = async (
  id: string,
  inquiry: string,
  overrideReason?: string,
): Promise<Inquiry> =>
  (
    await apiClient.post(
      `${base(id)}/inquiries/${encodeURIComponent(inquiry)}/send`,
      overrideReason ? { override_reason: overrideReason } : {},
    )
  ).data;
export const withdrawInquiry = async (
  id: string,
  inquiry: string,
  reason: string,
): Promise<Inquiry> =>
  (
    await apiClient.post(`${base(id)}/inquiries/${encodeURIComponent(inquiry)}/withdraw`, {
      reason,
    })
  ).data;

// ------------------------------------------------------------------------------------------------ approvals and the closure ledger

export interface ClosurePolicy {
  threshold_micros: string;
  actions: string[];
  approver_role: "ADMIN" | "OWNER";
  updated_at: string;
  note: string;
}
export interface ClosureApproval {
  id: string;
  credit_id: string;
  action: string;
  reason: string;
  amount_micros: string;
  case_revision: number;
  approver_role: string;
  requested_by: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED" | "STALE" | string;
  decided_by: string | null;
  decided_reason: string | null;
  decided_at: string | null;
  created_at: string;
}
export const getClosurePolicy = async (
  id: string,
): Promise<{ policy: ClosurePolicy | null; available: boolean }> =>
  (await apiClient.get(`${base(id)}/policy`)).data;
export const listApprovals = async (
  id: string,
  status?: string,
): Promise<{ items: ClosureApproval[] }> =>
  (await apiClient.get(`${base(id)}/approvals`, { params: status ? { status } : {} })).data;
export const approveClosure = async (
  id: string,
  approval: string,
  reason: string,
): Promise<CreditCase> =>
  (
    await apiClient.post(`${base(id)}/approvals/${encodeURIComponent(approval)}/approve`, {
      reason,
    })
  ).data;
export const rejectClosure = async (
  id: string,
  approval: string,
  reason: string,
): Promise<unknown> =>
  (await apiClient.post(`${base(id)}/approvals/${encodeURIComponent(approval)}/reject`, { reason }))
    .data;
export const setClosurePolicy = async (
  organizationId: string,
  body: { threshold: string; actions: string[]; approver_role: "ADMIN" | "OWNER" },
): Promise<ClosurePolicy> =>
  (
    await apiClient.put(
      `/organizations/${encodeURIComponent(organizationId)}/trinetra/policy`,
      body,
    )
  ).data;
export interface ClosureLedger {
  now_visible_total_micros: string;
  now_visible_this_month_micros?: string;
  now_visible_this_year_micros?: string;
  now_visible_cases: number;
  months: { month: string; amount_micros: string; cases: number }[];
  ledger_note: string;
  [key: string]: unknown;
}
export const getClosureLedger = async (id: string): Promise<ClosureLedger> =>
  (await apiClient.get(`${base(id)}/outcomes`)).data;

export interface TemplateRowResult {
  row: number;
  reference: string;
  tan_masked: string;
  amount_micros: string;
  section_text: string | null;
  /** OK, or why it is refused: NOT_FOUND, AMBIGUOUS, NOT_USABLE, and the others the server names. */
  status: string;
  reason?: string;
}
export interface TemplatePreview {
  rows: number;
  ok: number;
  items: TemplateRowResult[];
}
const templateForm = (file: File, profileId: string, skipRefused?: boolean): FormData => {
  const form = new FormData();
  form.set("file", file);
  form.set("profile_id", profileId);
  if (skipRefused !== undefined) {
    form.set("skip_refused", String(skipRefused));
  }
  return form;
};
export const previewSuggestionTemplate = async (
  id: string,
  file: File,
  profileId: string,
): Promise<TemplatePreview> =>
  (await apiClient.post(`${base(id)}/suggestions/template/preview`, templateForm(file, profileId)))
    .data;
export const importSuggestionTemplate = async (
  id: string,
  file: File,
  profileId: string,
  skipRefused: boolean,
): Promise<Record<string, unknown>> =>
  (
    await apiClient.post(
      `${base(id)}/suggestions/template`,
      templateForm(file, profileId, skipRefused),
    )
  ).data;
export const mapDeductor = async (
  id: string,
  body: { profile_id: string; tan: string; counterparty: string; reason: string },
): Promise<Deductor> => (await apiClient.post(`${base(id)}/deductors`, body)).data;
