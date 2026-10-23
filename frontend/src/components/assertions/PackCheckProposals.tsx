/**
 * Final session 1 (F-408): the checks the workspace's enabled document packs suggest, one click to add each.
 *
 * A pack lists the checks it recommends for its kind of document. Enabling the pack proposes them here; nothing is added until an
 * administrator clicks. A check the engine reads with an AI model (billed as assistant usage) says so on its button, and the click
 * is the confirmation. "Not for us" remembers the choice, so the check is not proposed again. Nothing shows when no pack is enabled,
 * when all its checks are added, or when the plan does not include Clause assertions.
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, Sparkles } from "lucide-react";

import { isAtLeast } from "@/permissions/workspacePermissions";
import { useResolvedTenant } from "@/routes/TenantContext";
import { errorMessage } from "@/services/api/errors";
import { acceptPackCheck, dismissPackCheck, listPackCheckProposals, type PackCheckProposal } from "@/services/api/ingestion";
import { ingestionKeys } from "@/services/api/queryKeys";

interface PackCheckProposalsProps {
  readonly workspaceId: string;
}

const SEVERITY_WORDS: Readonly<Record<string, string>> = {
  HIGH: "strict",
  MEDIUM: "usual",
  LOW: "relaxed",
};

export const PackCheckProposals: React.FC<PackCheckProposalsProps> = ({ workspaceId }) => {
  const queryClient = useQueryClient();
  // Only an administrator may add or turn down a suggestion; others do not see the section.
  const { workspaceRole } = useResolvedTenant();
  const canManage = isAtLeast(workspaceRole, "ADMIN");
  const proposals = useQuery({
    queryKey: ingestionKeys.packCheckProposals(workspaceId),
    queryFn: () => listPackCheckProposals(workspaceId),
    enabled: Boolean(workspaceId) && canManage,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ingestionKeys.packCheckProposals(workspaceId) });
    void queryClient.invalidateQueries({ queryKey: ["clause-checks", workspaceId] });
  };
  const accept = useMutation({
    mutationFn: (proposal: PackCheckProposal) => acceptPackCheck(workspaceId, proposal),
    onSuccess: () => {
      toast.success("Check added and switched on.");
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error, "The check could not be added.")),
  });
  const dismiss = useMutation({
    mutationFn: (proposal: PackCheckProposal) => dismissPackCheck(workspaceId, proposal.key),
    onSuccess: refresh,
    onError: (error) => toast.error(errorMessage(error, "The suggestion could not be set aside.")),
  });

  const list = proposals.data?.proposals ?? [];
  if (!canManage || !proposals.data?.available || list.length === 0) {
    return null;
  }

  return (
    <section className="fp-card p-5" aria-labelledby="pack-check-proposals-heading" data-testid="pack-check-proposals">
      <header className="mb-3">
        <h2 id="pack-check-proposals-heading" className="flex items-center gap-2 text-base font-semibold text-foreground">
          <Sparkles className="h-4 w-4" aria-hidden="true" /> Suggested by your document packs
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          The packs you enabled recommend these checks. Nothing is added until you add it; each one you add is switched on at once.
        </p>
      </header>
      <ul className="space-y-3">
        {list.map((proposal) => {
          const busy = (accept.isPending && accept.variables?.key === proposal.key) || (dismiss.isPending && dismiss.variables?.key === proposal.key);
          return (
            <li key={proposal.key} className="rounded-lg border border-border p-3">
              <p className="font-medium text-foreground">{proposal.sentence}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {proposal.preset_label} pack · {SEVERITY_WORDS[proposal.severity] ?? "usual"} confidence
                {proposal.understood_as ? ` · Understood as: ${proposal.understood_as}` : ""}
              </p>
              {proposal.requires_acknowledgement ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  An AI model reads this check on each document and it is billed as assistant usage. Adding it confirms that.
                </p>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => accept.mutate(proposal)}
                  disabled={busy}
                  className="fp-btn-primary inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {busy && accept.variables?.key === proposal.key ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {proposal.requires_acknowledgement ? "Add, read by an AI model" : "Add this check"}
                </button>
                <button
                  type="button"
                  onClick={() => dismiss.mutate(proposal)}
                  disabled={busy}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold hover:bg-muted disabled:opacity-50"
                >
                  Not for us
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
};

export default PackCheckProposals;
