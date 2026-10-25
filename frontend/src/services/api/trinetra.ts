import { apiClient } from "@/services/api/client";

export interface CreditCase {
  id: string;
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
    evidence?: { work_item_id: string; kind: string; current: boolean }[];
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
export const getTrinetraAccess = async (
  id: string,
): Promise<{ live_enabled: boolean; entitled: boolean }> =>
  (await apiClient.get(`${base(id)}/access`)).data;
export const getTrinetraCockpit = async (id: string, sample: boolean): Promise<Cockpit> =>
  (await apiClient.get(`${base(id)}/${sample ? "sample" : "summary"}`)).data;
export interface TaxProfile {
  id: string;
  name: string;
  pan_masked: string;
}
export interface CaseDetail extends CreditCase {
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
