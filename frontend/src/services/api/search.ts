/**
 * PHASE 4 — global search (Ctrl+K).
 *
 * Documents (by file name or any extracted value, e.g. an invoice number),
 * entity records, cases, GST suppliers (GSTIN or name), invoices in the GST books
 * (by number) and automation rules (by name), from every workspace of the
 * organization the caller may open - never another. A result the person's role or
 * the plan would lock is not returned. Each hit names its workspace so the
 * palette can open it there.
 */
import apiClient from "@/services/api/client";
import { SEARCH_ENDPOINTS } from "@/services/api/endpoints";

export type SearchHitKind = "DOCUMENT" | "ENTITY" | "CASE" | "GST_SUPPLIER" | "GST_INVOICE" | "RULE";

export interface SearchHit {
  kind: SearchHitKind;
  id: string;
  title: string;
  subtitle: string | null;
  workspace_id: string;
  workspace_slug: string;
  workspace_name: string;
  /** What to look the hit up by on its page: a GSTIN or an invoice number (GST hits); else null. */
  reference: string | null;
}

export interface SearchResponse {
  query: string;
  workspaces_searched: number;
  documents: SearchHit[];
  entities: SearchHit[];
  cases: SearchHit[];
  suppliers: SearchHit[];
  gst_invoices: SearchHit[];
  rules: SearchHit[];
}

/** The server refuses shorter queries (422). */
export const MIN_SEARCH_LENGTH = 2;

export const searchOrganization = async (
  organizationId: string,
  query: string,
  signal?: AbortSignal,
): Promise<SearchResponse> => {
  const response = await apiClient.get<SearchResponse>(
    SEARCH_ENDPOINTS.organization(organizationId),
    signal
      ? { params: { q: query, limit: 5 }, signal }
      : { params: { q: query, limit: 5 } },
  );
  return response.data;
};
