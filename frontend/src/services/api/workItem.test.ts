import { beforeEach, describe, expect, it, vi } from "vitest";
import { getDocumentCounts, getWorkItems } from "./workItem";
import apiClient from "./client";
vi.mock("./client", () => ({ default: { get: vi.fn() } }));

describe("document API contract", () => {
  beforeEach(() => vi.clearAllMocks());
  it("sends the server's offset, limit, sort and filter names and normalizes the total", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { items: [], page: 3, pageSize: 25, totalItems: 75, totalPages: 3 },
    });
    const result = await getWorkItems("workspace", {
      page: 3,
      pageSize: 25,
      sortBy: "file_size",
      sortOrder: "asc",
      fileFormat: "pdf",
      uploadedFrom: "2026-10-01",
      uploadedTo: "2026-10-02",
      search: " invoice ",
      status: "FAILED",
    });
    const params = vi.mocked(apiClient.get).mock.calls[0]?.[1]?.params as URLSearchParams;
    expect(Object.fromEntries(params)).toEqual({
      skip: "50",
      limit: "25",
      sort_by: "file_size",
      sort_order: "asc",
      file_format: "pdf",
      uploaded_from: "2026-10-01",
      uploaded_to: "2026-10-02",
      search: "invoice",
      status: "FAILED",
    });
    expect(result.total).toBe(75);
    expect(params.has("pageSize")).toBe(false);
  });
  it("fetches counts from the requested workspace", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { total: 4 } });
    expect((await getDocumentCounts("workspace-2")).total).toBe(4);
    expect(vi.mocked(apiClient.get).mock.calls[0]?.[0]).toContain("workspace-2/work-items/counts");
  });
});
