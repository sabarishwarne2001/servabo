import { describe, expect, it } from "vitest";

import type { AutomationRule } from "@/types/automation";
import type { FlowCatalog } from "@/types/automationFlow";
import type { Recipe } from "@/types/automationVolume";
import { matchesRecipe } from "@/components/automation/RecipeGallery";
import {
  applyFillIns,
  conditionText,
  draftFromPayload,
  draftFromRule,
  emptyDraft,
  localIssues,
  payloadFromDraft,
  sameDraft,
  summarize,
  valueText,
  type ConditionDraft,
  type FlowDraft,
} from "./flowModel";
import { matchesTrigger } from "./TriggerCard";

const catalog = {
  triggers: [
    {
      key: "document.completed", label: "Document processed", category: "Documents", description: "A document was read.",
      event_types: ["work_item.enriched"], fields: [], capability: null, has_document: true, excluded_actions: [],
      runs_during_review: false, available: true, summary: "Every time a document is read.",
    },
    {
      key: "anomaly.detected", label: "Anomaly detected", category: "Compliance", description: "Forensic audit found something.",
      event_types: ["anomaly.detected"], capability: null, has_document: true, excluded_actions: [], runs_during_review: false,
      available: true,
      fields: [{ key: "event.severity", label: "Severity", type: "string", example: "HIGH", description: "", source: "event",
        options: [{ value: "HIGH", label: "High" }, { value: "LOW", label: "Low" }] }],
    },
  ],
  actions: [
    {
      type: "notify.role", label: "Notify a role", description: "", category: "Notify", capability: null, addon: null,
      minimum_role: "WORKSPACE_ADMIN", available: true, unavailable_reason: null, commercial: true, needs_document: false,
      template_fields: [], aliases: [], config_schema: { properties: { roles: { type: "array" } }, required: ["roles"] },
    },
  ],
  operators: { string: ["EQUALS", "IN"], number: ["EQUALS"], money: ["GREATER_THAN", "BETWEEN"], boolean: ["EQUALS"], array: ["CONTAINS"], date: ["BEFORE", "OLDER_THAN_DAYS"] },
  valueless_operators: ["EXISTS", "IS_EMPTY", "IS_NOT_EMPTY"],
  template_variables: [],
  document_fields: [
    { key: "total_amount", label: "Total amount", type: "money", example: "118000.00", description: "", source: "document" },
    { key: "invoice_date", label: "Invoice date", type: "date", example: "2026-10-01", description: "", source: "document" },
  ],
  resources: {
    webhook_endpoints: [], warehouse_destinations: [], redaction_profiles: [], organization_roles: [], export_datasets: [],
    mutable_fields: [], erp_targets: [], erp_object_kinds: [],
  },
  limits: { triggers: 4, groups: 10, conditions_per_group: 20, actions_per_branch: 10 },
} as unknown as FlowCatalog;

const condition = (patch: Partial<ConditionDraft>): ConditionDraft => ({
  uid: "c", field: "total_amount", operator: "GREATER_THAN", value: "1000000", currency: "INR", ...patch,
});

const draftWith = (conditions: ConditionDraft[]): FlowDraft => ({
  ...emptyDraft(),
  name: "Big invoices",
  triggers: ["document.completed"],
  groups: [{ uid: "g", logic_operator: "AND", conditions }],
  actions: [{ uid: "a", action_type: "notify.role", config: { roles: ["ADMIN"] } }],
});

describe("valueText", () => {
  it("shows an amount with its currency and a list in words", () => {
    expect(valueText("GREATER_THAN", "1000000", "INR")).toBe("10,00,000 INR");
    expect(valueText("GREATER_THAN", "1000000", "USD")).toBe("1,000,000 USD");
    expect(valueText("GREATER_THAN", "₹10,00,000", "INR")).toBe("₹10,00,000 INR");
    expect(valueText("GREATER_THAN", "1180.50", "INR")).toBe("1,180.50 INR");
    expect(valueText("IN", ["Acme, Inc", "Beta"])).toBe("Acme, Inc or Beta");
    expect(valueText("IN", ["a", "b", "c"])).toBe("a, b or c");
    expect(valueText("BETWEEN", ["5", "10"], "USD")).toBe("5 and 10 USD");
    expect(valueText("BETWEEN", ["50000", "200000"], "INR")).toBe("50,000 and 2,00,000 INR");
  });
  it("counts days and says nothing for an empty value", () => {
    expect(valueText("OLDER_THAN_DAYS", "30")).toBe("30 days");
    expect(valueText("OLDER_THAN_DAYS", "1")).toBe("1 day");
    expect(valueText("EQUALS", "")).toBe("");
    expect(valueText("IN", [])).toBe("");
  });
});

describe("the sentence builder", () => {
  it("reads one condition as a person would say it", () => {
    expect(conditionText(catalog, condition({}))).toBe("total amount is greater than 10,00,000 INR");
    expect(conditionText(catalog, condition({ operator: "EXISTS", value: "" }))).toBe("total amount exists");
    expect(conditionText(catalog, condition({ field: "invoice_date", operator: "OLDER_THAN_DAYS", value: "30", currency: "" })))
      .toBe("invoice date is older than 30 days");
  });
  it("names an empty rule without calling it ready, and never prints an ellipsis for it", () => {
    const sentence = summarize(emptyDraft(), catalog);
    expect(sentence).toContain("(pick when it runs)");
    expect(sentence).toContain("(add what it does)");
    expect(sentence).not.toContain("…");
  });
  it("puts trigger, conditions, steps and otherwise in one sentence", () => {
    const draft: FlowDraft = {
      ...draftWith([condition({})]),
      else_actions: [{ uid: "e", action_type: "notify.role", config: { roles: ["OWNER"] } }],
    };
    expect(summarize(draft, catalog)).toBe(
      "When document processed, if total amount is greater than 10,00,000 INR: notify a role; otherwise notify a role.",
    );
  });
});

describe("the payload", () => {
  it("sends an amount with its currency and a list as a list", () => {
    const payload = payloadFromDraft(
      draftWith([condition({}), condition({ uid: "d", field: "event.severity", operator: "IN", value: ["HIGH", "LOW"], currency: "" })]),
      catalog,
    );
    const [first, second] = payload.condition_groups[0]?.conditions ?? [];
    expect(first).toEqual({ field: "total_amount", operator: "GREATER_THAN", value: "1000000", currency: "INR" });
    expect(second).toEqual({ field: "event.severity", operator: "IN", value: ["HIGH", "LOW"] });
  });
  it("sends the limits and the note only when they are set", () => {
    const base = payloadFromDraft(draftWith([]), catalog);
    expect(base.max_runs_per_hour).toBeNull();
    expect(base.cooldown_hours).toBeNull();
    expect("note" in base).toBe(false);
    const set = payloadFromDraft({ ...draftWith([]), max_runs_per_hour: 50, cooldown_hours: 24, note: " why " }, catalog);
    expect(set.max_runs_per_hour).toBe(50);
    expect(set.cooldown_hours).toBe(24);
    expect(set.note).toBe("why");
  });
  it("opens a stored rule and saves it back unchanged", () => {
    const rule = {
      id: "r", name: "Old rule", priority: 5, event: "document.completed", conditions: [], logic_operator: "AND",
      actions: [{ action_type: "notify.role", config: { roles: ["ADMIN"] } }], is_active: true, created_at: "", updated_at: "",
      triggers: ["document.completed"], groups_operator: "AND", else_actions: [], on_error: "HALT",
      condition_groups: [{ logic_operator: "AND", conditions: [{ field: "total_amount", operator: "GREATER_THAN", value: "5", currency: "INR" }] }],
      max_runs_per_hour: 20, cooldown_hours: null,
    } as unknown as AutomationRule;
    const draft = draftFromRule(rule, catalog, "edit");
    expect(draft.max_runs_per_hour).toBe(20);
    expect(draft.groups[0]?.conditions[0]?.currency).toBe("INR");
    expect(sameDraft(draft, draftFromRule(rule, catalog, "edit"), catalog)).toBe(true);
    expect(draftFromRule(rule, catalog, "duplicate").is_active).toBe(false);
  });
});

describe("local checks", () => {
  const messages = (draft: FlowDraft): string[] => localIssues(draft, catalog).map((issue) => issue.message);
  it("asks for a value, a low and a high, and a whole number of days", () => {
    expect(messages(draftWith([condition({ value: "" })]))).toContain("Enter a value.");
    expect(messages(draftWith([condition({ operator: "BETWEEN", value: ["5"] })]))).toContain("Give a low and a high value.");
    expect(messages(draftWith([condition({ operator: "OLDER_THAN_DAYS", value: "x", currency: "" })]))).toContain("Enter a whole number of days.");
    expect(messages(draftWith([condition({})]))).toEqual([]);
  });
  it("bounds the limits", () => {
    expect(messages({ ...draftWith([]), max_runs_per_hour: 0 }).some((m) => m.includes("hourly limit"))).toBe(true);
    expect(messages({ ...draftWith([]), cooldown_hours: 9000 }).some((m) => m.includes("cooldown"))).toBe(true);
    expect(messages({ ...draftWith([]), max_runs_per_hour: 100000, cooldown_hours: 1 })).toEqual([]);
  });
});

describe("recipes", () => {
  const rule = {
    name: "Post to chat", priority: 100, on_error: "CONTINUE", triggers: ["document.completed"], groups_operator: "AND",
    condition_groups: [], actions: [{ action_type: "notify.role", config: { roles: [] } }], else_actions: [],
  } as unknown as Parameters<typeof applyFillIns>[0];
  it("writes an answer at the path the recipe names and leaves the recipe itself alone", () => {
    const filled = applyFillIns(rule, { "actions.0.config.roles": "ADMIN" });
    expect((filled.actions[0]?.config as Record<string, unknown>).roles).toBe("ADMIN");
    expect((rule.actions[0]?.config as Record<string, unknown>).roles).toEqual([]);
  });
  it("opens as a draft that starts switched on", () => {
    const draft = draftFromPayload(rule, catalog);
    expect(draft.is_active).toBe(true);
    expect(draft.on_error).toBe("CONTINUE");
    expect(draft.actions).toHaveLength(1);
  });
  it("gets the default priority when the recipe carries none, so the builder can save it", () => {
    const { priority: _unused, ...withoutPriority } = rule as unknown as Record<string, unknown>;
    const draft = draftFromPayload(withoutPriority as unknown as Parameters<typeof applyFillIns>[0], catalog);
    expect(draft.priority).toBe(100);
  });
  it("is found by what it is about", () => {
    const recipe = { title: "Hold invoices above ₹10 lakh", summary: "Waits for a person.", category: "Invoices", trigger_labels: ["Document processed"] } as unknown as Recipe;
    expect(matchesRecipe(recipe, "lakh", "All")).toBe(true);
    expect(matchesRecipe(recipe, "processed", "All")).toBe(true);
    expect(matchesRecipe(recipe, "", "GST")).toBe(false);
    expect(matchesRecipe(recipe, "slack", "All")).toBe(false);
  });
});

describe("the trigger search", () => {
  const [documents, anomaly] = catalog.triggers;
  it("matches the name, the category, the summary and the description", () => {
    expect(matchesTrigger(documents!, "processed")).toBe(true);
    expect(matchesTrigger(documents!, "documents")).toBe(true);
    expect(matchesTrigger(documents!, "every time")).toBe(true);
    expect(matchesTrigger(anomaly!, "forensic")).toBe(true);
    expect(matchesTrigger(anomaly!, "gst")).toBe(false);
    expect(matchesTrigger(anomaly!, "   ")).toBe(true);
  });
});
