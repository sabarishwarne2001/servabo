import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BUTTON_SECONDARY, SURFACE } from "@/components/ui/primitives";
import { apiClient } from "@/services/api/client";
import type { components } from "@/types/api.generated";

export default function ReconciliationRun({ workspaceId }: { workspaceId: string }) {
  const cache = useQueryClient();
  const base = `/workspaces/${encodeURIComponent(workspaceId)}/trinetra/reconciliation`;
  const start = useMutation({
    mutationFn: async () => (await apiClient.post<components["schemas"]["RunOut"]>(base)).data,
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
    },
  });
  const run = useQuery({
    queryKey: ["trinetra", workspaceId, "run", start.data?.job_id],
    enabled: Boolean(start.data),
    queryFn: async () =>
      (
        await apiClient.get<components["schemas"]["RunStatusOut"]>(
          `${base}/${encodeURIComponent(start.data!.job_id)}`,
        )
      ).data,
    refetchInterval: (query) =>
      ["SUCCEEDED", "DEAD"].includes(query.state.data?.status ?? "") ? false : 2000,
  });
  return (
    <section
      className={`${SURFACE} flex flex-wrap items-center gap-3 p-4`}
      aria-label="Reconciliation run"
    >
      <button
        className={BUTTON_SECONDARY}
        disabled={
          start.isPending || Boolean(run.data && !["SUCCEEDED", "DEAD"].includes(run.data.status))
        }
        onClick={() => start.mutate()}
      >
        Reconcile current evidence
      </button>
      {run.data && (
        <p role="status" className="text-sm">
          {run.data.status === "SUCCEEDED"
            ? run.data.result?.status === "complete"
              ? "Reconciliation complete. The queue reflects current source evidence."
              : "Reconciliation is blocked by current access or release gates."
            : run.data.status === "DEAD"
              ? "Reconciliation failed. Ask your administrator to inspect the job."
              : "Reconciliation queued or running…"}
        </p>
      )}
      {(start.isError || run.isError) && (
        <p role="alert" className="text-sm">
          The reconciliation run could not be loaded. Try again.
        </p>
      )}
    </section>
  );
}
