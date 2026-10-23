import { describe, expect, it } from "vitest";
import { documentFormatLabel, readDocumentFilters } from "./documentFilters";

describe("document console URLs", () => {
  it("restores the entire query from a shared link", () => {
    expect(
      readDocumentFilters(
        new URLSearchParams(
          "page=3&pageSize=25&search=invoice&status=COMPLETED&format=pdf&from=2026-10-01&to=2026-10-12&sort=file_size&order=asc",
        ),
      ),
    ).toEqual({
      page: 3,
      pageSize: 25,
      search: "invoice",
      status: "COMPLETED",
      fileFormat: "pdf",
      uploadedFrom: "2026-10-01",
      uploadedTo: "2026-10-12",
      sortBy: "file_size",
      sortOrder: "asc",
    });
  });
  it("rejects invalid pages, sort fields, dates and status categories", () => {
    expect(
      readDocumentFilters(
        new URLSearchParams(
          "page=-1&pageSize=200&status=REVIEW&format=exe&sort=__proto__&from=2026-02-30&to=nope",
        ),
      ),
    ).toEqual({ page: 1, pageSize: 10, sortBy: "created_at", sortOrder: "desc" });
  });
  it("drops reversed end dates and bounds page sizes and query length", () => {
    const filters = readDocumentFilters(
      new URLSearchParams({
        page: "Infinity",
        search: "a".repeat(500),
        from: "2026-10-02",
        to: "2026-10-01",
      }),
    );
    expect(filters.page).toBe(1);
    expect(filters.search).toHaveLength(100);
    expect(filters.uploadedTo).toBeUndefined();
  });
  it("uses concise names for OOXML MIME types", () => {
    expect(
      documentFormatLabel(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ),
    ).toBe("DOCX");
    expect(
      documentFormatLabel("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ).toBe("XLSX");
    expect(documentFormatLabel("image/png")).toBe("PNG");
  });
});
