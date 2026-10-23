import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { EyeOff, Loader2, Lock } from "lucide-react";

import { CAPABILITY } from "@/constants/capabilities";
import { useCapabilityAccess } from "@/hooks/useCapabilityAccess";
import { isAtLeast } from "@/permissions/workspacePermissions";
import { useResolvedTenant } from "@/routes/TenantContext";
import { redactionPath } from "@/routes/tenantPaths";
import { ApiError } from "@/services/api/client";
import { getRedactionSuggestion } from "@/services/api/ingestion";
import { ingestionKeys } from "@/services/api/queryKeys";
import { startRedaction } from "@/services/api/redaction";

/**
 * The redaction profiles the engine defines, with the words a reviewer reads.
 *
 * Keys mirror `PROFILES` in app/services/redaction/vocabulary.py.
 * verify_arch36.py fails when the two sets differ: an extra key here is a
 * button that always answers 422, and a missing one is a profile nobody can
 * start.
 */
export const REDACTION_PROFILE_LABELS: Readonly<Record<string, { label: string; hint: string }>> = {
  all_identifiers: {
    label: "All identifiers",
    hint: "Every kind of identifier the engine detects",
  },
  financial: {
    label: "Financial",
    hint: "Card numbers, IBAN, SSN, PAN, GSTIN",
  },
  hipaa_safe_harbor: {
    label: "HIPAA Safe Harbor",
    hint: "Names, dates of birth, SSN, card numbers, contact details",
  },
  india_kyc: {
    label: "India KYC",
    hint: "Aadhaar, PAN, GSTIN, date of birth, contact details",
  },
};

interface StartRedactionButtonProps {
  readonly workspaceId: string;
  readonly workItemId: string;
  /** `work_items.file_type` — the stored MIME type. */
  readonly mimeType: string;
  readonly status: string;
}

/**
 * ARCH36-S1:redaction-entry — the only way into the Redaction Studio.
 *
 * ARCH-32 shipped the studio at `redactions/:jobId` and `startRedaction` in
 * the API client, and nothing called `startRedaction`. With no job there is no
 * id, and with no id the studio cannot be opened, so the feature was
 * unreachable however the navigation was arranged.
 *
 * Shown for completed PDFs only, because the engine refuses anything else
 * (it rebuilds a PDF from rendered pages and needs extraction geometry).
 * Hidden below CONTRIBUTOR, which is what the endpoint requires. When the
 * tier lacks the capability the button renders locked rather than hidden;
 * the endpoint's capability gate is what actually refuses.
 */
const StartRedactionButton: React.FC<StartRedactionButtonProps> = ({
  workspaceId,
  workItemId,
  mimeType,
  status,
}) => {
  const navigate = useNavigate();
  const { organization, workspace, workspaceRole } = useResolvedTenant();
  const capability = useCapabilityAccess(organization.organization_id, CAPABILITY.redaction);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const onPointer = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // F-408: the profile of the enabled document pack that fits this document is offered first and focused.
  const suggestion = useQuery({
    queryKey: ingestionKeys.redactionSuggestion(workspaceId, workItemId),
    queryFn: () => getRedactionSuggestion(workspaceId, workItemId),
    enabled: open && capability.granted,
    staleTime: 60_000,
  });
  const suggestedProfile =
    suggestion.data && suggestion.data.profile in REDACTION_PROFILE_LABELS ? suggestion.data : null;
  const suggestedRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (open && suggestedProfile) {
      suggestedRef.current?.focus();
    }
  }, [open, suggestedProfile]);

  const start = useMutation({
    mutationFn: (profileKey: string) => startRedaction(workspaceId, workItemId, profileKey),
    onSuccess: (job) => {
      setOpen(false);
      navigate(redactionPath(organization.organization_slug, workspace.slug, job.id));
    },
    onError: (error: unknown) => {
      toast.error(
        error instanceof ApiError ? error.message : "Redaction could not be started.",
      );
    },
  });

  const isPdf = mimeType.toLowerCase() === "application/pdf";
  if (!isPdf || status !== "COMPLETED" || !isAtLeast(workspaceRole, "CONTRIBUTOR")) {
    return null;
  }

  const buttonClass =
    "inline-flex items-center rounded-lg border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50";

  if (!capability.isLoading && !capability.granted) {
    return (
      <button
        type="button"
        disabled
        title="Redaction is not included in your plan"
        className={buttonClass}
      >
        <Lock className="mr-2 h-4 w-4" aria-hidden />
        Redact
      </button>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={capability.isLoading || start.isPending}
        aria-haspopup="menu"
        aria-expanded={open}
        className={buttonClass}
      >
        {start.isPending ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <EyeOff className="mr-2 h-4 w-4" aria-hidden />
        )}
        Redact
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Redaction profile"
          className="absolute right-0 z-30 mt-2 w-72 fp-card p-1 shadow-lg"
        >
          <p className="px-3 py-2 text-xs text-muted-foreground">
            Choose what to detect. You review every region before anything is
            applied.
          </p>
          {Object.entries(REDACTION_PROFILE_LABELS)
            .sort(([a], [b]) => Number(b === suggestedProfile?.profile) - Number(a === suggestedProfile?.profile))
            .map(([key, profile]) => {
              const suggested = key === suggestedProfile?.profile;
              return (
                <button
                  key={key}
                  ref={suggested ? suggestedRef : undefined}
                  type="button"
                  role="menuitem"
                  data-suggested={suggested ? "true" : undefined}
                  onClick={() => start.mutate(key)}
                  className={`flex w-full flex-col items-start rounded-lg px-3 py-2 text-left hover:bg-muted ${
                    suggested ? "bg-primary/5 ring-1 ring-primary/30" : ""
                  }`}
                >
                  <span className="text-sm font-semibold">{profile.label}</span>
                  <span className="text-xs text-muted-foreground">{profile.hint}</span>
                  {suggested ? (
                    <span className="mt-0.5 text-[11px] font-medium text-primary">
                      Suggested by your {suggestedProfile?.preset_label} pack
                    </span>
                  ) : null}
                </button>
              );
            })}
        </div>
      )}
    </div>
  );
};

export default StartRedactionButton;
