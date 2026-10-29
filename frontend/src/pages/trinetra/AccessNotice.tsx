import { Link } from "react-router-dom";
import { Lock } from "lucide-react";
import { BUTTON_SECONDARY, SURFACE } from "@/components/ui/primitives";
import type { TrinetraAccess } from "@/services/api/trinetra";
import { accessNotice } from "./model";

/** The one sentence about why live TDS credit is closed (a pilot not joined, a plan without it, not open yet). Silent when it is open. */
export default function AccessNotice({
  access,
  billingPath,
}: {
  access: TrinetraAccess;
  billingPath: string;
}) {
  const notice = accessNotice(access);
  if (!notice) {
    return null;
  }
  return (
    <section
      className={`${SURFACE} flex flex-wrap items-start gap-3 p-4 text-sm`}
      aria-label="Availability"
      data-testid={`trinetra-access-${notice.kind}`}
    >
      <Lock className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{notice.title}</p>
        <p className="mt-1 text-muted-foreground">{notice.message}</p>
      </div>
      {notice.kind === "not_entitled" && (
        <Link className={BUTTON_SECONDARY} to={billingPath}>
          See the plans
        </Link>
      )}
    </section>
  );
}
