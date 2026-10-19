/** GST Credit API client (docs/product/GST-CREDIT.md). Workspace-scoped. */

import { apiClient } from "@/services/api/client";
import type {
  GstDecisionKind,
  GstImportResponse,
  GstLineDetail,
  GstLinePage,
  GstOrgLinePage,
  GstOrgSummary,
  GstReminder,
  GstStatus,
  GstSummary,
  GstSupplierPage,
  ImsAction,
} from "@/types/gst";

const base = (workspaceId: string): string => `/workspaces/${encodeURIComponent(workspaceId)}/gst`;

export interface GstScope {
  readonly gstin?: string | null;
  readonly period?: string | null;
}

const scopeParams = (scope: GstScope): URLSearchParams => {
  const params = new URLSearchParams();
  if (scope.gstin) {params.set("gstin", scope.gstin);}
  if (scope.period) {params.set("period", scope.period);}
  return params;
};

export const getGstSummary = async (workspaceId: string, scope: GstScope = {}): Promise<GstSummary> =>
  (await apiClient.get<GstSummary>(`${base(workspaceId)}/summary?${scopeParams(scope).toString()}`)).data;

export const importGstReturn = async (workspaceId: string, file: File): Promise<GstImportResponse> => {
  const form = new FormData();
  form.append("file", file);
  return (await apiClient.post<GstImportResponse>(`${base(workspaceId)}/returns`, form)).data;
};

export const listGstSuppliers = async (
  workspaceId: string,
  scope: GstScope,
  offset = 0,
  limit = 50,
): Promise<GstSupplierPage> => {
  const params = scopeParams(scope);
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return (await apiClient.get<GstSupplierPage>(`${base(workspaceId)}/suppliers?${params.toString()}`)).data;
};

export interface GstLineFilters extends GstScope {
  readonly status?: readonly GstStatus[];
  readonly supplier?: string;
  readonly ims?: ImsAction;
  readonly q?: string;
  readonly atRisk?: boolean;
  readonly offset?: number;
  readonly limit?: number;
}

export const listGstLines = async (workspaceId: string, filters: GstLineFilters = {}): Promise<GstLinePage> => {
  const params = scopeParams(filters);
  filters.status?.forEach((value) => params.append("status", value));
  if (filters.supplier) {params.set("supplier", filters.supplier);}
  if (filters.ims) {params.set("ims", filters.ims);}
  if (filters.q) {params.set("q", filters.q);}
  if (filters.atRisk) {params.set("at_risk", "true");}
  params.set("offset", String(filters.offset ?? 0));
  params.set("limit", String(filters.limit ?? 50));
  return (await apiClient.get<GstLinePage>(`${base(workspaceId)}/records?${params.toString()}`)).data;
};

export const getGstLine = async (workspaceId: string, lineId: string): Promise<GstLineDetail> =>
  (await apiClient.get<GstLineDetail>(`${base(workspaceId)}/records/${encodeURIComponent(lineId)}`)).data;

export const decideGstRecord = async (
  workspaceId: string,
  recordId: string,
  body: { decision: GstDecisionKind; work_item_id?: string; note?: string },
): Promise<void> => {
  await apiClient.post(`${base(workspaceId)}/records/${encodeURIComponent(recordId)}/decision`, body);
};

export const undoGstDecision = async (workspaceId: string, recordId: string): Promise<void> => {
  await apiClient.delete(`${base(workspaceId)}/records/${encodeURIComponent(recordId)}/decision`);
};

export const getGstReminder = async (workspaceId: string, supplierGstin: string, gstin: string): Promise<GstReminder> =>
  (
    await apiClient.get<GstReminder>(
      `${base(workspaceId)}/suppliers/${encodeURIComponent(supplierGstin)}/reminder?gstin=${encodeURIComponent(gstin)}`,
    )
  ).data;

export const sendGstReminder = async (workspaceId: string, supplierGstin: string, gstin: string): Promise<GstReminder> =>
  (
    await apiClient.post<GstReminder>(
      `${base(workspaceId)}/suppliers/${encodeURIComponent(supplierGstin)}/reminder/send?gstin=${encodeURIComponent(gstin)}`,
    )
  ).data;

/** The export is fetched as a blob so the request carries the session's authorisation. */
export const downloadGstWorkbook = async (workspaceId: string, scope: GstScope): Promise<Blob> =>
  (
    await apiClient.get<Blob>(`${base(workspaceId)}/export.xlsx?${scopeParams(scope).toString()}`, {
      responseType: "blob",
    })
  ).data;

// ---------------------------------------------------------------------------------- every workspace (Enterprise)

const orgBase = (organizationId: string): string => `/organizations/${encodeURIComponent(organizationId)}/gst`;

export const getGstOrgSummary = async (organizationId: string, scope: GstScope = {}): Promise<GstOrgSummary> =>
  (await apiClient.get<GstOrgSummary>(`${orgBase(organizationId)}/summary?${scopeParams(scope).toString()}`)).data;

export const listGstOrgSuppliers = async (
  organizationId: string,
  scope: GstScope,
  offset = 0,
  limit = 50,
): Promise<GstSupplierPage> => {
  const params = scopeParams(scope);
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return (await apiClient.get<GstSupplierPage>(`${orgBase(organizationId)}/suppliers?${params.toString()}`)).data;
};

export interface GstOrgLineFilters extends GstLineFilters {
  readonly workspaceId?: string;
}

export const listGstOrgLines = async (organizationId: string, filters: GstOrgLineFilters = {}): Promise<GstOrgLinePage> => {
  const params = scopeParams(filters);
  filters.status?.forEach((value) => params.append("status", value));
  if (filters.supplier) {params.set("supplier", filters.supplier);}
  if (filters.q) {params.set("q", filters.q);}
  if (filters.atRisk) {params.set("at_risk", "true");}
  if (filters.workspaceId) {params.set("workspace_id", filters.workspaceId);}
  params.set("offset", String(filters.offset ?? 0));
  params.set("limit", String(filters.limit ?? 50));
  return (await apiClient.get<GstOrgLinePage>(`${orgBase(organizationId)}/records?${params.toString()}`)).data;
};
