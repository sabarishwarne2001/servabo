import React from "react";
import { Check } from "lucide-react";

import { SWATCHES, tidyColourInput } from "@/components/branding/brandPresets";
import { INPUT_MONO } from "@/components/ui/primitives";
import { isValidHexColor, normaliseHexColor } from "@/types/branding";

interface ColorFieldProps {
  /** The text input's id; the label points at it. */
  readonly id: string;
  readonly label: string;
  readonly help: string;
  readonly value: string;
  readonly disabled?: boolean;
  readonly onChange: (next: string) => void;
}

/**
 * One brand colour: a swatch that opens the system colour picker, the hex code for people who have
 * one, and a row of one-click swatches. The value stays a hex string; the picker and the swatches
 * only ever write six-digit hex (`<input type="color">` does by definition), so a colour chosen
 * visually is stored exactly like a typed one.
 */
export const ColorField: React.FC<ColorFieldProps> = ({ id, label, help, value, disabled = false, onChange }) => {
  const current = normaliseHexColor(value);
  const invalid = value.trim() !== "" && !isValidHexColor(value);
  return (
    <div className="space-y-2">
      <div>
        <label className="text-sm font-medium text-foreground" htmlFor={id}>
          {label}
        </label>
        <p className="text-xs text-muted-foreground">{help}</p>
      </div>
      <div className="flex items-center gap-2">
        {/*
         * The colour is written to `backgroundColor` only after the hex test above, never built
         * into a stylesheet. The native input sits invisibly over the swatch so a click anywhere on
         * it opens the picker and the keyboard and screen reader get a real control.
         */}
        <span
          className={`relative h-9 w-9 shrink-0 overflow-hidden rounded-lg border border-[hsl(var(--border-strong)/0.7)] shadow-sm focus-within:ring-2 focus-within:ring-ring/50 ${
            current ? "" : "bg-[repeating-conic-gradient(hsl(var(--muted))_0_25%,transparent_0_50%)] bg-[length:10px_10px]"
          } ${disabled ? "opacity-60" : ""}`}
          style={current ? { backgroundColor: current } : undefined}
        >
          <input
            type="color"
            aria-label={`Pick ${label.toLowerCase()} colour`}
            value={current ?? "#000000"}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value.toLowerCase())}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
          />
        </span>
        <input
          id={id}
          className={`${INPUT_MONO} min-w-0`}
          value={value}
          placeholder="#1a73e8"
          spellCheck={false}
          autoComplete="off"
          maxLength={9}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => {
            const tidy = tidyColourInput(value);
            if (tidy !== value) {
              onChange(tidy);
            }
          }}
        />
      </div>
      {invalid ? (
        <p className="text-xs text-destructive" role="alert">
          Use six-digit hex, e.g. #1a73e8.
        </p>
      ) : null}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={`${label} quick colours`}>
        {SWATCHES.map((swatch) => {
          const selected = current === swatch;
          return (
            <button
              key={swatch}
              type="button"
              disabled={disabled}
              title={swatch}
              aria-label={`${label} ${swatch}`}
              aria-pressed={selected}
              onClick={() => onChange(swatch)}
              className="relative flex h-5 w-5 items-center justify-center rounded-full border border-[hsl(var(--border-strong)/0.6)] transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100"
              style={{ backgroundColor: swatch }}
            >
              {selected ? (
                <Check
                  className="h-3 w-3"
                  style={{ color: swatch === "#ffffff" || swatch === "#f8fafc" || swatch === "#f59e0b" ? "#0f172a" : "#ffffff" }}
                  aria-hidden
                />
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default ColorField;
