import apiClient from "@/services/api/client";
import type { ReceiptPeriod, ValueReceipt } from "@/types/valueReceipt";

const base = (organizationId: string): string => {
  if (!organizationId) {
    throw new Error("An organizationId is required to read the value receipt. Gate the query with `enabled`.");
  }
  return `/organizations/${encodeURIComponent(organizationId)}/value-receipt`;
};

export const getValueReceipt = async (organizationId: string, period: ReceiptPeriod): Promise<ValueReceipt> =>
  (await apiClient.get<ValueReceipt>(`${base(organizationId)}?period=${period}`)).data;

/** The one-page PDF, fetched as a blob so the request carries the session's authorisation. */
export const downloadValueReceiptPdf = async (organizationId: string, period: ReceiptPeriod): Promise<Blob> =>
  (await apiClient.get<Blob>(`${base(organizationId)}.pdf?period=${period}`, { responseType: "blob" })).data;
