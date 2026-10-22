/**
 * ARCH-37 — the step builder's draft model. Pure functions only.
 *
 * A draft is what the three cards edit. `draftFromRule` opens any stored rule
 * (ARCH-13 or ARCH-37), `payloadFromDraft` produces the request, and
 * `issuesByCard` turns the server's FastAPI-shaped refusals into messages on
 * the card that caused them. Action and trigger vocabulary comes from the
 * catalog; nothing here names one.
 */

import { ApiError } from "@/services/api/errors";
import type {
  AutomationErrorPolicy,
  AutomationLogicOperator,
  AutomationRule,
  AutomationRuleCreateRequest,
} from "@/types/automation";
import type {
  FlowAction,
  FlowActionEntry,
  FlowCatalog,
  FlowConditionValue,
  FlowField,
  FlowFieldType,
  FlowTrigger,
  JsonSchemaProperty,
} from "@/types/automationFlow";

export interface ConditionDraft {
  readonly uid: string;
  readonly field: string;
  readonly operator: string;
  /** A string, or a list of strings for "is one of", "between" and the list operators (a value may hold a comma). */
  readonly value: FlowConditionValue;
  /** An amount's currency ("INR"); empty means the document's own. Never converted. */
  readonly currency: string;
}

export interface GroupDraft {
  readonly uid: string;
  readonly logic_operator: AutomationLogicOperator;
  readonly conditions: readonly ConditionDraft[];
}

export interface ActionDraft {
  readonly uid: string;
  readonly action_type: string;
  readonly config: Readonly<Record<string, unknown>>;
}

export interface FlowDraft {
  readonly name: string;
  readonly priority: number;
  readonly is_active: boolean;
  readonly on_error: AutomationErrorPolicy;
  readonly triggers: readonly string[];
  readonly groups: readonly GroupDraft[];
  readonly groups_operator: AutomationLogicOperator;
  readonly actions: readonly ActionDraft[];
  readonly else_actions: readonly ActionDraft[];
  /** Session J: "at most N runs an hour"; null means the workspace default. */
  readonly max_runs_per_hour: number | null;
  /** Session J: "at most once per document every X hours"; null means off. */
  readonly cooldown_hours: number | null;
  /** A note kept with the version this save writes. */
  readonly note: string;
}

export type CardKey = "general" | "trigger" | "conditions" | "actions" | "else";

export interface CardIssue {
  readonly card: CardKey;
  /** Group index for conditions, action index for actions / else. */
  readonly index: number | null;
  /** Condition index inside a group. */
  readonly subIndex: number | null;
  /** The config key or field the issue names, if any. */
  readonly field: string | null;
  readonly message: string;
}

let counter = 0;
export const uid = (prefix: string): string => {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
};

export const OPERATOR_LABELS: Readonly<Record<string, string>> = {
  EQUALS: "equals",
  NOT_EQUALS: "does not equal",
  CONTAINS: "contains",
  NOT_CONTAINS: "does not contain",
  STARTS_WITH: "starts with",
  ENDS_WITH: "ends with",
  GREATER_THAN: "is greater than",
  LESS_THAN: "is less than",
  GREATER_THAN_OR_EQUAL: "is at least",
  LESS_THAN_OR_EQUAL: "is at most",
  BETWEEN: "is between",
  IN: "is one of",
  NOT_IN: "is not one of",
  EXISTS: "exists",
  IS_EMPTY: "is empty",
  IS_NOT_EMPTY: "is not empty",
  ARRAY_CONTAINS_ANY: "contains any of",
  ARRAY_CONTAINS_ALL: "contains all of",
  BEFORE: "is before",
  AFTER: "is after",
  ON_OR_BEFORE: "is on or before",
  ON_OR_AFTER: "is on or after",
  WITHIN_NEXT_DAYS: "is within the next",
  WITHIN_LAST_DAYS: "was within the last",
  OLDER_THAN_DAYS: "is older than",
};

/** The words after the value of a day-count comparison: "is older than 30 days". */
export const DAY_COUNT_OPERATORS: readonly string[] = ["WITHIN_NEXT_DAYS", "WITHIN_LAST_DAYS", "OLDER_THAN_DAYS"];
export const LIST_OPERATORS: readonly string[] = ["IN", "NOT_IN", "BETWEEN", "ARRAY_CONTAINS_ANY", "ARRAY_CONTAINS_ALL"];

export const valueItems = (value: FlowConditionValue | undefined): string[] =>
  (Array.isArray(value) ? [...value] : typeof value === "string" ? [value] : [])
    .map((item) => String(item).trim())
    .filter((item) => item !== "");

export const valueIsEmpty = (value: FlowConditionValue | undefined): boolean => valueItems(value).length === 0;

/**
 * An amount as people write it: rupees in lakh grouping ("10,00,000"), other currencies in thousands. Text that is
 * not a plain number ("₹10,00,000", "1.5 crore") is shown exactly as typed.
 */
export const groupAmount = (text: string, currency: string): string => {
  if (!/^\d+(\.\d+)?$/.test(text)) {return text;}
  const [whole = "", fraction] = text.split(".");
  const digits = whole.replace(/^0+(?=\d)/, "");
  let grouped: string;
  if (currency.toUpperCase() === "INR" && digits.length > 3) {
    // Lakh grouping: the last three digits, then pairs (10,00,000).
    const head = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
    grouped = `${head},${digits.slice(-3)}`;
  } else {
    grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
};

/** The value as a person reads it: "10,00,000 INR", "Acme, Inc or Beta", "5 and 10". */
export const valueText = (
  operator: string,
  value: FlowConditionValue | undefined,
  currency = "",
): string => {
  const items = valueItems(value);
  if (items.length === 0) {return "";}
  const unit = currency ? ` ${currency}` : "";
  const shown = (item: string): string => (currency ? groupAmount(item, currency) : item);
  if (operator === "BETWEEN" && items.length === 2) {return `${shown(items[0] ?? "")} and ${shown(items[1] ?? "")}${unit}`;}
  if (items.length > 1) {
    const last = items[items.length - 1] ?? "";
    return `${items.slice(0, -1).join(", ")} or ${last}${unit}`;
  }
  const only = items[0] ?? "";
  return DAY_COUNT_OPERATORS.includes(operator) ? `${only} day${only === "1" ? "" : "s"}` : `${shown(only)}${unit}`;
};

export const operatorLabel = (operator: string): string =>
  OPERATOR_LABELS[operator] ?? operator.toLowerCase().replace(/_/g, " ");

export const humanize = (key: string): string => {
  const last = key.replace(/^event\./, "").replace(/^classification_details\./, "");
  const text = last.replace(/[._]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : key;
};

export const emptyDraft = (): FlowDraft => ({
  name: "",
  priority: 100,
  is_active: true,
  on_error: "HALT",
  triggers: [],
  groups: [],
  groups_operator: "AND",
  actions: [],
  else_actions: [],
  max_runs_per_hour: null,
  cooldown_hours: null,
  note: "",
});

export const findTrigger = (catalog: FlowCatalog | undefined, key: string): FlowTrigger | undefined =>
  catalog?.triggers.find((t) => t.key === key);

/** The catalog action for a stored type, including legacy aliases. */
export const findAction = (catalog: FlowCatalog | undefined, actionType: string): FlowAction | undefined => {
  if (!catalog) {return undefined;}
  const lowered = actionType.trim().toLowerCase();
  return (
    catalog.actions.find((a) => a.type === lowered) ??
    catalog.actions.find((a) => a.aliases.includes(lowered))
  );
};

export const triggerLabel = (catalog: FlowCatalog | undefined, key: string): string =>
  findTrigger(catalog, key)?.label ?? humanize(key);

/**
 * Phase 2: what a rule listens to, named from its stored event types when no catalog trigger is
 * held whole (a clause check listens to `work_item.enriched`, one of the two events "Document
 * processed" covers, so the API's trigger list for it is empty).
 */
export const triggerLabelsForEvents = (catalog: FlowCatalog | undefined, eventTypes: readonly string[]): string[] => [
  ...new Set(
    eventTypes.map(
      (event) => catalog?.triggers.find((trigger) => trigger.event_types.includes(event))?.label ?? humanize(event),
    ),
  ),
];

export const actionLabel = (catalog: FlowCatalog | undefined, actionType: string): string =>
  findAction(catalog, actionType)?.label ?? humanize(actionType);

/** Event fields every selected trigger carries (the server enforces the same). */
export const commonEventFields = (catalog: FlowCatalog | undefined, triggers: readonly string[]): FlowField[] => {
  const specs = triggers
    .map((key) => findTrigger(catalog, key))
    .filter((t): t is FlowTrigger => t !== undefined);
  const first = specs[0];
  if (!first) {return [];}
  return first.fields.filter((field) => specs.every((spec) => spec.fields.some((f) => f.key === field.key)));
};

export const availableFields = (catalog: FlowCatalog | undefined, triggers: readonly string[]): FlowField[] => {
  const specs = triggers.map((key) => findTrigger(catalog, key)).filter((t): t is FlowTrigger => t !== undefined);
  const documents = specs.length > 0 && specs.every((spec) => spec.has_document);
  return [...commonEventFields(catalog, triggers), ...(documents ? catalog?.document_fields ?? [] : [])];
};

export const fieldFor = (catalog: FlowCatalog | undefined, triggers: readonly string[], key: string): FlowField | undefined =>
  availableFields(catalog, triggers).find((f) => f.key === key);

export const fieldLabel = (catalog: FlowCatalog | undefined, key: string): string => {
  const pool = [
    ...(catalog?.triggers.flatMap((t) => t.fields) ?? []),
    ...(catalog?.document_fields ?? []),
  ];
  return pool.find((f) => f.key === key)?.label ?? humanize(key);
};

export const operatorsFor = (catalog: FlowCatalog | undefined, type: FlowFieldType | undefined): readonly string[] => {
  if (!catalog) {return [];}
  if (type) {return catalog.operators[type] ?? [];}
  return Array.from(new Set(Object.values(catalog.operators).flat()));
};

export const isValueless = (catalog: FlowCatalog | undefined, operator: string): boolean =>
  catalog?.valueless_operators.includes(operator) ?? false;

/** Actions the selected triggers may run. */
export const excludedActions = (catalog: FlowCatalog | undefined, triggers: readonly string[]): Set<string> =>
  new Set(triggers.flatMap((key) => findTrigger(catalog, key)?.excluded_actions ?? []));

export const schemaProperties = (action: FlowAction | undefined): [string, JsonSchemaProperty][] =>
  Object.entries(action?.config_schema.properties ?? {});

export const defaultConfig = (action: FlowAction): Record<string, unknown> => {
  const config: Record<string, unknown> = {};
  for (const [key, prop] of schemaProperties(action)) {
    if (prop.default !== undefined) {
      config[key] = prop.default;
    } else if (prop.type === "array") {
      config[key] = [];
    }
  }
  return config;
};

const cleanConfig = (action: FlowAction | undefined, config: Readonly<Record<string, unknown>>): Record<string, unknown> => {
  const allowed = new Set(schemaProperties(action).map(([key]) => key));
  const required = new Set(action?.config_schema.required ?? []);
  const cleaned: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (allowed.size > 0 && !allowed.has(key)) {continue;}
    if (typeof value === "string" && value.trim() === "" && !required.has(key)) {continue;}
    cleaned[key] = typeof value === "string" ? value.trim() : value;
  }
  return cleaned;
};

const toActionDraft = (catalog: FlowCatalog | undefined, entry: FlowActionEntry): ActionDraft => {
  const action = findAction(catalog, entry.action_type);
  const base = action ? defaultConfig(action) : {};
  return {
    uid: uid("action"),
    action_type: action?.type ?? entry.action_type,
    config: { ...base, ...(entry.config ?? {}) },
  };
};

/** The pieces of a rule a draft is built from; a stored rule and a recipe both have them. */
type RuleShape = Pick<
  AutomationRuleCreateRequest,
  "name" | "priority" | "on_error" | "triggers" | "groups_operator" | "actions" | "else_actions"
> & {
  readonly is_active?: boolean | undefined;
  readonly condition_groups?: AutomationRuleCreateRequest["condition_groups"] | undefined;
  readonly max_runs_per_hour?: number | null | undefined;
  readonly cooldown_hours?: number | null | undefined;
};

const draftFromShape = (rule: RuleShape, catalog: FlowCatalog | undefined, name: string, active: boolean): FlowDraft => {
  const groups: GroupDraft[] = (rule.condition_groups ?? []).map((group) => ({
    uid: uid("group"),
    logic_operator: group.logic_operator,
    conditions: group.conditions.map((condition) => ({
      uid: uid("condition"),
      field: condition.field,
      operator: condition.operator,
      value: condition.value ?? "",
      currency: condition.currency ?? "",
    })),
  }));
  return {
    name,
    priority: rule.priority,
    is_active: active,
    on_error: rule.on_error ?? "HALT",
    triggers: [...(rule.triggers ?? [])],
    groups,
    groups_operator: rule.groups_operator ?? "AND",
    actions: rule.actions.map((entry) => toActionDraft(catalog, entry)),
    else_actions: (rule.else_actions ?? []).map((entry) => toActionDraft(catalog, entry)),
    max_runs_per_hour: rule.max_runs_per_hour ?? null,
    cooldown_hours: rule.cooldown_hours ?? null,
    note: "",
  };
};

export const draftFromRule = (
  rule: AutomationRule,
  catalog: FlowCatalog | undefined,
  mode: "edit" | "duplicate",
): FlowDraft =>
  draftFromShape(
    {
      name: rule.name,
      priority: rule.priority,
      on_error: rule.on_error ?? "HALT",
      triggers: rule.triggers ?? [],
      groups_operator: rule.groups_operator ?? "AND",
      actions: rule.actions,
      else_actions: rule.else_actions ?? [],
      condition_groups: rule.condition_groups,
      max_runs_per_hour: rule.max_runs_per_hour,
      cooldown_hours: rule.cooldown_hours,
    },
    catalog,
    mode === "duplicate" ? `${rule.name} (copy)`.slice(0, 100) : rule.name,
    mode === "duplicate" ? false : rule.is_active,
  );

/** A recipe's rule as a draft, ready for the builder. A recipe starts switched on: the person decides when they save. */
/**
 * A rule document (a recipe) to a draft. A recipe carries no priority of its own (the server fills it in on save), so the
 * draft gets the default one; without it the builder said "Priority must be a whole number" and refused to save.
 */
export const draftFromPayload = (payload: AutomationRuleCreateRequest, catalog: FlowCatalog | undefined): FlowDraft =>
  draftFromShape({ ...payload, priority: payload.priority ?? emptyDraft().priority }, catalog, payload.name, payload.is_active ?? true);

/** Answers a recipe asked for, written into its rule at the `path` each fill-in names (`actions.0.config.endpoint_id`). */
export const applyFillIns = (
  rule: AutomationRuleCreateRequest,
  answers: Readonly<Record<string, string>>,
): AutomationRuleCreateRequest => {
  const copy = JSON.parse(JSON.stringify(rule)) as Record<string, unknown>;
  for (const [path, value] of Object.entries(answers)) {
    const parts = path.split(".");
    let target: unknown = copy;
    for (const part of parts.slice(0, -1)) {
      if (target === null || typeof target !== "object") {break;}
      target = (target as Record<string, unknown>)[part];
    }
    const last = parts[parts.length - 1];
    if (target !== null && typeof target === "object" && last !== undefined) {
      (target as Record<string, unknown>)[last] = value;
    }
  }
  return copy as unknown as AutomationRuleCreateRequest;
};

export const payloadFromDraft = (draft: FlowDraft, catalog: FlowCatalog | undefined): AutomationRuleCreateRequest => {
  const actionEntry = (entry: ActionDraft): FlowActionEntry => ({
    action_type: entry.action_type,
    config: cleanConfig(findAction(catalog, entry.action_type), entry.config),
  });
  return {
    name: draft.name.trim(),
    priority: draft.priority,
    is_active: draft.is_active,
    on_error: draft.on_error,
    triggers: [...draft.triggers],
    condition_groups: draft.groups
      .filter((group) => group.conditions.length > 0)
      .map((group) => ({
        logic_operator: group.logic_operator,
        conditions: group.conditions.map(({ field, operator, value, currency }) => ({
          field,
          operator,
          value: typeof value === "string" ? value.trim() : valueItems(value),
          ...(currency ? { currency } : {}),
        })),
      })),
    groups_operator: draft.groups_operator,
    actions: draft.actions.map(actionEntry),
    else_actions: draft.else_actions.map(actionEntry),
    max_runs_per_hour: draft.max_runs_per_hour,
    cooldown_hours: draft.cooldown_hours,
    ...(draft.note.trim() ? { note: draft.note.trim() } : {}),
  };
};

/** Client-side checks that mirror the server's, so most mistakes show before a round trip. */
export const localIssues = (draft: FlowDraft, catalog: FlowCatalog | undefined): CardIssue[] => {
  const issues: CardIssue[] = [];
  const push = (card: CardKey, message: string, index: number | null = null, subIndex: number | null = null, field: string | null = null): void => {
    issues.push({ card, index, subIndex, field, message });
  };
  if (!draft.name.trim()) {push("general", "Give the rule a name.", null, null, "name");}
  if (!Number.isInteger(draft.priority) || draft.priority < 1) {push("general", "Priority must be a whole number of at least 1.", null, null, "priority");}
  if (draft.max_runs_per_hour !== null && (!Number.isInteger(draft.max_runs_per_hour) || draft.max_runs_per_hour < 1 || draft.max_runs_per_hour > 100000)) {
    push("general", "The hourly limit must be a whole number from 1 to 100,000, or empty.", null, null, "max_runs_per_hour");
  }
  if (draft.cooldown_hours !== null && (!Number.isInteger(draft.cooldown_hours) || draft.cooldown_hours < 1 || draft.cooldown_hours > 8760)) {
    push("general", "The cooldown must be a whole number of hours from 1 to 8,760, or empty.", null, null, "cooldown_hours");
  }
  if (draft.triggers.length === 0) {push("trigger", "Choose at least one trigger.");}
  draft.triggers.forEach((key, index) => {
    const trigger = findTrigger(catalog, key);
    if (!trigger) {push("trigger", "This trigger no longer exists.", index);}
    else if (!trigger.available) {push("trigger", `${trigger.label} is not included in your plan.`, index);}
  });
  draft.groups.forEach((group, g) => {
    group.conditions.forEach((condition, c) => {
      if (!condition.field) {push("conditions", "Choose a field.", g, c, "field");}
      else if (!fieldFor(catalog, draft.triggers, condition.field) && condition.field.startsWith("event.")) {
        push("conditions", "Not every selected trigger carries this field.", g, c, "field");
      }
      if (!condition.operator) {push("conditions", "Choose a comparison.", g, c, "operator");}
      if (condition.operator && !isValueless(catalog, condition.operator) && valueIsEmpty(condition.value)) {
        push("conditions", "Enter a value.", g, c, "value");
      } else if (condition.operator === "BETWEEN" && valueItems(condition.value).length !== 2) {
        push("conditions", "Give a low and a high value.", g, c, "value");
      } else if (DAY_COUNT_OPERATORS.includes(condition.operator) && !/^\d+$/.test(valueItems(condition.value)[0] ?? "")) {
        push("conditions", "Enter a whole number of days.", g, c, "value");
      }
    });
  });
  const hasConditions = draft.groups.some((group) => group.conditions.length > 0);
  if (draft.actions.length === 0) {push("actions", "Add at least one action.");}
  if (draft.else_actions.length > 0 && !hasConditions) {push("else", "'Otherwise' actions need at least one condition.");}
  const excluded = excludedActions(catalog, draft.triggers);
  const checkActions = (card: CardKey, list: readonly ActionDraft[]): void => {
    list.forEach((entry, index) => {
      const action = findAction(catalog, entry.action_type);
      if (!action) {
        push(card, "This action no longer exists.", index);
        return;
      }
      if (!action.available) {push(card, action.unavailable_reason ?? `${action.label} is unavailable.`, index);}
      if (excluded.has(action.type)) {push(card, `${action.label} cannot run on the selected trigger.`, index);}
      for (const key of action.config_schema.required ?? []) {
        const value = entry.config[key];
        const empty = value === undefined || value === null || (typeof value === "string" && !value.trim()) || (Array.isArray(value) && value.length === 0);
        if (empty) {push(card, `${humanize(key)} is required.`, index, null, key);}
      }
    });
  };
  checkActions("actions", draft.actions);
  checkActions("else", draft.else_actions);
  return issues;
};

interface ServerIssue {
  readonly loc?: readonly (string | number)[];
  readonly msg?: string;
}

/** The server's refusals, placed on the card that caused them. */
export const issuesFromError = (error: unknown): CardIssue[] | null => {
  if (!(error instanceof ApiError)) {return null;}
  const raw = error.details["issues"];
  if (!Array.isArray(raw)) {return null;}
  return (raw as ServerIssue[]).map((issue) => {
    const loc = (issue.loc ?? []).filter((part) => part !== "body");
    const head = String(loc[0] ?? "");
    const num = (value: unknown): number | null => (typeof value === "number" ? value : null);
    const message = issue.msg ?? "Invalid value.";
    if (head === "triggers" || head === "event") {
      return { card: "trigger", index: num(loc[1]), subIndex: null, field: null, message };
    }
    if (head === "condition_groups" || head === "conditions" || head === "groups_operator" || head === "logic_operator") {
      return {
        card: "conditions",
        index: num(loc[1]),
        subIndex: num(loc[3]),
        field: typeof loc[4] === "string" ? loc[4] : null,
        message,
      };
    }
    if (head === "actions" || head === "else_actions") {
      const configKey = loc[2] === "config" && typeof loc[3] === "string" ? loc[3] : null;
      return {
        card: head === "actions" ? "actions" : "else",
        index: num(loc[1]),
        subIndex: null,
        field: configKey,
        message,
      };
    }
    return {
      card: "general",
      index: null,
      subIndex: null,
      field: typeof loc[0] === "string" ? loc[0] : null,
      message,
    };
  });
};

export const issuesFor = (
  issues: readonly CardIssue[],
  card: CardKey,
  index: number | null = null,
): CardIssue[] =>
  issues.filter((issue) => issue.card === card && (index === null || issue.index === index));

const joinWords = (parts: readonly string[], word: string): string => {
  if (parts.length <= 1) {return parts[0] ?? "";}
  return `${parts.slice(0, -1).join(", ")} ${word} ${parts[parts.length - 1] ?? ""}`;
};

/** One condition as a person reads it: "total amount is greater than 1,000,000 INR". */
export const conditionText = (catalog: FlowCatalog | undefined, condition: ConditionDraft): string => {
  const label = fieldLabel(catalog, condition.field).toLowerCase();
  if (isValueless(catalog, condition.operator)) {return `${label} ${operatorLabel(condition.operator)}`;}
  const shown = valueText(condition.operator, condition.value, condition.currency);
  return `${label} ${operatorLabel(condition.operator)} ${shown ? shown : "…"}`.trim();
};

/** A plain-English sentence for the summary rail and the rule list. */
export const summarize = (draft: FlowDraft, catalog: FlowCatalog | undefined): string => {
  const when = draft.triggers.length
    ? joinWords(draft.triggers.map((key) => triggerLabel(catalog, key).toLowerCase()), "or")
    : "(pick when it runs)";
  const groups = draft.groups
    .filter((group) => group.conditions.length > 0)
    .map((group) => {
      const parts = group.conditions.map((condition) => conditionText(catalog, condition));
      return joinWords(parts, group.logic_operator === "OR" ? "or" : "and");
    });
  const condition = groups.length
    ? `, if ${groups.map((g) => (groups.length > 1 ? `(${g})` : g)).join(draft.groups_operator === "OR" ? " or " : " and ")}`
    : "";
  const then = draft.actions.length
    ? joinWords(draft.actions.map((a) => actionLabel(catalog, a.action_type).toLowerCase()), "then")
    : "(add what it does)";
  const otherwise = draft.else_actions.length
    ? `; otherwise ${joinWords(draft.else_actions.map((a) => actionLabel(catalog, a.action_type).toLowerCase()), "then")}`
    : "";
  return `When ${when}${condition}: ${then}${otherwise}.`;
};

export const sameDraft = (a: FlowDraft, b: FlowDraft, catalog: FlowCatalog | undefined): boolean =>
  JSON.stringify(payloadFromDraft(a, catalog)) === JSON.stringify(payloadFromDraft(b, catalog));
