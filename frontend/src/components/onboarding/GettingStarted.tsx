/**
 * The workspace's first-run checklist: a short path to the first money found (Final session 1, 2C).
 *
 * The steps come from the server, which ticks each one from real data (a document exists, one has been read, a GSTR-2B is
 * imported, Helm is opened, a recipe exists, a teammate is invited), so the card is never out of step with what has been done.
 * A person only sees the steps they can do. Where a feature is a preview on the plan, the step says what the plan or add-on
 * unlocks. When the value receipt has its first confirmed figure, the card says so in one line. It can be hidden (remembered in
 * this browser) and brought back from a link that stays on the page.
 */
import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CheckCircle2, Circle, Copy, Loader2, Sparkles, X } from "lucide-react";

import { workItemApi } from "@/services/api/workItem";
import { dashboardKeys, workItemKeys } from "@/services/api/queryKeys";
import { getGettingStarted, gettingStartedKeys, type GettingStartedKey } from "@/services/api/gettingStarted";
import { getInboundEmail, inboundEmailKeys } from "@/services/api/inboundEmail";
import {
  automationPath,
  gstPath,
  helmPath,
  organizationBillingPath,
  organizationMembersPath,
  workItemsPath,
  workspaceSettingsPath,
} from "@/routes/tenantPaths";
import { ApiError } from "@/services/api/client";

interface GettingStartedProps {
  readonly workspaceId: string;
  readonly orgSlug: string;
  readonly workspaceSlug: string;
  readonly canUpload: boolean;
  /** Workspace administrators can see the workspace's email-in address. */
  readonly canAdmin: boolean;
}

const storageKey = (workspaceId: string): string => `fp.getting-started.hidden.${workspaceId}`;

const readHidden = (workspaceId: string): boolean => {
  try {
    return window.localStorage.getItem(storageKey(workspaceId)) === "1";
  } catch {
    return false;
  }
};

const writeHidden = (workspaceId: string, hidden: boolean): void => {
  try {
    if (hidden) {
      window.localStorage.setItem(storageKey(workspaceId), "1");
    } else {
      window.localStorage.removeItem(storageKey(workspaceId));
    }
  } catch {
    /* private window: remembered for this visit only */
  }
};

const linkClass = "text-xs font-medium text-primary hover:underline";

export const GettingStarted: React.FC<GettingStartedProps> = ({ workspaceId, orgSlug, workspaceSlug, canUpload, canAdmin }) => {
  const queryClient = useQueryClient();
  const [hidden, setHidden] = useState(() => readHidden(workspaceId));

  const view = useQuery({
    queryKey: gettingStartedKeys.all(workspaceId),
    queryFn: () => getGettingStarted(workspaceId),
    // While a document is still being read the card checks again; once it is read the page's other queries refresh it.
    refetchInterval: (query) => {
      const steps = query.state.data?.steps ?? [];
      const documents = steps.find((s) => s.key === "documents");
      const read = steps.find((s) => s.key === "read");
      return documents?.done && read && !read.done ? 5_000 : false;
    },
    retry: false,
  });
  const documentsOpen = view.data?.steps.some((s) => s.key === "documents" && !s.done) ?? false;
  const address = useQuery({
    queryKey: inboundEmailKeys.all(workspaceId),
    queryFn: () => getInboundEmail(workspaceId),
    enabled: !hidden && canAdmin && documentsOpen,
    retry: false,
  });

  const sample = useMutation({
    mutationFn: () => workItemApi.uploadSampleDocument(workspaceId),
    onSuccess: async () => {
      toast.success("Sample invoice added. Servabo is reading it now; it takes about a minute.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: dashboardKeys.all(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: workItemKeys.all(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: gettingStartedKeys.all(workspaceId) }),
      ]);
    },
    onError: (error: unknown) => {
      toast.error(error instanceof ApiError ? error.message : "The sample could not be added. Please try again.");
    },
  });

  const setHiddenAndRemember = (next: boolean): void => {
    writeHidden(workspaceId, next);
    setHidden(next);
  };

  const copyAddress = async (value: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("Address copied.");
    } catch {
      toast.error("The address could not be copied. Select it and copy it by hand.");
    }
  };

  if (!view.data || view.data.total === 0) {
    return null;
  }
  const { steps, done, total, money } = view.data;
  if (done === total) {
    return null;
  }

  if (hidden) {
    return (
      <p className="text-xs text-muted-foreground">
        <button type="button" onClick={() => setHiddenAndRemember(false)} className="font-medium text-primary hover:underline">
          Show getting started ({done} of {total} done)
        </button>
      </p>
    );
  }

  const action = (key: GettingStartedKey): React.ReactNode => {
    switch (key) {
      case "documents":
        return (
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            {canUpload ? <>Drop files or a zip above, or</> : null}
            {canUpload ? (
              <button
                type="button"
                onClick={() => sample.mutate()}
                disabled={sample.isPending}
                className="fp-btn fp-btn-secondary h-7 text-xs"
              >
                {sample.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                Try a sample invoice
              </button>
            ) : null}
            {canAdmin ? (
              address.data?.enabled && address.data.address ? (
                <span className="flex flex-wrap items-center gap-1">
                  or email them to
                  <code className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-foreground" data-testid="getting-started-address">
                    {address.data.address}
                  </code>
                  <button
                    type="button"
                    onClick={() => void copyAddress(address.data?.address ?? "")}
                    aria-label="Copy the email-in address"
                    className="rounded-md p-1 hover:bg-muted"
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </span>
              ) : (
                <Link to={`${workspaceSettingsPath(orgSlug, workspaceSlug)}?section=inbound`} className={linkClass}>
                  or set up email-in
                </Link>
              )
            ) : null}
          </span>
        );
      case "read":
        return (
          <Link to={workItemsPath(orgSlug, workspaceSlug)} className={linkClass}>
            Open your documents
          </Link>
        );
      case "gst":
        return (
          <Link to={gstPath(orgSlug, workspaceSlug)} className={linkClass}>
            Open GST Credit
          </Link>
        );
      case "helm":
        return (
          <Link to={helmPath(orgSlug)} className={linkClass}>
            Open Helm
          </Link>
        );
      case "recipe":
        return (
          <Link to={automationPath(orgSlug, workspaceSlug)} className={linkClass}>
            Browse recipes
          </Link>
        );
      case "invite":
        return (
          <Link to={organizationMembersPath(orgSlug)} className={linkClass}>
            Go to members
          </Link>
        );
      default:
        return null;
    }
  };

  return (
    <section aria-labelledby="getting-started" className="fp-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="getting-started" className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Get started with Servabo
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {done} of {total} done. Each step ticks itself when you have done it.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setHiddenAndRemember(true)}
          aria-label="Hide getting started"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
      {money ? (
        <p className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200" data-testid="getting-started-money">
          {money.text}{" "}
          <Link to={organizationBillingPath(orgSlug)} className="font-medium underline">
            See the receipt
          </Link>
        </p>
      ) : null}
      <ol className="mt-4 space-y-3" aria-label="Getting started steps">
        {steps.map((step) => (
          <li key={step.key} className="space-y-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {step.done ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
              ) : (
                <Circle className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              )}
              <span className={`text-sm ${step.done ? "text-muted-foreground line-through" : "text-foreground"}`}>
                {step.title}
                <span className="sr-only">{step.done ? " (done)" : " (to do)"}</span>
              </span>
              {/* A finished step still links to the place: the work is done, not hidden. */}
              {step.done && step.key === "documents" ? null : action(step.key)}
            </div>
            {step.note && !step.done ? <p className="pl-7 text-xs text-muted-foreground">{step.note}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
};

export default GettingStarted;
