import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Clock, Lock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import ConfirmDialog from "@/components/common/ConfirmDialog";
import { useAskPlanOwners } from "@/components/billing/AskPlanOwners";
import { getBillingAccessSummary } from "@/services/api/billing";
import { billingKeys } from "@/services/api/queryKeys";
import { pollUnlessRefused } from "@/services/api/polling";
import { DownloadReceiptPdf, ReceiptBody, useValueReceipt } from "@/components/billing/ValueReceipt";
import { organizationBillingPath } from "@/routes/tenantPaths";
import { formatTimestampDate } from "@/utils/displayTime";

/** The banner shows for the trial's last three days, as N-052 decided (day 12 of the 14-day trial since N-187). */
const BANNER_DAYS_LEFT = 3;

const dismissKey = (organizationId: string): string => `servabo.trialEnded.seen.${organizationId}`;

const readDismissed = (organizationId: string): boolean => {
  try {
    return window.sessionStorage.getItem(dismissKey(organizationId)) === "1";
  } catch {
    return false;
  }
};

const writeDismissed = (organizationId: string): void => {
  try {
    window.sessionStorage.setItem(dismissKey(organizationId), "1");
  } catch {
    // Private windows can refuse storage; the dialog then shows once per page load.
  }
};

export interface TrialBannerProps {
  readonly organizationId: string;
  readonly organizationSlug: string;
  /** Only owners can choose a plan (`can_manage_billing`); everyone else is told whom to ask. */
  readonly canChoosePlan: boolean;
  /**
   * Session G: owners, admins and the billing role also see what Servabo found in the trial (the value receipt):
   * its headline in the banner's last three days, and a receipt card in the "trial has ended" dialog. Everyone else
   * keeps today's text.
   */
  readonly canSeeReceipt?: boolean;
}

/**
 * Campaign session 2 — the free trial (owner decision N-052; 14 days since Final session 2A, N-187).
 *
 * Every member reads the same member-readable summary the read-only gate uses,
 * so what the banner says and what the server refuses cannot disagree.
 *
 * - During the last three days: how many days are left, and "Choose a plan"
 *   for an owner or "Ask <owner> to choose a plan" for everyone else.
 * - After the end: a persistent strip saying what still works, and once per
 *   browser session a full-page dialog ("Your trial has ended") whose primary
 *   action takes an owner to the plan cards. "Continue read-only" closes it:
 *   reading, search, export and member management stay open by design.
 */
export const TrialBanner: React.FC<TrialBannerProps> = ({
  organizationId,
  organizationSlug,
  canChoosePlan,
  canSeeReceipt = false,
}) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const plansPath = organizationBillingPath(organizationSlug);
  const [dismissed, setDismissed] = useState(() => readDismissed(organizationId));
  const askToChoose = useAskPlanOwners("choose a plan", organizationId);
  const askToSubscribe = useAskPlanOwners("subscribe to a plan", organizationId);

  const { data: summary } = useQuery({
    queryKey: billingKeys.accessSummary(organizationId),
    queryFn: () => getBillingAccessSummary(organizationId),
    enabled: Boolean(organizationId),
    refetchInterval: pollUnlessRefused(120_000),
    refetchOnWindowFocus: true,
    staleTime: 60_000,
    retry: false,
  });

  const trial = summary?.trial;
  const receiptDue =
    trial?.state === "ENDED" ? !trial.lapsed : trial?.state === "ACTIVE" && (trial.days_left ?? 0) <= BANNER_DAYS_LEFT;
  const { data: receipt } = useValueReceipt(organizationId, "trial", canSeeReceipt && Boolean(receiptDue));
  if (!trial || trial.state === "NONE") {
    return null;
  }

  if (trial.state === "ACTIVE") {
    const daysLeft = trial.days_left ?? 0;
    if (daysLeft > BANNER_DAYS_LEFT) {
      return null;
    }
    return (
      <div
        role="status"
        data-testid="trial-banner"
        className="border-b border-primary/30 bg-primary/5 px-4 py-2.5"
      >
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3">
          <Clock className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <p className="min-w-0 flex-1 text-sm text-foreground">
            <span className="font-semibold">
              Your free trial ends in {daysLeft} {daysLeft === 1 ? "day" : "days"}
            </span>
            {trial.ends_at ? ` (${formatTimestampDate(trial.ends_at)})` : ""}.{" "}
            {receipt?.headline ? (
              <>
                <span data-testid="trial-banner-headline">{receipt.headline}</span>{" "}
              </>
            ) : null}
            {canChoosePlan
              ? "Choose a plan to keep uploading and using the assistant without a pause."
              : askToChoose}
          </p>
          {canChoosePlan ? (
            <Link to={plansPath} className="fp-btn fp-btn-primary text-sm">
              Choose a plan
            </Link>
          ) : null}
        </div>
      </div>
    );
  }

  // Campaign session 4 (F-342): a former customer whose subscription ended is not told about a trial.
  const endedTitle = trial.lapsed ? "Your subscription has ended" : "Your free trial has ended";
  const onPlansPage = pathname.startsWith(plansPath);
  const closeDialog = () => {
    writeDismissed(organizationId);
    setDismissed(true);
  };

  return (
    <>
      <div
        role="alert"
        data-testid="trial-ended-banner"
        className="border-b border-destructive/40 bg-destructive/10 px-4 py-3"
      >
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3">
          <Lock className="h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-destructive">{endedTitle}</p>
            <p className="mt-0.5 text-sm text-foreground/80">
              You can still read, search and export everything. New uploads, the assistant
              and automations are paused until {canChoosePlan ? "you choose" : "someone chooses"} a
              plan. {canChoosePlan ? "" : askToSubscribe}
            </p>
          </div>
          {canChoosePlan && !onPlansPage ? (
            <Link to={plansPath} className="fp-btn fp-btn-primary text-sm">
              Choose a plan
            </Link>
          ) : null}
        </div>
      </div>
      <ConfirmDialog
        open={!dismissed && !onPlansPage}
        tone="primary"
        title={endedTitle}
        message={
          canChoosePlan
            ? "Choose a plan to upload documents, ask the assistant and run automations again. Nothing has been deleted: everyone can still read, search and export in the meantime."
            : `Uploads, the assistant and automations are paused. Nothing has been deleted, and you can still read, search and export. ${askToSubscribe}`
        }
        wide={Boolean(receipt)}
        confirmText={canChoosePlan ? "Choose a plan" : "Continue read-only"}
        cancelText="Continue read-only"
        hideCancel={!canChoosePlan}
        initialFocus="confirm"
        onConfirm={() => {
          closeDialog();
          if (canChoosePlan) {
            navigate(plansPath);
          }
        }}
        onCancel={closeDialog}
      >
        {receipt && (receipt.headline || receipt.found.length > 0) ? (
          <ReceiptBody
            receipt={receipt}
            maxFindings={4}
            onNavigate={closeDialog}
            testId="trial-ended-receipt"
            footer={<DownloadReceiptPdf organizationId={organizationId} period="trial" testId="trial-ended-receipt-pdf" />}
          />
        ) : null}
      </ConfirmDialog>
    </>
  );
};

export default TrialBanner;
