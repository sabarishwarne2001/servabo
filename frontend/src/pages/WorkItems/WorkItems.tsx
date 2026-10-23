import React, { useState, useMemo, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Search,
  FileText,
  RefreshCw,
  Eye,
  Trash2,
  ArrowUpDown,
  Filter,
  Upload,
  X,
  Files,
  CircleCheck,
  CircleAlert,
  Activity,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

import { documentFormatLabel, readDocumentFilters } from "./documentFilters";
import { workItemApi } from "@/services/api/workItem";
import { useActiveWorkspaceId } from "@/hooks/useActiveWorkspace";
import { useTenant } from "@/hooks/useTenant"; // Imported to resolve slug links
import { workItemKeys, invalidateWorkspace, keepPreviousWithinWorkspace } from "@/services/api/queryKeys";

import { useOptionalTenant } from "@/routes/TenantContext";
import { canCreateContent } from "@/permissions/workspacePermissions";
import { BulkActionBar } from "@/components/workItems/BulkActionBar";
import { formatTimestamp, formatTimestampDate } from "@/utils/displayTime";
import { SkeletonTable } from "@/components/common/skeletons/SkeletonTable";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { formatBytes } from "@/utils/formatters";
import { ApiError } from "@/services/api/client";
import type { WorkItemStatus, WorkItemSortField } from "@/types/workItem";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { UploadTray } from "@/components/common/UploadTray";
import { errorMessage } from "@/services/api/errors";

const filterFormSchema = z.object({
  format: z.enum(["ALL", "pdf", "docx", "xlsx", "csv", "image"]).optional(),
  from: z.string().optional(),
  to: z.string().optional(),
  search: z.string().max(100, "Search query is too long.").optional(),
  status: z
    .union([
      z.literal("ALL"),
      z.literal("QUEUED"),
      z.literal("PROCESSING"),
      z.literal("COMPLETED"),
      z.literal("FAILED"),
    ])
    .optional(),
}).refine((data) => !data.from || !data.to || data.from <= data.to, { message: "Start date must be on or before end date.", path: ["to"] });

type FilterFormInput = z.infer<typeof filterFormSchema>;

const STATUS_BADGE_MAP: Record<WorkItemStatus, string> = {
  QUEUED: "bg-primary/[0.08] text-primary border-primary/20 dark:text-[hsl(var(--primary-on-dark))]",
  PROCESSING: "bg-sky-500/[0.08] text-sky-700 border-sky-500/25 dark:text-sky-300",
  COMPLETED: "bg-emerald-500/[0.08] text-emerald-600 border-emerald-500/25 dark:text-emerald-400",
  FAILED: "bg-destructive/[0.08] text-destructive border-destructive/25",
};

export const WorkItems: React.FC = () => {
  const queryClient = useQueryClient();
  const workspaceId = useActiveWorkspaceId();
  const { state: tenantState } = useTenant(); // Retrieve active tenant state for slugs
  // Viewers read documents; uploading, reprocessing, deleting and bulk actions are contributor
  // work (the server refuses them to viewers), so the controls are not offered to them.
  const resolvedTenant = useOptionalTenant();
  const canWrite = resolvedTenant ? canCreateContent(resolvedTenant.workspaceRole) : false;
  const [selectedIds, setSelectedIds] = useState<readonly string[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedWorkItemId, setSelectedWorkItemId] = useState<string | null>(null);
  const [reprocessDialogOpen, setReprocessDialogOpen] = useState(false);
  const [selectedReprocessWorkItemId, setSelectedReprocessWorkItemId] = useState<string | null>(null);

  const [searchParams, setSearchParams] = useSearchParams();
  const queryFilters = useMemo(() => readDocumentFilters(searchParams), [searchParams]);
  const { page: currentPage, pageSize, sortBy, sortOrder } = queryFilters;
  const updateParams = useCallback((updates: Record<string, string | undefined>) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(updates)) {
        if (value) {next.set(key, value);} else {next.delete(key);}
      }
      return next;
    });
  }, [setSearchParams]);

  const counts = useQuery({
    queryKey: workItemKeys.counts(workspaceId!),
    queryFn: () => workItemApi.getDocumentCounts(workspaceId!),
    enabled: Boolean(workspaceId),
    refetchInterval: 10000,
  });

  // A selection only ever covers rows on screen: changing page, filter, sort or workspace clears it.
  useEffect(() => {
    setSelectedIds([]);
  }, [workspaceId, queryFilters]);

  const {
    data: response,
    isLoading,
    isFetching,
    isPlaceholderData,
    error,
  } = useQuery({
    queryKey: workItemKeys.list(workspaceId!, queryFilters),
    queryFn: () => workItemApi.getWorkItems(workspaceId!, queryFilters),
    enabled: Boolean(workspaceId),
    placeholderData: keepPreviousWithinWorkspace(workspaceId!),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const currentList = query.state.data;
      if (!currentList || !Array.isArray(currentList.items)) {return false;}
      const hasRunningJobs = currentList.items.some(
        (item) => item.status === "QUEUED" || item.status === "PROCESSING"
      );
      return hasRunningJobs ? 2000 : false;
    },
  });

  const reprocessMutation = useMutation({
    mutationFn: (workItemId: string) => workItemApi.reprocessWorkItem(workspaceId!, workItemId),
    onSuccess: async () => {
      setReprocessDialogOpen(false);
      setSelectedReprocessWorkItemId(null);
      toast.success("Document queued for reprocessing.");
      await invalidateWorkspace(queryClient, workspaceId!);
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError) {
        toast.error(errorMessage(error, "Unable to reprocess document."));
        return;
      }
      toast.error("Unexpected network error.");
    },
  });

  const triggerReprocess = (workItemId: string): void => {
    setSelectedReprocessWorkItemId(workItemId);
    setReprocessDialogOpen(true);
  };

  const confirmReprocess = (): void => {
    if (!selectedReprocessWorkItemId) {return;}
    reprocessMutation.mutate(selectedReprocessWorkItemId);
  };

  const deleteMutation = useMutation({
    mutationFn: (workItemId: string) => workItemApi.deleteWorkItem(workspaceId!, workItemId),
    onSuccess: async () => {
      setDeleteDialogOpen(false);
      setSelectedWorkItemId(null);
      toast.success("Document deleted successfully.");
      await invalidateWorkspace(queryClient, workspaceId!);
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError) {
        toast.error(errorMessage(error, "Unable to delete document."));
        return;
      }
      toast.error("Unexpected network error.");
    },
  });

  const triggerDelete = (workItemId: string): void => {
    setSelectedWorkItemId(workItemId);
    setDeleteDialogOpen(true);
  };

  const confirmDelete = (): void => {
    if (!selectedWorkItemId) {return;}
    deleteMutation.mutate(selectedWorkItemId);
  };

  const { register, handleSubmit, reset, formState: { errors: filterErrors } } = useForm<FilterFormInput>({
    resolver: zodResolver(filterFormSchema),
    defaultValues: {
      search: "",
      status: queryFilters.status ?? "ALL",
      format: queryFilters.fileFormat ?? "ALL",
      from: queryFilters.uploadedFrom ?? "",
      to: queryFilters.uploadedTo ?? "",
    },
  });

  useEffect(() => {
    reset({ search: queryFilters.search ?? "", status: queryFilters.status ?? "ALL", format: queryFilters.fileFormat ?? "ALL", from: queryFilters.uploadedFrom ?? "", to: queryFilters.uploadedTo ?? "" });
  }, [queryFilters, reset]);

  const handleApplyFiltersSubmit = (data: FilterFormInput): void => {
    updateParams({ page: undefined, search: data.search?.trim(), status: data.status === "ALL" ? undefined : data.status, format: data.format === "ALL" ? undefined : data.format, from: data.from, to: data.to });
  };
  const handleSortToggle = (field: WorkItemSortField): void => {
    updateParams({ page: undefined, sort: field, order: sortBy === field && sortOrder === "desc" ? "asc" : "desc" });
  };
  const items = response?.items ?? [];
  const totalPages = response?.totalPages ?? 1;
  const hasFilters = Boolean(queryFilters.search || queryFilters.status || queryFilters.fileFormat || queryFilters.uploadedFrom || queryFilters.uploadedTo);
  useEffect(() => {
    if (response && !isFetching && !isPlaceholderData && currentPage > totalPages) {
      updateParams({ page: String(totalPages) });
    }
  }, [response, isFetching, isPlaceholderData, currentPage, totalPages, updateParams]);


  // Construct workspace-scoped details URLs dynamically using the active slugs
  const getDetailsPath = (itemId: string) => {
    if (tenantState.status !== "ready") {return "#";}
    return `/${tenantState.organization.organization_slug}/${tenantState.workspace.slug}/work-items/${itemId}`;
  };

  if (isLoading && !response) {
    return (
      <div className="space-y-6">
        <div className="space-y-1 select-none">
          <h2 className="text-2xl font-semibold tracking-tight">Documents Database</h2>
          <div className="h-4 w-96 rounded bg-muted/40 animate-pulse" />
        </div>
        <SkeletonTable rows={10} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <ErrorState
          title="Failed to load documents"
          description="An error occurred while loading your document collection."
          onRetry={async () => {
            if (workspaceId) {
              await queryClient.invalidateQueries({
                queryKey: workItemKeys.all(workspaceId),
              });
            }
          }}
        />
      </div>
    );
  }

  return (
    <div className="intelligence-page documents-page space-y-5">
      <div className="intelligence-header flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="intelligence-mark" aria-hidden="true"><Files /></span>
          <div className="space-y-1"><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Documents Database</h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Monitor ingestion pipelines, search uploaded documents, inspect AI processing status, and navigate into detailed extraction results.
          </p></div>
        </div>
        {canWrite && (
          <button
            type="button"
            onClick={() => setUploadOpen((open) => !open)}
            aria-expanded={uploadOpen}
            className={`fp-btn ${uploadOpen ? "fp-btn-secondary" : "fp-btn-primary"} h-9 shrink-0 text-[13px]`}
          >
            {uploadOpen ? <X className="h-3.5 w-3.5" /> : <Upload className="h-3.5 w-3.5" />}
            {uploadOpen ? "Close upload" : "Upload documents"}
          </button>
        )}
      </div>

      <section aria-label="Document statistics" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[
          { label: "Total documents", value: counts.data?.total, Icon: Files, tone: "blue", detail: "Across this workspace", status: undefined },
          { label: "Processing", value: counts.data?.processing, Icon: Activity, tone: "cyan", detail: `${counts.data?.queued ?? "—"} queued for processing`, status: "PROCESSING" },
          { label: "Completed", value: counts.data?.completed, Icon: CircleCheck, tone: "green", detail: "Processing completed", status: "COMPLETED" },
          { label: "Failed", value: counts.data?.failed, Icon: CircleAlert, tone: "red", detail: "May need your attention", status: "FAILED" },
        ].map(({ label, value, Icon, tone, detail, status }) => (
          <button key={label} type="button" className={`document-stat document-stat-${tone}`} onClick={() => updateParams({ status, page: undefined })} aria-label={`Show ${label.toLowerCase()}`}>
            <span className="document-stat-icon"><Icon className="h-6 w-6" aria-hidden="true" /></span>
            <span className="min-w-0"><span className="block text-xs text-muted-foreground sm:text-sm">{label}</span><span className="my-1 block text-2xl font-semibold tracking-tight tabular-nums" aria-live="polite">{counts.isError ? "—" : value?.toLocaleString() ?? "…"}</span><span className="block text-[11px] text-muted-foreground">{detail}</span></span>
          </button>
        ))}
      </section>
      {counts.isError && <p role="status" className="text-xs text-muted-foreground">Document counts are unavailable. <button type="button" className="underline" onClick={() => void counts.refetch()}>Retry counts</button></p>}

      {canWrite && uploadOpen && (
        <UploadTray
          onUploadSuccess={() => {
            if (workspaceId) {
              void invalidateWorkspace(queryClient, workspaceId);
            }
          }}
        />
      )}

      <form
        onSubmit={handleSubmit(handleApplyFiltersSubmit)}
        noValidate
        className="documents-filters fp-card flex flex-wrap items-end gap-3 p-3"
      >
        <div className="relative min-w-[180px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            {...register("search")}
            type="text"
            placeholder="Search documents..."
            aria-label="Search documents by filename"
            maxLength={100}
            className="fp-input h-9 pl-9 pr-4"
          />
        </div>

        <div className="relative w-full sm:w-40">
          <select
            {...register("status")}
            aria-label="Filter by status"
            className="fp-input h-9 cursor-pointer appearance-none pr-9"
          >
            <option value="ALL">All Statuses</option>
            <option value="QUEUED">Queued</option>
            <option value="PROCESSING">Processing</option>
            <option value="COMPLETED">Completed</option>
            <option value="FAILED">Failed</option>
          </select>
          <Filter className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        </div>

        <select {...register("format")} aria-label="Filter by format" className="fp-input h-9 w-full sm:w-32">
          <option value="ALL">All formats</option><option value="pdf">PDF</option><option value="docx">DOCX</option><option value="xlsx">XLSX</option><option value="csv">CSV</option><option value="image">Images</option>
        </select>
        <label className="flex-1 text-[11px] text-muted-foreground sm:max-w-40">Uploaded from<input {...register("from")} type="date" aria-label="Uploaded from" className="fp-input mt-1 h-9" /></label>
        <label className="flex-1 text-[11px] text-muted-foreground sm:max-w-40">Uploaded through<input {...register("to")} type="date" aria-label="Uploaded through" aria-invalid={Boolean(filterErrors.to)} className="fp-input mt-1 h-9" /></label>
        <button
          type="submit"
          className="fp-btn fp-btn-secondary h-9 text-[13px]"
        >
          <Search className="h-3.5 w-3.5" />
          <span>Apply Filters</span>
        </button>
        {hasFilters && <button type="button" className="fp-btn fp-btn-ghost h-9 text-xs" onClick={() => updateParams({ search: undefined, status: undefined, format: undefined, from: undefined, to: undefined, page: undefined })}><X className="h-3.5 w-3.5" />Reset</button>}
        {filterErrors.to && <p role="alert" className="w-full text-xs text-destructive">{filterErrors.to.message}</p>}
      </form>

      <div className="documents-table relative overflow-hidden fp-card">
        {isFetching && (
          <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-primary/20">
            <div className="h-full w-full animate-pulse bg-primary" />
          </div>
        )}
        <div className="overflow-x-auto">
          {items.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={FileText}
                title="No documents found"
                description="No documents match the current search and filter criteria."
              />
            </div>
          ) : (
            <>
            {/* F-166: on a phone, documents are cards with their full name; the table needs width. */}
            <ul className="divide-y divide-border/60 md:hidden" aria-label="Documents">
              {items.map((item) => (
                <li
                  key={item.id}
                  data-testid="document-card"
                  className={`flex items-start gap-3 px-3 py-3 ${selectedIds.includes(item.id) ? "bg-primary/[0.04]" : ""}`}
                >
                  {canWrite && (
                    <input
                      type="checkbox"
                      aria-label={`Select ${item.original_filename}`}
                      className="mt-1 h-4 w-4 shrink-0 cursor-pointer rounded border-border accent-primary"
                      checked={selectedIds.includes(item.id)}
                      onChange={(event) =>
                        setSelectedIds((current) =>
                          event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id),
                        )
                      }
                    />
                  )}
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Link to={getDetailsPath(item.id)} className="block break-all text-sm font-medium leading-snug text-foreground hover:text-primary">
                      {item.original_filename}
                    </Link>
                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ${STATUS_BADGE_MAP[item.status]}`}
                      >
                        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
                        {item.status.toLowerCase()}
                      </span>
                      {item.duplicate_of && (
                        <Link
                          to={getDetailsPath(item.duplicate_of.id)}
                          title={`Same file as ${item.duplicate_of.original_filename}`}
                          className="rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300"
                        >
                          Duplicate
                        </Link>
                      )}
                      <span className="font-mono text-[11px]">{documentFormatLabel(item.file_type)}</span>
                      <span>·</span>
                      <span className="font-mono text-[11px]">{formatBytes(item.file_size)}</span>
                      <span>·</span>
                      <time dateTime={item.created_at}>{formatTimestampDate(item.created_at)}</time>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    {canWrite && item.status === "FAILED" && (
                      <button
                        type="button"
                        disabled={reprocessMutation.isPending}
                        onClick={() => triggerReprocess(item.id)}
                        aria-label={`Retry processing ${item.original_filename}`}
                        className="rounded-md p-1.5 text-amber-600 hover:bg-amber-500/10 dark:text-amber-400"
                      >
                        <RefreshCw className="h-4 w-4" />
                      </button>
                    )}
                    {canWrite && (
                      <button
                        type="button"
                        onClick={() => triggerDelete(item.id)}
                        disabled={deleteMutation.isPending}
                        aria-label={`Delete ${item.original_filename}`}
                        className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            <table className="hidden w-full min-w-[800px] table-fixed border-collapse text-left md:table">
              <thead>
                <tr className="sticky top-0 z-[1] border-b border-border bg-muted/40 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground backdrop-blur">
                  {canWrite && (
                    <th className="w-10 py-2.5 pl-4 pr-0">
                      <input
                        type="checkbox"
                        aria-label="Select every document on this page"
                        className="h-4 w-4 cursor-pointer rounded border-border accent-primary"
                        checked={items.length > 0 && selectedIds.length === items.length}
                        ref={(element) => {
                          if (element) {
                            element.indeterminate =
                              selectedIds.length > 0 && selectedIds.length < items.length;
                          }
                        }}
                        onChange={(event) =>
                          setSelectedIds(event.target.checked ? items.map((item) => item.id) : [])
                        }
                      />
                    </th>
                  )}
                  <th
                    className="w-[34%] px-4 py-2.5"
                    aria-sort={
                      sortBy === "original_filename"
                        ? sortOrder === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      disabled={isFetching}
                      onClick={() => handleSortToggle("original_filename")}
                      className="flex items-center space-x-1.5 font-semibold uppercase transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                    >
                      <span>Document Filename</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </button>
                  </th>
                  <th
                    className="w-[14%] px-4 py-2.5"
                    aria-sort={
                      sortBy === "created_at"
                        ? sortOrder === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      disabled={isFetching}
                      onClick={() => handleSortToggle("created_at")}
                      className="flex items-center space-x-1.5 font-semibold uppercase transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                    >
                      <span className="whitespace-nowrap">Uploaded</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </button>
                  </th>
                  <th className="w-[9%] px-4 py-2.5">Format</th>
                  <th
                    className="w-[12%] px-4 py-2.5"
                    aria-sort={
                      sortBy === "file_size"
                        ? sortOrder === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      disabled={isFetching}
                      onClick={() => handleSortToggle("file_size")}
                      className="flex items-center space-x-1.5 font-semibold uppercase transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                    >
                      <span className="whitespace-nowrap">File Size</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </button>
                  </th>
                  <th className="w-[14%] px-4 py-2.5">Status</th>
                  <th className="w-[12%] px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>

              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={`group border-b border-border/60 text-sm transition-colors last:border-b-0 hover:bg-muted/40 ${
                      selectedIds.includes(item.id) ? "bg-primary/[0.04]" : ""
                    }`}
                  >
                    {canWrite && (
                      <td className="py-3 pl-4 pr-0">
                        <input
                          type="checkbox"
                          aria-label={`Select ${item.original_filename}`}
                          className="h-4 w-4 cursor-pointer rounded border-border accent-primary"
                          checked={selectedIds.includes(item.id)}
                          onChange={(event) =>
                            setSelectedIds((current) =>
                              event.target.checked
                                ? [...current, item.id]
                                : current.filter((id) => id !== item.id),
                            )
                          }
                        />
                      </td>
                    )}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className={`document-file-icon document-file-${documentFormatLabel(item.file_type).toLowerCase()}`}>
                          <FileText className="h-4 w-4" />
                        </span>
                        <Link to={getDetailsPath(item.id)} className="min-w-0 truncate font-medium text-foreground hover:text-primary" title={item.original_filename}>
                          {item.original_filename}
                        </Link>
                        {item.duplicate_of && (
                          <Link
                            to={getDetailsPath(item.duplicate_of.id)}
                            title={`Same file as ${item.duplicate_of.original_filename}`}
                            className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-700 hover:border-amber-500/60 dark:text-amber-300"
                          >
                            Duplicate
                          </Link>
                        )}
                      </div>
                    </td>
                    <td className="truncate px-4 py-3 text-xs text-muted-foreground" title={formatTimestamp(item.created_at)}>
                      <time dateTime={item.created_at}>{formatTimestampDate(item.created_at)}</time>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                        {documentFormatLabel(item.file_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {formatBytes(item.file_size)}
                    </td>
                    <td className="px-4 py-3 select-none">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10.5px] font-semibold uppercase leading-4 tracking-wide ${STATUS_BADGE_MAP[item.status]}`}
                      >
                        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
                        {item.status.toLowerCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {canWrite && item.status === "FAILED" && (
                          <button
                            type="button"
                            disabled={reprocessMutation.isPending}
                            onClick={() => triggerReprocess(item.id)}
                            title="Retry Processing"
                            aria-label="Retry Processing"
                            className="rounded-md p-1.5 text-amber-600 hover:bg-amber-500/10 disabled:pointer-events-none disabled:opacity-50 dark:text-amber-400"
                          >
                            <RefreshCw className={`h-4 w-4 ${reprocessMutation.isPending ? "animate-spin" : ""}`} />
                          </button>
                        )}
                        <Link
                          to={getDetailsPath(item.id)}
                          title="View Details"
                          aria-label="View Details"
                          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                        >
                          <Eye className="h-4 w-4" />
                        </Link>
                        {canWrite && (
                          <button
                            type="button"
                            onClick={() => triggerDelete(item.id)}
                            disabled={deleteMutation.isPending}
                            title="Delete Document"
                            aria-label="Delete Document"
                            className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:pointer-events-none disabled:opacity-50"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </>
          )}
        </div>
      </div>

      {canWrite && workspaceId && selectedIds.length > 0 && (
        <BulkActionBar
          workspaceId={workspaceId}
          selectedIds={selectedIds}
          onClear={() => setSelectedIds([])}
          onDone={(result) => {
            // Rows that were refused stay selected, so they can be acted on again.
            const refused = new Set(
              result.results.filter((row) => row.outcome === "refused").map((row) => row.work_item_id),
            );
            setSelectedIds((current) => current.filter((id) => refused.has(id)));
          }}
        />
      )}

      <footer className="documents-pagination flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <p className="tabular-nums" aria-live="polite">{response?.total ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, response.total)} of ${response.total.toLocaleString()} documents` : "0 documents"}</p>
        <nav aria-label="Document pagination" className="flex items-center gap-1.5">
          <button type="button" aria-label="Previous page" className="fp-btn fp-btn-secondary h-8 px-2" disabled={currentPage === 1 || isFetching} onClick={() => updateParams({ page: String(currentPage - 1) })}><ChevronLeft className="h-4 w-4" /><span className="sr-only">Previous</span></button>
          {Array.from({ length: Math.min(5, totalPages) }, (_, i) => Math.max(1, Math.min(currentPage - 2, totalPages - 4)) + i).map((page) => <button type="button" key={page} aria-label={`Page ${page}`} aria-current={currentPage === page ? "page" : undefined} className={`fp-btn h-8 min-w-8 px-2 ${currentPage === page ? "fp-btn-primary" : "fp-btn-secondary"}`} disabled={isFetching} onClick={() => updateParams({ page: String(page) })}>{page}</button>)}
          <button type="button" aria-label="Next page" className="fp-btn fp-btn-secondary h-8 px-2" disabled={currentPage >= totalPages || isFetching} onClick={() => updateParams({ page: String(currentPage + 1) })}><ChevronRight className="h-4 w-4" /><span className="sr-only">Next</span></button>
        </nav>
        <label className="flex items-center gap-2">Rows per page<select aria-label="Rows per page" value={pageSize} className="fp-input h-8 w-16" onChange={(event) => updateParams({ page: undefined, pageSize: event.target.value })}><option>10</option><option>25</option><option>50</option></select></label>
      </footer>

      <ConfirmDialog
        open={reprocessDialogOpen}
        title="Reprocess Document"
        message="This will queue the document for processing again. Existing extracted results may be replaced after processing completes."
        confirmText="Reprocess"
        cancelText="Cancel"
        loading={reprocessMutation.isPending}
        onConfirm={confirmReprocess}
        onCancel={() => {
          if (!reprocessMutation.isPending) {
            setReprocessDialogOpen(false);
            setSelectedReprocessWorkItemId(null);
          }
        }}
      />
      <ConfirmDialog
        open={deleteDialogOpen}
        title="Delete Document"
        message="This will permanently delete the uploaded file, extracted data, embeddings, and all related processing history. This action cannot be undone."
        confirmText="Delete"
        cancelText="Cancel"
        loading={deleteMutation.isPending}
        onConfirm={confirmDelete}
        onCancel={() => {
          if (!deleteMutation.isPending) {
            setDeleteDialogOpen(false);
            setSelectedWorkItemId(null);
          }
        }}
      />
    </div>
  );
};

WorkItems.displayName = "WorkItems";
export default WorkItems;
