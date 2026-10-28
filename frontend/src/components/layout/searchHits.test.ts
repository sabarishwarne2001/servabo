/** Where each kind of global-search result opens. */
import { describe, expect, it } from "vitest";

import type { SearchHit, SearchResponse } from "@/services/api/search";

import { HIT_SECTION, allSearchHits, searchHitPath } from "./searchHits";

const hit = (kind: SearchHit["kind"], over: Partial<SearchHit> = {}): SearchHit => ({
  kind,
  id: "11111111-2222-3333-4444-555555555555",
  title: "Title",
  subtitle: null,
  workspace_id: "w1",
  workspace_slug: "branch",
  workspace_name: "Branch office",
  reference: null,
  ...over,
});

describe("searchHitPath", () => {
  it("opens a GST supplier on the invoice list narrowed to its GSTIN", () => {
    expect(searchHitPath("acme", hit("GST_SUPPLIER", { reference: "27AABCS5555K1ZV" }))).toBe(
      "/acme/branch/gst?tab=invoices&supplier=27AABCS5555K1ZV",
    );
  });

  it("opens a GST invoice on the invoice list narrowed to its number, encoded", () => {
    expect(searchHitPath("acme", hit("GST_INVOICE", { reference: "INV/2026 #1" }))).toBe(
      "/acme/branch/gst?tab=invoices&number=INV%2F2026%20%231",
    );
  });

  it("falls back to the title when a GST hit carries no reference", () => {
    expect(searchHitPath("acme", hit("GST_INVOICE", { title: "INV-9" }))).toContain("number=INV-9");
  });

  it("opens an automation rule on its workspace's Workflows page", () => {
    expect(searchHitPath("acme", hit("RULE"))).toBe("/acme/branch/automation");
  });

  it("keeps the older kinds where they were", () => {
    expect(searchHitPath("acme", hit("DOCUMENT"))).toBe("/acme/branch/work-items/11111111-2222-3333-4444-555555555555");
    expect(searchHitPath("acme", hit("CASE"))).toContain("/acme/branch/cases/");
    expect(searchHitPath("acme", hit("ENTITY"))).toContain("/acme/branch/entities/");
  });
});

describe("the sections and the order", () => {
  it("names every kind in plain words", () => {
    expect(Object.values(HIT_SECTION)).toEqual(["Documents", "Entities", "Cases", "GST suppliers", "GST invoices", "TDS credit", "Workflows"]);
  });

  it("lists documents first and tolerates a response from an older server", () => {
    const response = {
      query: "x",
      workspaces_searched: 1,
      documents: [hit("DOCUMENT")],
      entities: [],
      cases: [hit("CASE")],
      suppliers: [hit("GST_SUPPLIER")],
      gst_invoices: [],
      rules: [hit("RULE")],
    } satisfies SearchResponse;
    expect(allSearchHits(response).map((h) => h.kind)).toEqual(["DOCUMENT", "CASE", "GST_SUPPLIER", "RULE"]);
    const old = { query: "x", workspaces_searched: 1, documents: [hit("DOCUMENT")], entities: [], cases: [] } as unknown as SearchResponse;
    expect(allSearchHits(old)).toHaveLength(1);
  });
});

describe("TDS credit cases", () => {
  it("opens the case in its workspace's TRINETRA page and sorts after the GST invoices", () => {
    const tds = hit("TDS_CASE", { id: "11111111-2222-3333-4444-555555555555", reference: "INV-1" });
    expect(searchHitPath("acme", tds)).toBe("/acme/branch/trinetra?case=11111111-2222-3333-4444-555555555555");
    const response = {
      query: "x",
      workspaces_searched: 1,
      documents: [],
      entities: [],
      cases: [],
      suppliers: [],
      gst_invoices: [hit("GST_INVOICE")],
      tds_cases: [tds],
      rules: [hit("RULE")],
    } satisfies SearchResponse;
    expect(allSearchHits(response).map((h) => h.kind)).toEqual(["GST_INVOICE", "TDS_CASE", "RULE"]);
  });
});
