import React from "react";
import { useQuery } from "@tanstack/react-query";

import { ReceiptCard } from "@/components/billing/ValueReceipt";
import { getBillingAccessSummary } from "@/services/api/billing";
import { billingKeys } from "@/services/api/queryKeys";

/**
 * Session G — "Your trial so far", above the plan cards while the organization is on its trial (or just past it, and
 * has not subscribed): the person choosing a plan sees what it keeps. Shares the access summary the trial banner reads.
 */
export const TrialReceiptCard: React.FC<{ readonly organizationId: string }> = ({ organizationId }) => {
  const { data: summary } = useQuery({
    queryKey: billingKeys.accessSummary(organizationId),
    queryFn: () => getBillingAccessSummary(organizationId),
    enabled: Boolean(organizationId),
    staleTime: 60_000,
    retry: false,
  });
  const trial = summary?.trial;
  const onTrial = Boolean(trial && (trial.state === "ACTIVE" || (trial.state === "ENDED" && !trial.lapsed)));
  return (
    <ReceiptCard
      organizationId={organizationId}
      period="trial"
      title="Your trial so far"
      testId="billing-trial-receipt"
      enabled={onTrial}
      quietLine="Nothing found yet. Upload invoices and import your GSTR-2B, and what Servabo finds in them appears here."
    />
  );
};

export default TrialReceiptCard;
