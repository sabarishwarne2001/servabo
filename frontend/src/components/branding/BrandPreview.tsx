import React, { useState } from "react";
import { FileText, LayoutDashboard, Lock, Search, Settings, Users } from "lucide-react";

import { FALLBACK_COLOURS, type BrandColourKey } from "@/components/branding/brandPresets";
import { useImageFallback } from "@/hooks/useImageFallback";
import { contrastRatio, readableHexOn } from "@/utils/brandTheme";
import { isValidHexColor, type ColorScheme } from "@/types/branding";

type Surface = "signin" | "app";

const SURFACES: readonly { readonly id: Surface; readonly label: string }[] = [
  { id: "signin", label: "Sign-in page" },
  { id: "app", label: "Inside the app" },
];

interface BrandPreviewProps {
  readonly colours: Readonly<Record<BrandColourKey, string>>;
  readonly scheme: ColorScheme;
  readonly brandName: string;
  readonly logoUrl: string | null;
  /** The hostname shown in the address bar: the organization's primary domain, if it has one. */
  readonly hostname: string;
}

/** The sign-in page's palette when a token is not set: it follows the colour scheme. */
const SCHEME_DEFAULTS: Readonly<Record<ColorScheme, { readonly background: string; readonly foreground: string }>> = {
  LIGHT: { background: FALLBACK_COLOURS.background_color, foreground: FALLBACK_COLOURS.foreground_color },
  SYSTEM: { background: FALLBACK_COLOURS.background_color, foreground: FALLBACK_COLOURS.foreground_color },
  DARK: { background: "#0b1220", foreground: "#f8fafc" },
};

const pick = (value: string, fallback: string): string => (isValidHexColor(value) ? value.trim().toLowerCase() : fallback);

/**
 * A simulation of what a visitor sees on the organization's own domain, drawn from the colours
 * still being edited. Everything is decorative (`aria-hidden`): the controls beside it are the
 * accessible way to change a colour.
 *
 * Colours reach the DOM only through inline `style`, and only after the six-digit hex test in
 * `pick`: no `dangerouslySetInnerHTML`, no injected `<style>`, no string built into CSS from tenant
 * input (a tenant's token has to stay a token). The one derived value, `${accent}33`, appends two
 * hex digits to an already-validated colour to make it translucent.
 */
export const BrandPreview: React.FC<BrandPreviewProps> = ({ colours, scheme, brandName, logoUrl, hostname }) => {
  const [surface, setSurface] = useState<Surface>("signin");
  const logoImage = useImageFallback(logoUrl);
  const defaults = SCHEME_DEFAULTS[scheme];
  const primary = pick(colours.primary_color, FALLBACK_COLOURS.primary_color);
  const accent = pick(colours.accent_color, FALLBACK_COLOURS.accent_color);
  const background = pick(colours.background_color, defaults.background);
  const foreground = pick(colours.foreground_color, defaults.foreground);
  const onPrimary = readableHexOn(primary);
  const name = brandName.trim() || "Your brand";
  const showLogo = Boolean(logoUrl) && !logoImage.failed;

  const mark = showLogo ? (
    <img src={logoUrl ?? undefined} alt="" className="h-7 w-auto" style={{ maxWidth: 140 }} onError={logoImage.onError} />
  ) : (
    <span
      className="flex h-7 w-7 items-center justify-center rounded-lg text-[13px] font-bold"
      style={{ backgroundColor: primary, color: onPrimary }}
    >
      {name.charAt(0).toUpperCase()}
    </span>
  );

  return (
    <div data-testid="brand-preview" className="space-y-3">
      <div role="tablist" aria-label="Preview surface" className="inline-flex rounded-lg bg-muted/70 p-0.5">
        {SURFACES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={surface === item.id}
            onClick={() => setSurface(item.id)}
            className={`rounded-md px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 ${
              surface === item.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div aria-hidden className="overflow-hidden rounded-xl border border-[hsl(var(--border-strong)/0.6)] bg-card shadow-md">
        <div className="flex items-center gap-3 border-b border-border/70 bg-muted/50 px-3 py-2">
          <span className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-red-400/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-400/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
          </span>
          <span className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-background/80 px-2.5 py-1 text-[11px] text-muted-foreground">
            <Lock className="h-3 w-3 shrink-0" />
            <span className="truncate">{hostname}</span>
          </span>
        </div>

        {surface === "signin" ? (
          <div
            className="relative flex min-h-[19rem] items-center justify-center overflow-hidden px-4 py-8"
            style={{
              backgroundColor: background,
              color: foreground,
              backgroundImage: `radial-gradient(60% 55% at 50% 0%, ${accent}40, transparent 70%)`,
            }}
          >
            <div className="w-full max-w-[17rem] space-y-4">
              <div className="flex items-center justify-center gap-2.5">
                {mark}
                <span className="truncate text-base font-semibold tracking-tight">{name}</span>
              </div>
              <div
                className="space-y-3 rounded-xl border p-4"
                style={{ borderColor: `${foreground}26`, backgroundColor: `${foreground}0d` }}
              >
                <div>
                  <p className="text-sm font-semibold">Welcome back</p>
                  <p className="text-[11px]" style={{ opacity: 0.7 }}>
                    Sign in to continue to your workspace.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <div className="rounded-md border px-2.5 py-1.5 text-[11px]" style={{ borderColor: `${foreground}33`, opacity: 0.75 }}>
                    name@company.com
                  </div>
                  <div className="rounded-md border px-2.5 py-1.5 text-[11px]" style={{ borderColor: `${foreground}33`, opacity: 0.75 }}>
                    ••••••••••
                  </div>
                </div>
                <div className="rounded-md py-1.5 text-center text-xs font-semibold" style={{ backgroundColor: primary, color: onPrimary }}>
                  Continue
                </div>
                <div className="rounded-md border py-1.5 text-center text-xs font-semibold" style={{ borderColor: `${accent}99`, color: accent }}>
                  Single sign-on
                </div>
                <p className="text-center text-[11px]">
                  New here? <span className="font-semibold underline" style={{ color: primary }}>Sign up</span>
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex min-h-[19rem] bg-zinc-50 text-zinc-900">
            <div className="hidden w-32 shrink-0 space-y-3 border-r border-zinc-200 bg-white p-3 sm:block">
              <div className="flex items-center gap-2">
                {mark}
                <span className="truncate text-xs font-semibold">{name}</span>
              </div>
              <ul className="space-y-1 text-[11px] font-medium">
                {[
                  { label: "Overview", icon: LayoutDashboard, active: true },
                  { label: "Documents", icon: FileText, active: false },
                  { label: "Members", icon: Users, active: false },
                  { label: "Settings", icon: Settings, active: false },
                ].map(({ label, icon: Icon, active }) => (
                  <li
                    key={label}
                    className="flex items-center gap-1.5 rounded-md px-2 py-1.5"
                    style={active ? { backgroundColor: `${primary}1f`, color: primary } : { color: "#52525b" }}
                  >
                    <Icon className="h-3 w-3" />
                    {label}
                  </li>
                ))}
              </ul>
            </div>
            <div className="min-w-0 flex-1 space-y-3 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2 py-1 text-[11px] text-zinc-500">
                  <Search className="h-3 w-3" />
                  Search
                </span>
                <span className="rounded-md px-2.5 py-1 text-[11px] font-semibold" style={{ backgroundColor: primary, color: onPrimary }}>
                  New document
                </span>
              </div>
              <div className="space-y-2.5 rounded-lg border border-zinc-200 bg-white p-3">
                <p className="text-xs font-semibold">Processing this week</p>
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
                  <div className="h-full w-2/3 rounded-full" style={{ backgroundImage: `linear-gradient(90deg, ${primary}, ${accent})` }} />
                </div>
                <p className="text-[11px] text-zinc-500">
                  128 documents · <span className="font-semibold" style={{ color: primary }}>View all</span>
                </p>
              </div>
              <div className="flex gap-2 text-[10px] font-semibold">
                <span className="rounded-full px-2 py-0.5" style={{ backgroundColor: `${primary}1f`, color: primary }}>
                  Verified
                </span>
                <span className="rounded-full border px-2 py-0.5" style={{ borderColor: primary, color: primary }}>
                  Focus ring
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        {surface === "signin"
          ? "The sign-in page uses all four colours and the colour scheme."
          : "Inside the app only the primary colour applies; light or dark stays each person's own choice."}
      </p>
      <ul className="grid gap-1.5 text-xs sm:grid-cols-2" aria-label="Readability">
        <ReadabilityRow label="Text on background" ratio={contrastRatio(foreground, background)} />
        <ReadabilityRow label="Primary on background" ratio={contrastRatio(primary, background)} />
      </ul>
    </div>
  );
};

const ReadabilityRow: React.FC<{ readonly label: string; readonly ratio: number }> = ({ label, ratio }) => {
  const good = ratio >= 4.5;
  return (
    <li className="flex items-center justify-between gap-2 rounded-lg border border-border/70 bg-muted/30 px-2.5 py-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={`fp-num whitespace-nowrap rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${
          good ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/10 text-amber-800 dark:text-amber-300"
        }`}
      >
        {ratio.toFixed(1)}:1 · {good ? "Readable" : "Low contrast"}
      </span>
    </li>
  );
};

export default BrandPreview;
