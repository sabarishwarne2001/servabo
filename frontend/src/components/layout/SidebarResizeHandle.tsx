import React, { useCallback, useRef } from "react";

import {
  clampWidth,
  getSidebarWidth,
  resetSidebarWidth,
  setSidebarWidth,
  useSidebarWidth,
  type SidebarSpec,
} from "./sidebarWidth";

interface SidebarResizeHandleProps {
  readonly spec: SidebarSpec;
  /** What the handle is called for a screen reader, e.g. "Resize the sidebar". */
  readonly label?: string;
  /**
   * The widest the sidebar may get, as a share of the window (the page must keep room to be used). Phone drawers pass a
   * larger share than the desktop shells.
   */
  readonly viewportShare?: number;
  /** Where the handle sits. `straddle` centres it on the sidebar's edge; `inside` keeps it within the sidebar (phone drawers). */
  readonly edge?: "straddle" | "inside";
  readonly className?: string;
}

const KEY_STEP = 16;
const KEY_STEP_LARGE = 48;
const DRAGGING = "sidebarDragging";

const limitFor = (share: number): number => (typeof window === "undefined" ? Infinity : window.innerWidth * share);

/**
 * The draggable divider on a sidebar's right edge.
 *
 * One mechanism for mouse, finger and pen (pointer events, with the pointer captured so the drag keeps going when it
 * leaves the strip), and for the keyboard: it is a focusable separator, Left and Right change the width (Shift for
 * bigger steps), Home and End go to the narrowest and widest, and a double click or Enter puts it back to the default.
 * While dragging, the page does not select text and animations pause (see `html[data-sidebar-dragging]` in index.css),
 * so the sidebar follows the pointer exactly.
 */
export const SidebarResizeHandle: React.FC<SidebarResizeHandleProps> = ({
  spec,
  label = "Resize the sidebar",
  viewportShare = 0.5,
  edge = "straddle",
  className = "",
}) => {
  const drag = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null);
  const frame = useRef<number | null>(null);
  const now = useSidebarWidth(spec);

  const limit = useCallback(() => limitFor(viewportShare), [viewportShare]);

  const apply = useCallback(
    (value: number, persist: boolean) => {
      setSidebarWidth(spec, value, persist, limit());
    },
    [spec, limit],
  );

  const end = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const current = drag.current;
      if (!current || current.pointerId !== event.pointerId) {
        return;
      }
      drag.current = null;
      if (frame.current !== null) {
        window.cancelAnimationFrame(frame.current);
        frame.current = null;
      }
      delete document.documentElement.dataset[DRAGGING];
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        /* already released */
      }
      // Write the width to the browser once, at the end.
      apply(getSidebarWidth(spec), true);
    },
    [apply, spec],
  );

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>): void => {
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }
    event.preventDefault();
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: getSidebarWidth(spec) };
    event.currentTarget.setPointerCapture(event.pointerId);
    document.documentElement.dataset[DRAGGING] = "true";
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>): void => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) {
      return;
    }
    const x = event.clientX;
    if (frame.current !== null) {
      window.cancelAnimationFrame(frame.current);
    }
    frame.current = window.requestAnimationFrame(() => {
      frame.current = null;
      apply(current.startWidth + (x - current.startX), false);
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
    const width = getSidebarWidth(spec);
    switch (event.key) {
      case "ArrowLeft":
        apply(width - step, true);
        break;
      case "ArrowRight":
        apply(width + step, true);
        break;
      case "Home":
        apply(spec.min, true);
        break;
      case "End":
        apply(spec.max, true);
        break;
      case "Enter":
        resetSidebarWidth(spec);
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  const onDoubleClick = (): void => {
    resetSidebarWidth(spec);
  };

  const position = edge === "straddle" ? "right-0 translate-x-1/2" : "right-0";
  const max = clampWidth(spec, spec.max, limit());

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={spec.min}
      aria-valuemax={max}
      aria-valuenow={Math.min(now, max)}
      tabIndex={0}
      data-sidebar-resize-handle={spec.key}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onKeyDown={onKeyDown}
      onDoubleClick={onDoubleClick}
      // A wider strip for a finger; `touch-action: none` hands the gesture to the divider, not to scrolling.
      style={{ touchAction: "none" }}
      className={`group absolute inset-y-0 z-30 w-3 cursor-col-resize outline-none [@media(pointer:coarse)]:w-6 ${position} ${className}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-transparent transition-colors duration-150 group-hover:bg-primary/40 group-focus-visible:bg-primary group-active:bg-primary ${
          edge === "inside" ? "[@media(pointer:coarse)]:bg-border" : ""
        }`}
      />
    </div>
  );
};

export default SidebarResizeHandle;
