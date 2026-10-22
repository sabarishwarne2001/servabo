/**
 * Session J — a rule's history: every save as a plain-words list of what changed, with Restore.
 */

import React, { useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Loader2, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { ApiError } from "@/services/api/errors";
import { automationApi } from "@/services/api/automation";
import { automationKeys } from "@/services/api/queryKeys";
import type { AutomationRule } from "@/types/automation";
import type { RuleVersion } from "@/types/automationVolume";
import { formatTimestamp } from "@/utils/displayTime";

interface VersionHistoryDialogProps {
  readonly open: boolean;
  readonly workspaceId: string;
  readonly rule: AutomationRule | null;
  readonly canRestore: boolean;
  readonly onClose: () => void;
}

export const VersionHistoryDialog: React.FC<VersionHistoryDialogProps> = ({ open, workspaceId, rule, canRestore, onClose }) => {
  const queryClient = useQueryClient();
  const [restoring, setRestoring] = useState<RuleVersion | null>(null);

  const history = useQuery({
    queryKey: automationKeys.versions(workspaceId, rule?.id ?? ""),
    queryFn: () => automationApi.getRuleVersions(workspaceId, rule?.id ?? ""),
    enabled: open && Boolean(rule),
  });

  const restore = useMutation({
    mutationFn: (version: number) => automationApi.restoreRuleVersion(workspaceId, rule?.id ?? "", version),
    onSuccess: async (restored, version) => {
      toast.success(`Restored version ${version} of “${restored.name}” as a new version.`);
      setRestoring(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: automationKeys.rules(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: automationKeys.versions(workspaceId, rule?.id ?? "") }),
      ]);
    },
    onError: (error: unknown) => {
      setRestoring(null);
      toast.error(error instanceof ApiError ? error.message : "That version could not be restored.");
    },
  });

  if (!open || !rule) {return null;}

  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="version-history-title"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !restoring) {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-border bg-card px-5 py-3">
          <h2 id="version-history-title" className="flex items-center gap-2 text-sm font-semibold">
            <History className="h-4 w-4 text-primary" aria-hidden="true" /> History of “{rule.name}”
          </h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted" aria-label="Close the history">
            <X className="h-5 w-5" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {history.isLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status"><Loader2 className="h-4 w-4 animate-spin" /> Loading the history…</p>
          ) : history.isError || !history.data ? (
            <p className="text-sm text-destructive" role="alert">The history could not be loaded.</p>
          ) : history.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">This rule has no saved history yet. Versions are recorded from the next save.</p>
          ) : (
            <ol className="space-y-3">
              {history.data.items.map((item, index) => (
                <li key={item.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold">
                        Version {item.version}
                        {index === 0 && <span className="ml-2 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">Current</span>}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {formatTimestamp(item.created_at)}
                        {item.created_by_name ? ` · ${item.created_by_name}` : ""}
                      </p>
                    </div>
                    {canRestore && index > 0 && (
                      <button
                        type="button"
                        onClick={() => setRestoring(item)}
                        aria-label={`Restore version ${item.version}`}
                        className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs font-semibold hover:bg-muted"
                      >
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Restore
                      </button>
                    )}
                  </div>
                  {item.note && item.note !== item.changes[0] && <p className="mt-1.5 text-xs italic">“{item.note}”</p>}
                  <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                    {item.changes.length === 0 ? <li>Saved with no change to the steps</li> : item.changes.map((change) => <li key={change}>{change}</li>)}
                  </ul>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={restoring !== null}
        tone="primary"
        title={`Restore version ${restoring?.version ?? ""}?`}
        message="The rule goes back to how it was then. This is saved as a new version, so nothing is lost and you can undo it the same way."
        confirmText="Restore this version"
        cancelText="Keep the current one"
        loading={restore.isPending}
        onConfirm={() => restoring && restore.mutate(restoring.version)}
        onCancel={() => setRestoring(null)}
      />
    </div>,
    document.body,
  );
};
