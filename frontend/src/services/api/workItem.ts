import type { AxiosProgressEvent, AxiosResponse } from "axios";
import apiClient from "@/services/api/client";
import { KNOWLEDGE_ENDPOINTS, WORK_ITEM_ENDPOINTS } from "@/services/api/endpoints";
import type {
  DocumentCounts,
  ReindexResult,
  ReindexStatus,
  UploadDocumentResponse,
  WorkItemQueryFilters,
  WorkItemsListResponse,
  WorkItemResponse,
} from "@/types/workItem";

const JSON_HEADERS = { Accept: "application/json" } as const;

const buildQueryParams = (filters: WorkItemQueryFilters): URLSearchParams => {
  const params = new URLSearchParams({
    skip: String((filters.page - 1) * filters.pageSize),
    limit: String(filters.pageSize),
  });
  if (filters.search?.trim()) {params.set("search", filters.search.trim());}
  if (filters.status) {params.set("status", filters.status);}
  if (filters.sortBy) {params.set("sort_by", filters.sortBy);}
  if (filters.sortOrder) {params.set("sort_order", filters.sortOrder);}
  if (filters.fileFormat) {params.set("file_format", filters.fileFormat);}
  if (filters.uploadedFrom) {params.set("uploaded_from", filters.uploadedFrom);}
  if (filters.uploadedTo) {params.set("uploaded_to", filters.uploadedTo);}
  return params;
};

export const uploadDocument = async (
  workspaceId: string,
  file: File,
  onUploadProgress?: (progressEvent: AxiosProgressEvent) => void,
): Promise<UploadDocumentResponse> => {
  const formData = new FormData();
  formData.append("file", file);

  const response = await apiClient.post<
    UploadDocumentResponse,
    AxiosResponse<UploadDocumentResponse>
  >(WORK_ITEM_ENDPOINTS.upload(workspaceId), formData, {
    headers: { "Content-Type": "multipart/form-data", ...JSON_HEADERS },
    ...(onUploadProgress ? { onUploadProgress } : {}),
  });
  return response.data;
};

export const uploadSampleDocument = async (workspaceId: string): Promise<UploadDocumentResponse> => {
  const response = await apiClient.post<UploadDocumentResponse>(WORK_ITEM_ENDPOINTS.sample(workspaceId), null, {
    headers: JSON_HEADERS,
  });
  return response.data;
};

export const getWorkItems = async (
  workspaceId: string,
  filters: WorkItemQueryFilters,
): Promise<WorkItemsListResponse> => {
  const response = await apiClient.get<Omit<WorkItemsListResponse, "total"> & { totalItems: number }>(
    WORK_ITEM_ENDPOINTS.list(workspaceId),
    { params: buildQueryParams(filters), headers: JSON_HEADERS },
  );
  return { ...response.data, total: response.data.totalItems };
};

export const getDocumentCounts = async (workspaceId: string): Promise<DocumentCounts> => {
  const { data } = await apiClient.get<DocumentCounts>(`${WORK_ITEM_ENDPOINTS.list(workspaceId)}/counts`);
  return data;
};

export const getWorkItemDetails = async (
  workspaceId: string,
  workItemId: string,
): Promise<WorkItemResponse> => {
  const response = await apiClient.get<WorkItemResponse>(
    WORK_ITEM_ENDPOINTS.details(workspaceId, workItemId),
    { headers: JSON_HEADERS },
  );
  return response.data;
};

export const reprocessWorkItem = async (
  workspaceId: string,
  workItemId: string,
): Promise<void> => {
  await apiClient.post(
    WORK_ITEM_ENDPOINTS.reprocess(workspaceId, workItemId),
    null,
    { headers: JSON_HEADERS },
  );
};

export const deleteWorkItem = async (
  workspaceId: string,
  workItemId: string,
): Promise<void> => {
  await apiClient.delete(WORK_ITEM_ENDPOINTS.remove(workspaceId, workItemId), {
    headers: JSON_HEADERS,
  });
};

export const reindexKnowledgeBase = async (
  workspaceId: string,
): Promise<ReindexResult> => {
  const response = await apiClient.post<ReindexResult>(
    KNOWLEDGE_ENDPOINTS.reindex(workspaceId),
    {},
    { headers: JSON_HEADERS },
  );
  return response.data;
};

export const getReindexStatus = async (
  workspaceId: string,
): Promise<ReindexStatus> => {
  const response = await apiClient.get<ReindexStatus>(
    KNOWLEDGE_ENDPOINTS.reindexStatus(workspaceId),
    { headers: JSON_HEADERS },
  );
  return response.data;
};

export const workItemApi = {
  getDocumentCounts,
  uploadDocument,
  uploadSampleDocument,
  getWorkItems,
  getWorkItemDetails,
  reprocessWorkItem,
  deleteWorkItem,
  reindexKnowledgeBase,
  getReindexStatus,
};

export default workItemApi;
