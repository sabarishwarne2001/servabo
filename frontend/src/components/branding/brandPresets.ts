/**
 * Starting points for the Branding page. A preset only fills the colour fields: what is saved is
 * still four six-digit hex values, so the server's validation and the stored tokens are exactly
 * what they were with typed codes.
 */

export type BrandColourKey = "primary_color" | "accent_color" | "background_color" | "foreground_color";

export interface BrandPreset {
  readonly id: string;
  readonly name: string;
  readonly colours: Readonly<Record<BrandColourKey, string>>;
}

export const BRAND_PRESETS: readonly BrandPreset[] = [
  { id: "cobalt", name: "Cobalt", colours: { primary_color: "#2463eb", accent_color: "#7c3aed", background_color: "#ffffff", foreground_color: "#0f172a" } },
  { id: "emerald", name: "Emerald", colours: { primary_color: "#0f766e", accent_color: "#f59e0b", background_color: "#ffffff", foreground_color: "#0f172a" } },
  { id: "violet", name: "Violet", colours: { primary_color: "#6d28d9", accent_color: "#db2777", background_color: "#fafafa", foreground_color: "#18181b" } },
  { id: "crimson", name: "Crimson", colours: { primary_color: "#be123c", accent_color: "#ea580c", background_color: "#ffffff", foreground_color: "#1c1917" } },
  { id: "slate", name: "Slate", colours: { primary_color: "#334155", accent_color: "#0ea5e9", background_color: "#f8fafc", foreground_color: "#0f172a" } },
  { id: "midnight", name: "Midnight", colours: { primary_color: "#38bdf8", accent_color: "#a78bfa", background_color: "#0b1220", foreground_color: "#f8fafc" } },
];

/** One-click colours for a single field. */
export const SWATCHES: readonly string[] = [
  "#2463eb", "#0f766e", "#6d28d9", "#be123c", "#ea580c", "#f59e0b", "#0ea5e9", "#334155",
  "#ffffff", "#f8fafc", "#0f172a", "#0b1220",
];

/** What the sign-in page falls back to when a token is not set. */
export const FALLBACK_COLOURS: Readonly<Record<BrandColourKey, string>> = {
  primary_color: "#2463eb",
  accent_color: "#7c3aed",
  background_color: "#ffffff",
  foreground_color: "#111827",
};

/**
 * Tidies what a person typed or pasted into a colour field: trims, lower-cases, adds the missing
 * "#" and expands "#abc" to "#aabbcc". Anything else is returned as typed so the field can say it
 * is not valid; nothing here makes an invalid value valid by guessing.
 */
export const tidyColourInput = (raw: string): string => {
  const value = raw.trim().toLowerCase();
  const bare = value.startsWith("#") ? value.slice(1) : value;
  if (/^[0-9a-f]{3}$/.test(bare)) {
    return `#${bare.replace(/./g, (digit) => digit + digit)}`;
  }
  if (/^[0-9a-f]{6}$/.test(bare)) {
    return `#${bare}`;
  }
  return raw;
};
