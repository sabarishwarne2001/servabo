import { describe, expect, it } from "vitest";

import type { Batch, BatchItem } from "@/services/api/ingestion";

import { summariseArchive } from "./archiveSummary";

const item = (over: Partial<BatchItem> & { filename: string }): BatchItem => ({
  id: over.filename,
  client_key: over.client_key ?? `archive:x:${over.filename.length}${over.filename}`,
  size_bytes: 10,
  status: "COMPLETED",
  ...over,
});

const batch = (over: Partial<Batch>): Batch => ({
  id: "b1",
  status: "COMPLETED",
  source: "ARCHIVE",
  total_items: 0,
  completed_items: 0,
  failed_items: 0,
  created_at: "2026-10-22T00:00:00Z",
  items: [],
  ...over,
});

describe("summariseArchive", () => {
  it("says how many were added and how many were skipped, and why", () => {
    const docs = Array.from({ length: 38 }, (_, i) => item({ filename: `d${i}.pdf`, work_item_id: `w${i}` }));
    const summary = summariseArchive(
      batch({
        items: [item({ filename: "all.zip", client_key: "archive:abc" }), ...docs],
        skipped: [
          { name: "a.txt", code: "UNSUPPORTED_TYPE", message: "x" },
          { name: "b.docx", code: "UNSUPPORTED_TYPE", message: "x" },
        ],
      }),
    );
    expect(summary.sentence).toBe("38 documents added, 2 skipped: not a supported file type");
    expect(summary.expected).toBe(38);
    expect(summary.finished).toBe(true);
  });

  it("lists a GSTR-2B file as something to import on the GST credit page", () => {
    const summary = summariseArchive(batch({ skipped: [{ name: "r.json", code: "GSTR2B", message: "x" }] }));
    expect(summary.sentence).toContain("1 skipped: a GSTR-2B file, import it on the GST credit page");
  });

  it("separates what the plan refused from what could not be read, and counts one document in the singular", () => {
    const summary = summariseArchive(
      batch({
        status: "COMPLETED_WITH_ERRORS",
        items: [
          item({ filename: "a.pdf", work_item_id: "w1" }),
          item({ filename: "b.pdf", status: "FAILED", error_code: "PLAN_LIMIT" }),
          item({ filename: "c.pdf", status: "FAILED", error_code: "PLAN_LIMIT" }),
          item({ filename: "d.pdf", status: "FAILED", error_code: "FILE_TYPE_MISMATCH" }),
        ],
      }),
    );
    expect(summary.sentence).toBe("1 document added, 2 not added: your plan's monthly limit, 1 could not be read");
    expect(summary.notAddedByPlan.map((i) => i.filename)).toEqual(["b.pdf", "c.pdf"]);
    expect(summary.failed.map((i) => i.filename)).toEqual(["d.pdf"]);
  });

  it("is not finished while the batch is still being unpacked", () => {
    expect(summariseArchive(batch({ status: "PROCESSING" })).finished).toBe(false);
  });
});
