/**
 * What the TRINETRA screens say, as plain functions with tests: the words for a status, how much to trust the statement a case was
 * compared with, the amount waterfall (gross, bank, withheld, posted, gap), the evidence checklist and the freshness banner.
 *
 * Every amount is a string of millionths of a rupee, as the server writes it (a ₹ figure can exceed 2^53 millionths), so the sums
 * here use BigInt. A gap is an item to check: it is never called a refund, a loss or money, and a missing figure stays missing.
 */
import type { CreditCase, StatementReader } from "@/services/api/trinetra";

export const STATUS_WORDS: Readonly<Record<string, string>> = {
  POSTED: "Posted in your statement",
  LATE_POSTING: "Posted late",
  VERIFIED_CORRECTED: "Posted after a correction",
  AMOUNT_MISMATCH: "Amount differs",
  DUPLICATE_SUSPECTED: "Possible duplicate rows",
  AMBIGUOUS: "More than one possible match",
  SUGGESTED: "A match to confirm",
  TAN_MISMATCH_SUSPECTED: "Same invoice under another TAN",
  POSSIBLE_MISSING_POSTING: "Possible missing posting",
  EVIDENCE_NEEDED: "Evidence needed",
  PENDING_REPORT: "Waiting for a statement",
  DISPUTED: "Disputed",
  WITHDRAWN: "Withdrawn",
  CLOSED_WITH_EXCEPTION: "Closed with an explanation",
  UNRESOLVED: "Left unresolved",
};

export const statusWords = (status: string): string =>
  STATUS_WORDS[status] ?? status.toLowerCase().replaceAll("_", " ");

export type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral";

export const statusTone = (status: string): StatusTone => {
  if (["POSTED", "LATE_POSTING", "VERIFIED_CORRECTED"].includes(status)) {
    return "ok";
  }
  if (["POSSIBLE_MISSING_POSTING", "AMOUNT_MISMATCH", "TAN_MISMATCH_SUSPECTED"].includes(status)) {
    return "danger";
  }
  if (
    ["DUPLICATE_SUSPECTED", "AMBIGUOUS", "SUGGESTED", "EVIDENCE_NEEDED", "DISPUTED"].includes(
      status,
    )
  ) {
    return "warn";
  }
  if (status === "PENDING_REPORT") {
    return "info";
  }
  return "neutral";
};

/** How the statement a case was compared with came in, from the least to the most checked. */
export type Confidence = "none" | "typed" | "template" | "unverified" | "verified";

export const CONFIDENCE_ORDER: readonly Confidence[] = [
  "verified",
  "unverified",
  "template",
  "typed",
  "none",
];

export const CONFIDENCE_WORDS: Readonly<Record<Confidence, string>> = {
  verified: "Official download, verified reader",
  unverified: "Official download, unverified reader",
  template: "Servabo template (your transcription)",
  typed: "Rows typed by hand",
  none: "No statement imported",
};

export const CONFIDENCE_HINTS: Readonly<Record<Confidence, string>> = {
  verified: "A reader proven on a real downloaded file.",
  unverified:
    "Read by a layout that has not yet been proven on a real file: check the rows against your statement.",
  template: "Read as you typed it into the template. It is not an official format.",
  typed: "Read as you typed it. It is not an official format.",
  none: "No active statement: a missing import says nothing about missing tax credit.",
};

export const confidenceOf = (
  reader: CreditCase["statement_reader"] | StatementReader | null | undefined,
): Confidence => {
  if (!reader) {
    return "none";
  }
  if (reader.official) {
    return reader.verified ? "verified" : "unverified";
  }
  return reader.key.startsWith("servabo-template") ? "template" : "typed";
};

const micros = (value: string | number | null | undefined): bigint | null => {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  try {
    return BigInt(value);
  } catch {
    return null;
  }
};

export const sumMicros = (values: readonly (string | number | null | undefined)[]): bigint =>
  values.reduce<bigint>((total, value) => total + (micros(value) ?? 0n), 0n);

export interface ConfidenceRow {
  readonly confidence: Confidence;
  readonly cases: number;
  readonly gapMicros: bigint;
}

/** The headline figures split by how much the statement behind them can be trusted. Closed cases keep no gap. */
export const byConfidence = (items: readonly CreditCase[]): readonly ConfidenceRow[] => {
  const rows = new Map<Confidence, { cases: number; gap: bigint }>();
  for (const item of items) {
    const key = confidenceOf(item.statement_reader);
    const row = rows.get(key) ?? { cases: 0, gap: 0n };
    row.cases += 1;
    if (!["WITHDRAWN", "CLOSED_WITH_EXCEPTION", "UNRESOLVED"].includes(item.status)) {
      row.gap += micros(item.gap_micros) ?? 0n;
    }
    rows.set(key, row);
  }
  return CONFIDENCE_ORDER.filter((key) => rows.has(key)).map((key) => ({
    confidence: key,
    cases: rows.get(key)?.cases ?? 0,
    gapMicros: rows.get(key)?.gap ?? 0n,
  }));
};

export interface WaterfallStep {
  readonly key: "gross" | "bank" | "withheld" | "posted" | "gap";
  readonly label: string;
  readonly micros: bigint | null;
  readonly note: string;
}

/** Gross invoice, cash received, tax withheld (the confirmed expectation), posted in the statement, and what is left to check. */
export const waterfall = (c: CreditCase): readonly WaterfallStep[] => {
  const gross = micros(c.adjusted_gross_micros) ?? micros(c.gross_micros);
  const notes = micros(c.credit_notes_micros) ?? 0n;
  return [
    {
      key: "gross",
      label: "Invoice gross",
      micros: gross,
      note: notes > 0n ? "After the credit notes you attached." : "As read from the invoice.",
    },
    {
      key: "bank",
      label: "Cash received",
      micros: micros(c.bank_micros),
      note: "From the bank lines Helm matched; a shortfall alone is never proof of TDS.",
    },
    {
      key: "withheld",
      label: "Tax withheld (confirmed)",
      micros: micros(c.expected_micros),
      note: "What a person confirmed from the invoice, advice or accounting record.",
    },
    {
      key: "posted",
      label: "Posted in the statement",
      micros: micros(c.posted_micros),
      note: "Only rows a person allocated to this case.",
    },
    {
      key: "gap",
      label: "Left to check",
      micros: micros(c.gap_micros),
      note: "An item to check. Not a refund, and not money.",
    },
  ];
};

/** The width of a step's bar as a whole percent of the largest step (0 when unknown). */
export const barPercent = (steps: readonly WaterfallStep[], step: WaterfallStep): number => {
  const largest = steps.reduce<bigint>(
    (m, s) => (s.micros !== null && s.micros > m ? s.micros : m),
    0n,
  );
  if (step.micros === null || largest === 0n) {
    return 0;
  }
  return Number((step.micros * 100n) / largest);
};

export type ChecklistState = "done" | "missing" | "stale";

export interface ChecklistItem {
  readonly key: string;
  readonly label: string;
  readonly state: ChecklistState;
  readonly note: string;
}

const hasEvidence = (c: CreditCase, kind: string): ChecklistState => {
  const found = (c.review?.evidence ?? []).filter((e) => e.kind === kind);
  if (!found.length) {
    return "missing";
  }
  return found.some((e) => e.current) ? "done" : "stale";
};

/** What a reviewer would want on the table before closing the case, and which of it is current. */
export const evidenceChecklist = (c: CreditCase): readonly ChecklistItem[] => [
  {
    key: "invoice",
    label: "Invoice",
    state: c.source_current ? "done" : "stale",
    note: c.source_current
      ? "Still the invoice the withholding was confirmed on."
      : "The invoice changed: reconfirm the withholding.",
  },
  {
    key: "bank",
    label: "Bank receipt",
    state: micros(c.bank_micros) === null ? "missing" : "done",
    note: "Helm's matched bank lines.",
  },
  {
    key: "advice",
    label: "Deduction advice from the customer",
    state: hasEvidence(c, "DEDUCTOR_ADVICE"),
    note: "Form 16A or a withholding advice.",
  },
  {
    key: "books",
    label: "Accounting record",
    state: hasEvidence(c, "ACCOUNTING_RECORD"),
    note: "A voucher or a payment with tax withheld.",
  },
  {
    key: "notes",
    label: "Credit notes",
    state: hasEvidence(c, "CREDIT_NOTE"),
    note: "Only when the invoice was credited.",
  },
  {
    key: "statement",
    label: "Statement",
    state: c.statement_reader ? "done" : "missing",
    note: c.statement_reader ? "An active statement snapshot." : "Nothing imported yet.",
  },
];

export type FreshnessLevel = "none" | "ok" | "attention";

export interface Freshness {
  readonly level: FreshnessLevel;
  readonly message: string;
}

export const STALE_AFTER_DAYS = 45;

/** The banner above the cases: how old the evidence is, and how many confirmations lost theirs. */
export const freshness = (
  asOf: string | null,
  items: readonly CreditCase[],
  now: Date = new Date(),
): Freshness => {
  const changed = items.filter((c) => !c.source_current).length;
  if (!asOf) {
    return { level: "none", message: "No statement has been imported yet." };
  }
  const days = Math.floor((now.getTime() - new Date(asOf).getTime()) / 86_400_000);
  const parts: string[] = [];
  if (changed) {
    parts.push(
      `${changed} ${changed === 1 ? "case lost its" : "cases lost their"} evidence: the invoice changed after it was confirmed.`,
    );
  }
  if (days > STALE_AFTER_DAYS) {
    parts.push(`The statement is ${days} ${days === 1 ? "day" : "days"} old; a later posting needs a new import.`);
  }
  return parts.length
    ? { level: "attention", message: parts.join(" ") }
    : { level: "ok", message: `Evidence as of ${asOf.slice(0, 10)}.` };
};

export interface AccessNotice {
  readonly kind: "not_entitled" | "not_enrolled" | "off";
  readonly title: string;
  readonly message: string;
}

/** Why live TRINETRA is not open for this organization, in plain words; null when it is open. Mirrors the server's `live_for`. */
export const accessNotice = (access: {
  live_enabled: boolean;
  mode: string;
  enrolled: boolean;
  entitled: boolean;
}): AccessNotice | null => {
  if (access.live_enabled && access.entitled) {
    return null;
  }
  if (access.mode === "off") {
    return {
      kind: "off",
      title: "Live TDS credit is not open yet",
      message:
        "Servabo is still checking the official statement layouts with a tax adviser. Explore the synthetic examples meanwhile.",
    };
  }
  if (!access.entitled) {
    return {
      kind: "not_entitled",
      title: "TDS credit comes with Business and Enterprise",
      message:
        "Your plan shows the synthetic examples. On Business, check whether the tax your customers withheld reached your statement.",
    };
  }
  return {
    kind: "not_enrolled",
    title: "TRINETRA is in a pilot, and your organization is not enrolled yet",
    message:
      "Explore the synthetic examples. Servabo will open it to Business and Enterprise organizations when the pilot ends.",
  };
};

/** "1 day open", "2 days open". */
export const daysOpen = (days: number): string => `${days} ${days === 1 ? "day" : "days"} open`;

export interface TutorialStep {
  readonly key: "profile" | "case" | "statement" | "decide";
  readonly title: string;
  readonly done: boolean;
  readonly hint: string;
  readonly tab: "cases" | "statements" | "suggestions";
}

/** The first-run path for a live organization. Each step ticks from what exists, never from a click. */
export const tutorialSteps = (input: {
  profiles: number;
  items: readonly CreditCase[];
  hasStatement: boolean;
}): readonly TutorialStep[] => [
  {
    key: "profile",
    title: "Add the legal entity whose tax your customers withhold",
    done: input.profiles > 0,
    hint: "A name and a PAN. The PAN is stored encrypted and shown masked.",
    tab: "statements",
  },
  {
    key: "case",
    title: "Confirm one invoice where a customer withheld tax",
    done: input.items.length > 0,
    hint: "Accept a suggestion read from an invoice, or confirm one yourself.",
    tab: "suggestions",
  },
  {
    key: "statement",
    title: "Import your tax statement",
    done: input.hasStatement,
    hint: "From the Servabo template, a Form 26AS or Form 168 text file, or an AIS CSV. You check the preview first.",
    tab: "statements",
  },
  {
    key: "decide",
    title: "Review one case and record what you decided",
    done: input.items.some((c) => (c.review_state ?? "OPEN") !== "OPEN" || c.status === "POSTED"),
    hint: "Allocate a posting, explain the difference or close it, with a reason.",
    tab: "cases",
  },
];
