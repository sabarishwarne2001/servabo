import React from "react";
import { Lock } from "lucide-react";

import { BUTTON_SECONDARY, HINT, SURFACE } from "@/components/ui/primitives";

/**
 * What a plan without `capability.gst_credit` sees in place of a list: the numbers above are real, and this
 * says plainly what Business adds. The button opens the upgrade dialog the sidebar uses.
 */
export const PreviewLock: React.FC<{
  readonly title: string;
  readonly teaser: string;
  readonly onUpgrade: () => void;
}> = ({ title, teaser, onUpgrade }) => (
  <section className={`${SURFACE} space-y-3 p-6`} aria-labelledby="gst-lock-title" data-testid="gst-preview-lock">
    <div className="flex items-center gap-2">
      <Lock className="h-4 w-4 text-muted-foreground" aria-hidden />
      <h2 id="gst-lock-title" className="text-[15px] font-semibold text-foreground">
        {title}
      </h2>
    </div>
    <p className="text-sm text-muted-foreground">{teaser}</p>
    <p className={HINT}>
      Your figures above are real and stay open on every plan. Business and Enterprise add the supplier list, the invoice
      list with the books beside GSTR-2B, recommendations for the GST portal&apos;s Invoice Management System, the Excel
      export and supplier reminders.
    </p>
    <button type="button" className={BUTTON_SECONDARY} onClick={onUpgrade}>
      See what Business adds
    </button>
  </section>
);

export default PreviewLock;
