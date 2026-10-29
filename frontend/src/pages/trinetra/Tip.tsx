import { useId } from "react";
import { Info } from "lucide-react";

/** A small "where does this come from" note: opens on hover and on keyboard focus, never hides its text from a screen reader. */
export default function Tip({ label, children }: { label: string; children: string }) {
  const id = useId();
  return (
    <span className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="rounded-full text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
      >
        <Info className="h-3.5 w-3.5" aria-hidden />
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-20 mt-1 hidden w-64 -translate-x-1/2 rounded-md border border-border bg-popover p-2 text-xs font-normal text-popover-foreground shadow-md group-focus-within:block group-hover:block"
      >
        {children}
      </span>
    </span>
  );
}
