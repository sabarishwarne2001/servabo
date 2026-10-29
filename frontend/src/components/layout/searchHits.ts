/**
 * Where each kind of global-search result opens, and what its section is called.
 *
 * Kept apart from the palette so the rules are plain functions with tests: a GST result opens the GST credit page's invoice
 * list already narrowed to it, a TDS credit case opens its case in that workspace's TRINETRA page (`?tab=invoices&supplier=` or `&number=`, which the list reads), an automation rule opens its
 * workspace's Workflows page, and the older kinds open their own page.
 */
import {
  automationPath,
  casePath,
  entityPath,
  gstPath,
  trinetraPath,
  workItemDetailsPath,
} from "@/routes/tenantPaths";
import type { SearchHit, SearchHitKind, SearchResponse } from "@/services/api/search";

export const HIT_SECTION: Readonly<Record<SearchHitKind, string>> = {
  DOCUMENT: "Documents",
  ENTITY: "Entities",
  CASE: "Cases",
  GST_SUPPLIER: "GST suppliers",
  GST_INVOICE: "GST invoices",
  TDS_CASE: "TDS credit",
  RULE: "Workflows",
};

export const searchHitPath = (orgSlug: string, hit: SearchHit): string => {
  switch (hit.kind) {
    case "DOCUMENT":
      return workItemDetailsPath(orgSlug, hit.workspace_slug, hit.id);
    case "ENTITY":
      return entityPath(orgSlug, hit.workspace_slug, hit.id);
    case "CASE":
      return casePath(orgSlug, hit.workspace_slug, hit.id);
    case "GST_SUPPLIER":
      return `${gstPath(orgSlug, hit.workspace_slug)}?tab=invoices&supplier=${encodeURIComponent(hit.reference ?? hit.title)}`;
    case "GST_INVOICE":
      return `${gstPath(orgSlug, hit.workspace_slug)}?tab=invoices&number=${encodeURIComponent(hit.reference ?? hit.title)}`;
    case "TDS_CASE":
      return `${trinetraPath(orgSlug, hit.workspace_slug)}?case=${encodeURIComponent(hit.id)}`;
    case "RULE":
      return automationPath(orgSlug, hit.workspace_slug);
  }
};

/** Every hit of a response in the order the palette lists them. */
export const allSearchHits = (response: SearchResponse): readonly SearchHit[] => [
  ...response.documents,
  ...response.entities,
  ...response.cases,
  ...(response.suppliers ?? []),
  ...(response.gst_invoices ?? []),
  ...(response.tds_cases ?? []),
  ...(response.rules ?? []),
];
