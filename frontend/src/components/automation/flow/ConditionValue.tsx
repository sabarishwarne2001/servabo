/**
 * Session J — the value of one condition, shaped by what it compares.
 *
 * An amount takes a number and a currency (never micros); a date takes a date picker or a number of days; a field with
 * fixed values (a severity, a state, a document type) takes a dropdown, never a free-text code; "is one of" takes a list
 * where a value may hold a comma; "between" takes a low and a high. Everything else is plain text.
 */

import React, { useState } from "react";
import { Plus, X } from "lucide-react";

import type { FlowCatalog, FlowConditionValue, FlowField } from "@/types/automationFlow";
import { DAY_COUNT_OPERATORS, LIST_OPERATORS, valueItems } from "./flowModel";
import { inputClass } from "./StepCard";

/** The currencies offered next to an amount; the workspace's own comes first. */
export const COMMON_CURRENCIES: readonly string[] = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY"];

export const currencyChoices = (workspaceCurrency: string | undefined): string[] => {
  const own = (workspaceCurrency ?? "").toUpperCase();
  const rest = COMMON_CURRENCIES.filter((code) => code !== own);
  return own ? [own, ...rest] : [...rest];
};

interface ConditionValueProps {
  readonly catalog: FlowCatalog;
  readonly field: FlowField | undefined;
  readonly operator: string;
  readonly value: FlowConditionValue;
  readonly currency: string;
  readonly invalid: boolean;
  readonly disabled: boolean;
  readonly onChange: (patch: { readonly value?: FlowConditionValue; readonly currency?: string }) => void;
}

export const ChipList: React.FC<{
  readonly items: readonly string[];
  readonly disabled: boolean;
  readonly onChange: (next: string[]) => void;
  readonly invalid: boolean;
  readonly label?: string;
}> = ({ items, disabled, onChange, invalid, label = "Value" }) => {
  const [draft, setDraft] = useState("");
  const add = (): void => {
    const text = draft.trim();
    if (!text || items.includes(text)) {
      setDraft("");
      return;
    }
    onChange([...items, text]);
    setDraft("");
  };
  return (
    <div className="space-y-1.5">
      {items.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Values">
          {items.map((item) => (
            <li key={item} className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 py-0.5 pl-2.5 pr-1 text-xs">
              {item}
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(items.filter((other) => other !== item))}
                className="rounded-full p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                aria-label={`Remove ${item}`}
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-1.5">
        <input
          aria-label={label}
          disabled={disabled}
          value={draft}
          placeholder="Type a value, press Enter"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              e.stopPropagation();
              add();
            }
          }}
          onBlur={add}
          className={inputClass(invalid && items.length === 0)}
        />
        <button
          type="button"
          disabled={disabled || draft.trim() === ""}
          onClick={add}
          className="rounded-lg border border-border px-2 text-muted-foreground hover:bg-muted disabled:opacity-50"
          aria-label="Add value"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};

export const ConditionValue: React.FC<ConditionValueProps> = ({
  catalog, field, operator, value, currency, invalid, disabled, onChange,
}) => {
  const items = valueItems(value);
  const type = field?.type;
  const options = field?.options ?? [];
  const text = typeof value === "string" ? value : (items[0] ?? "");

  if (DAY_COUNT_OPERATORS.includes(operator)) {
    return (
      <div className="flex items-center gap-2">
        <input
          aria-label="Value"
          type="number"
          min={0}
          step={1}
          disabled={disabled}
          value={text}
          placeholder="30"
          onChange={(e) => onChange({ value: e.target.value })}
          className={inputClass(invalid)}
        />
        <span className="shrink-0 text-xs text-muted-foreground">days</span>
      </div>
    );
  }

  if (operator === "BETWEEN") {
    const low = items[0] ?? "";
    const high = items[1] ?? "";
    const inputType = type === "date" ? "date" : type === "number" ? "number" : "text";
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <input
            aria-label="Low value"
            type={inputType}
            inputMode={type === "money" ? "decimal" : undefined}
            disabled={disabled}
            value={low}
            onChange={(e) => onChange({ value: [e.target.value, high] })}
            className={inputClass(invalid)}
          />
          <span className="text-xs text-muted-foreground">and</span>
          <input
            aria-label="High value"
            type={inputType}
            inputMode={type === "money" ? "decimal" : undefined}
            disabled={disabled}
            value={high}
            onChange={(e) => onChange({ value: [low, e.target.value] })}
            className={inputClass(invalid)}
          />
        </div>
        {type === "money" && <CurrencyPick catalog={catalog} currency={currency} disabled={disabled} onChange={(c) => onChange({ currency: c })} />}
      </div>
    );
  }

  if (options.length > 0 && LIST_OPERATORS.includes(operator)) {
    return (
      <div role="group" aria-label="Values" className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const on = items.includes(option.value);
          return (
            <label
              key={option.value}
              className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                on ? "border-primary bg-primary/10 font-semibold" : "border-border hover:bg-muted/50"
              }`}
            >
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-primary"
                disabled={disabled}
                checked={on}
                onChange={() => onChange({ value: on ? items.filter((i) => i !== option.value) : [...items, option.value] })}
              />
              {option.label}
            </label>
          );
        })}
      </div>
    );
  }

  if (LIST_OPERATORS.includes(operator)) {
    return <ChipList items={items} disabled={disabled} invalid={invalid} onChange={(next) => onChange({ value: next })} />;
  }

  if (options.length > 0) {
    return (
      <select
        aria-label="Value"
        disabled={disabled}
        value={text}
        onChange={(e) => onChange({ value: e.target.value })}
        className={inputClass(invalid)}
      >
        <option value="" disabled>Choose…</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
        {text !== "" && !options.some((option) => option.value === text) && <option value={text}>{text} (no longer offered)</option>}
      </select>
    );
  }

  if (type === "boolean") {
    return (
      <select
        aria-label="Value"
        disabled={disabled}
        value={text}
        onChange={(e) => onChange({ value: e.target.value })}
        className={inputClass(invalid)}
      >
        <option value="" disabled>Choose…</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }

  if (type === "money") {
    return (
      <div className="space-y-1.5">
        <input
          aria-label="Value"
          inputMode="decimal"
          disabled={disabled}
          value={text}
          placeholder={field?.example || "10,00,000"}
          onChange={(e) => onChange({ value: e.target.value })}
          className={inputClass(invalid)}
        />
        <CurrencyPick catalog={catalog} currency={currency} disabled={disabled} onChange={(c) => onChange({ currency: c })} />
      </div>
    );
  }

  if (type === "date" && !["STARTS_WITH"].includes(operator)) {
    return (
      <input
        aria-label="Value"
        type="date"
        disabled={disabled}
        value={text}
        onChange={(e) => onChange({ value: e.target.value })}
        className={inputClass(invalid)}
      />
    );
  }

  return (
    <input
      aria-label="Value"
      disabled={disabled}
      type={type === "number" ? "number" : "text"}
      value={text}
      placeholder={field?.example || "value"}
      onChange={(e) => onChange({ value: e.target.value })}
      className={inputClass(invalid)}
    />
  );
};

const CurrencyPick: React.FC<{
  readonly catalog: FlowCatalog;
  readonly currency: string;
  readonly disabled: boolean;
  readonly onChange: (currency: string) => void;
}> = ({ catalog, currency, disabled, onChange }) => (
  <label className="flex w-full min-w-0 items-center gap-2 text-xs text-muted-foreground">
    <span className="shrink-0">Currency</span>
    <select
      aria-label="Currency"
      disabled={disabled}
      value={currency}
      onChange={(e) => onChange(e.target.value)}
      className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
    >
      <option value="">The document&rsquo;s own</option>
      {currencyChoices(catalog.workspace?.currency).map((code) => (
        <option key={code} value={code}>{code}</option>
      ))}
    </select>
  </label>
);
