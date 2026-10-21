/**
 * ARCH-37 — the configuration form for one action.
 *
 * ACTION_FORMS lists, per registered action type, the config keys the form
 * shows, in order. `verify_arch37.py` compares it with the server's action
 * registry and each action's schema: an action the server can run but the
 * console cannot configure, or a config key the form never shows, fails the
 * build. Controls are chosen from the key (resource pickers) or the JSON
 * schema the catalog serves (enums, numbers, lists, text).
 */

import React from "react";

import type { FlowAction, FlowCatalog, JsonSchemaProperty } from "@/types/automationFlow";
import {
  commonEventFields,
  humanize,
  schemaProperties,
  type CardIssue,
} from "./flowModel";
import { ChipList } from "./ConditionValue";
import { IssueText, inputClass } from "./StepCard";

export const ACTION_FORMS: Readonly<Record<string, readonly string[]>> = {
  "webhook.send": ["endpoint_id", "include_fields"],
  "redaction.start": ["profile_key"],
  "review.escalate": ["reason"],
  "warehouse.export": ["destination_id", "datasets", "lookback_days", "debounce_minutes"],
  "notify.role": ["roles", "priority", "title", "message"],
  "autonomy.decide": ["score_source", "on_hold", "hold_reason"],
  "email.send": ["recipient", "subject", "body"],
  "work_item.mutate": ["target_field", "target_value"],
  // ARCH47-S2:action-form-erp-post
  "erp.post": ["target_id", "object_kinds"],
  // Session J
  "document.tag": ["add", "remove"],
  "review.assign": ["assignee_email", "assignee_role", "reason", "due_in_hours"],
  "legal_hold.place": ["reason", "reference"],
  "chat.post": ["endpoint_id", "title", "message"],
  "gst.remind_supplier": ["at_most_every_days"],
  "obligation.create": ["title", "kind", "due_in_days", "owner_email", "description"],
  "supplier.request_document": ["case_template_id", "document_type"],
};

const LABELS: Readonly<Record<string, string>> = {
  endpoint_id: "Webhook endpoint",
  include_fields: "Document fields to include",
  profile_key: "Redaction profile",
  destination_id: "Warehouse destination",
  lookback_days: "Look back (days)",
  debounce_minutes: "At most once every (minutes)",
  score_source: "Score to decide on",
  on_hold: "When the document is held",
  hold_reason: "Reason shown to the reviewer",
  target_field: "Field to set",
  target_value: "New value",
  target_id: "ERP target",
  object_kinds: "What to post",
  add: "Tags to add",
  remove: "Tags to take off",
  assignee_email: "Send the review to",
  assignee_role: "Or to whoever holds the role",
  due_in_hours: "Due in (hours)",
  reference: "Matter or case reference",
  at_most_every_days: "At most one reminder per supplier every (days)",
  due_in_days: "Due in (days)",
  owner_email: "Owner",
  case_template_id: "Case template",
  document_type: "Document to ask for",
};

const HELP: Readonly<Record<string, string>> = {
  endpoint_id: "Only active endpoints registered for this organization are listed.",
  include_fields: "Only scalar values are sent. Leave empty to send references only.",
  destination_id: "Registered by an organization owner. Exports are debounced per destination.",
  score_source: "Held when below the calibrated threshold, suspended, or sampled for audit.",
  on_hold: "Either way, the actions after this one are skipped.",
  target_id: "Active ERP targets of this workspace. Runs on “procurement approved” and “case completed” only.",
  object_kinds: "One posting per kind, exactly once: a rule that fires again finds it already in the ledger.",
  add: "Press Enter after each tag. Tags are lower-case words, numbers and dashes.",
  assignee_email: "Choose a person, or a role below, not both.",
  owner_email: "Leave empty to give it to the person who built the rule.",
  case_template_id: "Only published case templates are listed.",
};

const enumOf = (prop: JsonSchemaProperty | undefined): readonly string[] | undefined =>
  prop?.enum ?? prop?.anyOf?.find((p) => p.enum)?.enum;

const optionLabel = (value: string): string => humanize(value.toLowerCase());

interface ActionConfigFormProps {
  readonly catalog: FlowCatalog;
  readonly action: FlowAction;
  readonly triggers: readonly string[];
  readonly config: Readonly<Record<string, unknown>>;
  readonly onChange: (config: Readonly<Record<string, unknown>>) => void;
  readonly issues: readonly CardIssue[];
  readonly disabled: boolean;
  readonly idPrefix: string;
}

export const ActionConfigForm: React.FC<ActionConfigFormProps> = ({
  catalog, action, triggers, config, onChange, issues, disabled, idPrefix,
}) => {
  const properties = new Map(schemaProperties(action));
  const keys = ACTION_FORMS[action.type] ?? Array.from(properties.keys());
  const required = new Set(action.config_schema.required ?? []);
  const resources = catalog.resources;
  const documentKeys = catalog.document_fields.map((f) => f.key).filter((k) => /^[a-z0-9_]{1,64}(\.[a-z0-9_]{1,64})?$/.test(k));
  const variables = [
    ...catalog.template_variables,
    ...commonEventFields(catalog, triggers).map((f) => f.key),
    ...catalog.document_fields.filter((f) => !f.key.includes(".")).map((f) => `field.${f.key}`),
  ];

  const set = (key: string, value: unknown): void => onChange({ ...config, [key]: value });
  const text = (key: string): string => {
    const value = config[key];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  };
  const list = (key: string): string[] => {
    const value = config[key];
    return Array.isArray(value) ? value.map(String) : [];
  };
  const toggleIn = (key: string, item: string): void => {
    const current = list(key);
    set(key, current.includes(item) ? current.filter((v) => v !== item) : [...current, item]);
  };

  const control = (key: string): React.ReactNode => {
    const prop = properties.get(key);
    const id = `${idPrefix}-${key}`;
    const invalid = issues.some((issue) => issue.field === key);
    const options = enumOf(prop);

    const select = (choices: readonly { value: string; label: string }[], empty: string): React.ReactNode => (
      <select id={id} disabled={disabled} value={text(key)} onChange={(e) => set(key, e.target.value)} className={inputClass(invalid)}>
        <option value="">{choices.length ? "Choose…" : empty}</option>
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>{choice.label}</option>
        ))}
      </select>
    );

    const checks = (choices: readonly string[], empty: string): React.ReactNode =>
      choices.length === 0 ? (
        <p className="text-xs text-muted-foreground">{empty}</p>
      ) : (
        <div id={id} role="group" className="flex flex-wrap gap-1.5">
          {choices.map((choice) => {
            const on = list(key).includes(choice);
            return (
              <button
                key={choice}
                type="button"
                disabled={disabled}
                aria-pressed={on}
                onClick={() => toggleIn(key, choice)}
                className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
                  on ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {choice.includes("_") || choice === choice.toUpperCase() ? optionLabel(choice) : choice}
              </button>
            );
          })}
        </div>
      );

    switch (key) {
      case "endpoint_id":
        if (action.type === "chat.post") {
          return select(
            (resources.chat_endpoints ?? []).map((e) => ({ value: e.id, label: `${e.kind === "SLACK" ? "Slack" : "Microsoft Teams"} · ${e.label}` })),
            "No Slack or Teams channel yet: add one under Settings › Webhooks",
          );
        }
        return select(
          resources.webhook_endpoints.map((e) => ({ value: e.id, label: `${e.label}${e.host && e.host !== e.label ? ` (${e.host})` : ""}` })),
          "No active webhook endpoints — register one under Settings › Webhooks",
        );
      case "destination_id":
        return select(
          resources.warehouse_destinations.map((d) => ({ value: d.id, label: `${d.label} · ${d.kind}` })),
          "No active destinations, or the warehouse add-on is not active",
        );
      case "assignee_email":
      case "owner_email":
        return (
          <select id={id} disabled={disabled} value={text(key)} onChange={(e) => set(key, e.target.value)} className={inputClass(invalid)}>
            <option value="">{key === "owner_email" ? "The person who built the rule" : "Choose a person…"}</option>
            {(resources.members ?? []).map((m) => (
              <option key={m.email} value={m.email}>{m.name === m.email ? m.email : `${m.name} (${m.email})`}</option>
            ))}
          </select>
        );
      case "case_template_id":
        return select(
          (resources.case_templates ?? []).map((t) => ({ value: t.id, label: t.label })),
          "No published case templates yet",
        );
      case "add":
      case "remove":
        return <ChipList items={list(key)} disabled={disabled} invalid={invalid} onChange={(next) => set(key, next)} label={`${LABELS[key] ?? key}`} />;
      case "profile_key":
        return select(resources.redaction_profiles.map((p) => ({ value: p, label: optionLabel(p) })), "No profiles");
      case "roles":
        return checks(resources.organization_roles, "No roles available.");
      case "datasets":
        return checks(resources.export_datasets, "No datasets available.");
      case "include_fields":
        return checks(documentKeys, "No extracted fields seen in this workspace yet.");
      // ARCH47-S2:action-form-erp-controls
      case "target_id":
        return select(
          resources.erp_targets.map((t) => ({ value: t.id, label: `${t.label} · ${t.preset !== "NONE" ? t.preset : t.format}` })),
          "No active ERP targets — add one under ERP posting › Targets",
        );
      case "object_kinds": {
        const chosen = resources.erp_targets.find((t) => t.id === text("target_id"));
        return checks(chosen ? chosen.objects : resources.erp_object_kinds, "This target takes no objects.");
      }
      case "target_field":
        return select(
          [
            ...resources.mutable_fields.map((f) => ({ value: f, label: humanize(f) })),
            ...documentKeys
              .filter((k) => !k.includes("."))
              .map((k) => ({ value: `extracted_entities.${k}`, label: `Extracted: ${humanize(k)}` })),
          ],
          "No fields",
        );
      default:
        break;
    }

    if (options) {
      return select(options.map((o) => ({ value: o, label: optionLabel(o) })), "—");
    }
    if (prop?.type === "array" && prop.items?.type === "string") {
      return <ChipList items={list(key)} disabled={disabled} invalid={invalid} onChange={(next) => set(key, next)} label={LABELS[key] ?? humanize(key)} />;
    }
    if (prop?.type === "integer" || prop?.type === "number") {
      return (
        <input
          id={id}
          type="number"
          disabled={disabled}
          min={prop.minimum}
          max={prop.maximum}
          value={text(key)}
          onChange={(e) => set(key, e.target.value === "" ? "" : Number(e.target.value))}
          className={inputClass(invalid)}
        />
      );
    }
    const isTemplate = action.template_fields.includes(key);
    const long = (prop?.maxLength ?? 0) > 500;
    return (
      <div className="space-y-1">
        {long ? (
          <textarea
            id={id}
            rows={5}
            disabled={disabled}
            maxLength={prop?.maxLength}
            value={text(key)}
            onChange={(e) => set(key, e.target.value)}
            className={`${inputClass(invalid)} font-mono text-xs`}
          />
        ) : (
          <input
            id={id}
            type={prop?.format === "email" ? "email" : "text"}
            disabled={disabled}
            maxLength={prop?.maxLength}
            value={text(key)}
            onChange={(e) => set(key, e.target.value)}
            className={inputClass(invalid)}
          />
        )}
        {isTemplate && (
          <select
            aria-label={`Insert a variable into ${humanize(key)}`}
            disabled={disabled}
            value=""
            onChange={(e) => {
              if (e.target.value) {set(key, `${text(key)}{{${e.target.value}}}`);}
            }}
            className="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground"
          >
            <option value="">Insert variable…</option>
            {variables.map((v) => (
              <option key={v} value={v}>{`{{${v}}}`}</option>
            ))}
          </select>
        )}
      </div>
    );
  };

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {keys.map((key) => {
        const prop = properties.get(key);
        const wide = ["include_fields", "roles", "datasets", "object_kinds", "body", "message", "title", "subject", "reason", "hold_reason"].includes(key);
        return (
          <div key={key} className={wide ? "md:col-span-2" : ""}>
            <label htmlFor={`${idPrefix}-${key}`} className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {LABELS[key] ?? prop?.title ?? humanize(key)}
              {required.has(key) && <span className="text-destructive"> *</span>}
            </label>
            {control(key)}
            {(HELP[key] ?? prop?.description) && (
              <p className="mt-1 text-[11px] text-muted-foreground">{HELP[key] ?? prop?.description}</p>
            )}
            <IssueText issues={issues.filter((issue) => issue.field === key)} />
          </div>
        );
      })}
    </div>
  );
};
