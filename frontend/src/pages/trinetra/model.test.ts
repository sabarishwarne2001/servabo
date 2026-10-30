import { describe, expect, it } from "vitest";
import type { CreditCase } from "@/services/api/trinetra";
import {
  barPercent,
  byConfidence,
  confidenceOf,
  evidenceChecklist,
  freshness,
  statusTone,
  statusWords,
  waterfall,
} from "./model";

const base: CreditCase = {
  id: "c1",
  counterparty: "Acme",
  reference: "INV-1",
  year: 2025,
  status: "POSSIBLE_MISSING_POSTING",
  revision: 1,
  source_current: true,
  age_days: 3,
  expected_micros: "2000000000",
  posted_micros: "0",
  gap_micros: "2000000000",
  bank_micros: "148000000000",
  gross_micros: "150000000000",
  note: "",
  rule_version: "v",
  as_of: "2026-10-01T00:00:00Z",
};

describe("how a statement came in", () => {
  it("separates typed, template, unverified and verified readers", () => {
    const reader = (key: string, official: boolean, verified: boolean) => ({
      key,
      label: key,
      official,
      verified,
    });
    expect(confidenceOf(null)).toBe("none");
    expect(confidenceOf(reader("human-transcription-v1", false, true))).toBe("typed");
    expect(confidenceOf(reader("servabo-template-v1", false, true))).toBe("template");
    expect(confidenceOf(reader("form26as-text-v1", true, false))).toBe("unverified");
    expect(confidenceOf(reader("form26as-text-v1", true, true))).toBe("verified");
  });

  it("splits the gap by confidence and leaves a closed case's gap out", () => {
    const typed = {
      key: "human-transcription-v1",
      label: "Rows typed by hand",
      official: false,
      verified: true,
    };
    const rows = byConfidence([
      { ...base, statement_reader: typed },
      { ...base, id: "c2", statement_reader: typed, status: "WITHDRAWN" },
      { ...base, id: "c3", statement_reader: null },
    ]);
    expect(rows.map((r) => [r.confidence, r.cases, r.gapMicros])).toEqual([
      ["typed", 2, 2_000_000_000n],
      ["none", 1, 2_000_000_000n],
    ]);
  });
});

describe("words", () => {
  it("names every status in plain words and never calls a gap money", () => {
    expect(statusWords("POSSIBLE_MISSING_POSTING")).toBe("Possible missing posting");
    expect(statusWords("SOMETHING_NEW")).toBe("something new");
    expect(statusTone("POSTED")).toBe("ok");
    expect(statusTone("AMOUNT_MISMATCH")).toBe("danger");
    expect(statusTone("PENDING_REPORT")).toBe("info");
    expect(statusTone("WITHDRAWN")).toBe("neutral");
  });
});

describe("the waterfall", () => {
  it("runs gross, cash, withheld, posted and what is left to check, with bars scaled to the largest", () => {
    const steps = waterfall(base);
    expect(steps.map((s) => s.key)).toEqual(["gross", "bank", "withheld", "posted", "gap"]);
    expect(steps.map((s) => s.micros)).toEqual([
      150_000_000_000n,
      148_000_000_000n,
      2_000_000_000n,
      0n,
      2_000_000_000n,
    ]);
    expect(barPercent(steps, steps[0]!)).toBe(100);
    expect(barPercent(steps, steps[1]!)).toBe(98);
    expect(barPercent(steps, steps[3]!)).toBe(0);
  });

  it("keeps an unknown figure unknown and uses the gross after credit notes", () => {
    const steps = waterfall({
      ...base,
      bank_micros: null,
      gap_micros: null,
      adjusted_gross_micros: "100000000000",
      credit_notes_micros: "50000000000",
    });
    expect(steps[0]!.micros).toBe(100_000_000_000n);
    expect(steps[0]!.note).toContain("credit notes");
    expect(steps[1]!.micros).toBeNull();
    expect(steps[4]!.micros).toBeNull();
    expect(barPercent(steps, steps[1]!)).toBe(0);
  });
});

describe("the evidence checklist", () => {
  it("says what is present, missing or stale", () => {
    const list = evidenceChecklist({
      ...base,
      source_current: false,
      bank_micros: null,
      statement_reader: { key: "x", label: "x", official: false, verified: true },
      review: {
        evidence: [
          { work_item_id: "a", kind: "DEDUCTOR_ADVICE", current: true },
          { work_item_id: "b", kind: "CREDIT_NOTE", current: false },
        ],
      },
    });
    const by = Object.fromEntries(list.map((i) => [i.key, i.state]));
    expect(by).toEqual({
      invoice: "stale",
      bank: "missing",
      advice: "done",
      books: "missing",
      notes: "stale",
      statement: "done",
    });
  });
});

describe("the freshness banner", () => {
  const now = new Date("2026-10-28T00:00:00Z");
  it("is quiet when the evidence is current and loud when it is old or lost", () => {
    expect(freshness(null, [], now).level).toBe("none");
    expect(freshness("2026-10-20T00:00:00Z", [base], now)).toEqual({
      level: "ok",
      message: "Evidence as of 2026-10-20.",
    });
    const old = freshness("2026-08-01T00:00:00Z", [{ ...base, source_current: false }], now);
    expect(old.level).toBe("attention");
    expect(old.message).toContain("lost its evidence");
    expect(old.message).toContain("days old");
  });
});

describe("why live TDS credit is closed", () => {
  const open = { live_enabled: true, mode: "on", enrolled: false, entitled: true };
  it("says nothing when it is open and names each reason in words otherwise", async () => {
    const { accessNotice } = await import("./model");
    expect(accessNotice(open)).toBeNull();
    expect(
      accessNotice({ ...open, live_enabled: false, mode: "pilot", enrolled: false })?.kind,
    ).toBe("not_enrolled");
    expect(accessNotice({ ...open, live_enabled: false, mode: "off" })?.kind).toBe("off");
    expect(accessNotice({ ...open, live_enabled: false, mode: "on", entitled: false })?.kind).toBe(
      "not_entitled",
    );
    expect(
      accessNotice({ ...open, live_enabled: false, mode: "pilot", entitled: false })?.kind,
    ).toBe("not_entitled");
    expect(accessNotice({ ...open, live_enabled: false, mode: "pilot" })?.title).toContain("pilot");
  });
});

describe("the first-run tutorial", () => {
  it("ticks each step from what exists", async () => {
    const { tutorialSteps } = await import("./model");
    expect(
      tutorialSteps({ profiles: 0, items: [], hasStatement: false }).map((s) => s.done),
    ).toEqual([false, false, false, false]);
    const open = { ...base, review_state: "OPEN", status: "EVIDENCE_NEEDED" };
    expect(
      tutorialSteps({ profiles: 1, items: [open], hasStatement: true }).map((s) => s.done),
    ).toEqual([true, true, true, false]);
    expect(
      tutorialSteps({
        profiles: 1,
        items: [{ ...open, review_state: "CA_REVIEWED" }],
        hasStatement: true,
      }).at(-1)?.done,
    ).toBe(true);
  });
});

describe("how long a case has been open, in words", () => {
  it("says 1 day, not 1 days", async () => {
    const { daysOpen } = await import("./model");
    expect(daysOpen(0)).toBe("0 days open");
    expect(daysOpen(1)).toBe("1 day open");
    expect(daysOpen(2)).toBe("2 days open");
    expect(daysOpen(40)).toBe("40 days open");
  });
});

describe("the platform administrator's note under the access notice", () => {
  const closed = { live_enabled: false, mode: "pilot", enrolled: false, entitled: true };
  it("tells a platform administrator how to enrol an organization that is waiting for the pilot", async () => {
    const { operatorHint } = await import("./model");
    const hint = operatorHint(closed, true);
    expect(hint?.kind).toBe("enrol");
    expect(hint?.message).toContain("TRINETRA pilot console");
  });
  it("says the server setting is off when the mode is off", async () => {
    const { operatorHint } = await import("./model");
    const hint = operatorHint({ ...closed, mode: "off" }, true);
    expect(hint?.kind).toBe("mode_off");
    expect(hint?.message).toContain("TRINETRA_MODE");
  });
  it("says nothing to a customer, to an open organization, or where only the plan is missing", async () => {
    const { operatorHint } = await import("./model");
    expect(operatorHint(closed, false)).toBeNull();
    expect(operatorHint({ ...closed, live_enabled: true }, true)).toBeNull();
    expect(operatorHint({ ...closed, entitled: false }, true)).toBeNull();
  });
});
