import type {
  DocumentFormat,
  WorkItemQueryFilters,
  WorkItemSortField,
  WorkItemStatus,
} from "@/types/workItem";

const STATUSES: readonly string[] = ["QUEUED", "PROCESSING", "COMPLETED", "FAILED"];
const FORMATS: readonly string[] = ["pdf", "docx", "xlsx", "csv", "image"];
const SORTS: readonly string[] = [
  "created_at",
  "updated_at",
  "original_filename",
  "file_size",
  "status",
];
const validDate = (value: string | null): value is string =>
  Boolean(
    value &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    value >= "0001-01-01" &&
    value < "9999-12-31" &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value,
  );

export function readDocumentFilters(params: URLSearchParams): WorkItemQueryFilters {
  const page = Number(params.get("page") ?? 1);
  const pageSize = Number(params.get("pageSize") ?? 10);
  const status = params.get("status");
  const format = params.get("format");
  const sort = params.get("sort");
  const from = params.get("from");
  const to = params.get("to");
  return {
    page: Number.isSafeInteger(page) && page > 0 && page <= 1000000 ? page : 1,
    pageSize: [10, 25, 50].includes(pageSize) ? pageSize : 10,
    sortBy: SORTS.includes(sort ?? "") ? (sort as WorkItemSortField) : "created_at",
    sortOrder: params.get("order") === "asc" ? "asc" : "desc",
    ...(STATUSES.includes(status ?? "") ? { status: status as WorkItemStatus } : {}),
    ...(FORMATS.includes(format ?? "") ? { fileFormat: format as DocumentFormat } : {}),
    ...(params.get("search")?.trim() ? { search: params.get("search")!.trim().slice(0, 100) } : {}),
    ...(validDate(from) ? { uploadedFrom: from } : {}),
    ...(validDate(to) && (!validDate(from) || from <= to) ? { uploadedTo: to } : {}),
  };
}

export function documentFormatLabel(mime: string): string {
  const formats: Record<string, string> = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-excel": "XLS",
    "text/csv": "CSV",
    "application/csv": "CSV",
    "image/jpeg": "JPG",
  };
  return formats[mime] ?? mime.split("/").pop()?.toUpperCase() ?? "FILE";
}
