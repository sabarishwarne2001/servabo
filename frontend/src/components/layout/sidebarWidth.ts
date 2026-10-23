/**
 * How wide each sidebar is, remembered in this browser.
 *
 * Every sidebar that can be dragged wider or narrower names itself with a `SidebarSpec`. The three app shells (workspace,
 * organization, Helm) share one spec, so the width a person chooses follows them from page to page, and the same width is used
 * in the phone drawer (never wider than most of the screen). The assistant's conversation list and the settings section list
 * have their own. The store is outside React so a drag moves every copy of the sidebar together and the width is written to
 * the browser once, when the drag ends.
 */
import { useSyncExternalStore } from "react";

export interface SidebarSpec {
  /** Names the remembered width. */
  readonly key: string;
  readonly min: number;
  readonly max: number;
  /** The width before anyone has chosen one. */
  readonly initial: number;
}

/** The workspace, organization and Helm shells, and their phone drawers. */
export const SHELL_SIDEBAR: SidebarSpec = { key: "shell", min: 220, max: 420, initial: 260 };
/** The assistant's conversation list. */
export const ASSISTANT_SIDEBAR: SidebarSpec = { key: "assistant", min: 240, max: 560, initial: 340 };
/** The settings page's section list. */
export const SETTINGS_SIDEBAR: SidebarSpec = { key: "settings", min: 220, max: 420, initial: 280 };

const STORAGE_PREFIX = "servabo_sidebar_width.";

const widths = new Map<string, number>();
const listeners = new Map<string, Set<() => void>>();

/** The nearest allowed width. `limit` lowers the maximum, e.g. to half of a narrow window. */
export const clampWidth = (spec: SidebarSpec, value: number, limit: number = spec.max): number => {
  const max = Math.max(spec.min, Math.min(spec.max, limit));
  if (!Number.isFinite(value)) {
    return spec.initial;
  }
  return Math.round(Math.min(max, Math.max(spec.min, value)));
};

const read = (spec: SidebarSpec): number => {
  const known = widths.get(spec.key);
  if (known !== undefined) {
    return known;
  }
  let value = spec.initial;
  try {
    const stored = window.localStorage.getItem(STORAGE_PREFIX + spec.key);
    if (stored !== null) {
      const parsed = Number(stored);
      value = Number.isFinite(parsed) ? clampWidth(spec, parsed) : spec.initial;
    }
  } catch {
    /* private window: the width lasts for this visit */
  }
  widths.set(spec.key, value);
  return value;
};

export const getSidebarWidth = (spec: SidebarSpec): number => read(spec);

/** Sets the width (clamped). `persist` writes it to the browser; do that when a drag ends, not on every move. */
export const setSidebarWidth = (spec: SidebarSpec, value: number, persist = true, limit?: number): number => {
  const next = clampWidth(spec, value, limit);
  if (read(spec) !== next) {
    widths.set(spec.key, next);
    listeners.get(spec.key)?.forEach((notify) => notify());
  }
  if (persist) {
    try {
      window.localStorage.setItem(STORAGE_PREFIX + spec.key, String(next));
    } catch {
      /* private window */
    }
  }
  return next;
};

export const resetSidebarWidth = (spec: SidebarSpec): void => {
  setSidebarWidth(spec, spec.initial, false);
  try {
    window.localStorage.removeItem(STORAGE_PREFIX + spec.key);
  } catch {
    /* private window */
  }
};

const subscribe = (spec: SidebarSpec) => (notify: () => void) => {
  const set = listeners.get(spec.key) ?? new Set<() => void>();
  set.add(notify);
  listeners.set(spec.key, set);
  return () => {
    set.delete(notify);
  };
};

/** The sidebar's current width, in pixels. */
export const useSidebarWidth = (spec: SidebarSpec): number =>
  useSyncExternalStore(subscribe(spec), () => read(spec), () => spec.initial);

/** For tests: forget everything held in memory (the browser's copy is cleared by the test). */
export const forgetSidebarWidths = (): void => {
  widths.clear();
};
