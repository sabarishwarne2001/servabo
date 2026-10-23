/**
 * What a zip's batch says, in plain words (Final session 1, 2A). Pure, so it is tested without a browser.
 *
 *   "38 documents added, 2 skipped: not a supported file type"
 *   "2 documents added, 3 not added: your plan's monthly limit"
 */
import type { Batch, BatchItem, SkippedFile } from "@/services/api/ingestion";

/** Codes the server writes on an item a plan or trial refused (never an error in the file itself). */
export const PLAN_REFUSAL_CODES: readonly string[] = ["PLAN_LIMIT", "TRIAL_ENDED"];

export interface ArchiveSummary {
  readonly finished: boolean;
  /** Documents the zip held (the archive's own row is not one). */
  readonly expected: number;
  readonly added: number;
  /** Refused by the plan: listed with the upgrade action, each whole or not at all. */
  readonly notAddedByPlan: readonly BatchItem[];
  /** Failed for a reason in the file itself (unreadable, too many pages, ...). */
  readonly failed: readonly BatchItem[];
  readonly skipped: readonly SkippedFile[];
  readonly sentence: string;
}

const plural = (count: number, one: string, many: string): string => `${count} ${count === 1 ? one : many}`;

const skippedReason = (skipped: readonly SkippedFile[]): string => {
  const gstr = skipped.filter((file) => file.code === "GSTR2B").length;
  const other = skipped.length - gstr;
  const parts: string[] = [];
  if (other > 0) {
    parts.push(gstr > 0 ? plural(other, "not a supported file type", "not a supported file type") : "not a supported file type");
  }
  if (gstr > 0) {
    parts.push(gstr === 1 ? "a GSTR-2B file, import it on the GST credit page" : `${gstr} GSTR-2B files, import them on the GST credit page`);
  }
  return parts.join("; ");
};

export const summariseArchive = (batch: Batch): ArchiveSummary => {
  // The zip's own row is "archive:<id>"; the documents it held are "archive:<id>:<n>".
  const members = batch.items.filter((item) => item.client_key.split(":").length > 2);
  const added = members.filter((item) => item.work_item_id).length;
  const notAddedByPlan = members.filter((item) => item.status === "FAILED" && PLAN_REFUSAL_CODES.includes(item.error_code ?? ""));
  const failed = members.filter((item) => item.status === "FAILED" && !PLAN_REFUSAL_CODES.includes(item.error_code ?? ""));
  const skipped = batch.skipped ?? [];
  const terminal = ["COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED"].includes(batch.status);
  const parts: string[] = [plural(added, "document added", "documents added")];
  if (skipped.length > 0) {
    parts.push(`${skipped.length} skipped: ${skippedReason(skipped)}`);
  }
  if (notAddedByPlan.length > 0) {
    parts.push(`${notAddedByPlan.length} not added: your plan's monthly limit`);
  }
  if (failed.length > 0) {
    parts.push(`${failed.length} could not be read`);
  }
  return {
    finished: terminal,
    expected: members.length,
    added,
    notAddedByPlan,
    failed,
    skipped,
    sentence: parts.join(", "),
  };
};
