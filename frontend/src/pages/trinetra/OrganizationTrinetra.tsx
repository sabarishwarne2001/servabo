import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye } from "lucide-react";
import PageHeader from "@/components/ui/PageHeader";
import { BUTTON_SECONDARY, SURFACE } from "@/components/ui/primitives";
import { useResolvedOrganization } from "@/routes/OrganizationGuard";
import { useUpgradePrompt } from "@/hooks/useUpgradePrompt";
import { CAPABILITY } from "@/constants/capabilities";
import { apiClient } from "@/services/api/client";
import { rupees } from "./format";

interface WorkspaceFigure {
  workspace_id: string;
  name: string;
  total: number;
  unresolved: number;
  expected_micros: string;
  posted_micros: string;
  gap_micros: string;
  as_of: string | null;
}
export default function OrganizationTrinetra() {
  const { organization, organizationId, organizationRole } = useResolvedOrganization();
  const upgrade = useUpgradePrompt(
    organizationId,
    organization.organization_slug,
    organizationRole,
  );
  const [offset, setOffset] = useState(0);
  const base = `/organizations/${encodeURIComponent(organizationId)}/trinetra`;
  const access = useQuery({
    queryKey: ["trinetra", organizationId, "organization-access"],
    queryFn: async () =>
      (await apiClient.get<{ live_enabled: boolean; entitled: boolean }>(`${base}/access`)).data,
  });
  const ready = Boolean(access.data?.live_enabled && access.data.entitled);
  const result = useQuery({
    queryKey: ["trinetra", organizationId, "organization-summary", offset],
    enabled: ready,
    queryFn: async () =>
      (
        await apiClient.get<{ workspaces: WorkspaceFigure[]; scope: string }>(`${base}/summary`, {
          params: { offset, limit: 50 },
        })
      ).data,
  });
  return (
    <div className="space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Eye}
        eyebrow="TRINETRA"
        title="Credit assurance across workspaces"
        description="Review evidence exposure across the workspaces you may access. Legal entities remain separate."
      />
      {!ready && (
        <div className={`${SURFACE} space-y-3 p-5`}>
          <p>
            {access.isPending
              ? "Checking access…"
              : "Live organization reporting requires Enterprise and source-validation release approval. Explore synthetic examples from a workspace's TRINETRA page."}
          </p>
          {access.data && !access.data.entitled && (
            <button
              className={BUTTON_SECONDARY}
              onClick={() =>
                upgrade.prompt(
                  CAPABILITY.trinetraAllWorkspaces,
                  "TRINETRA across authorized workspaces",
                )
              }
            >
              View plan availability
            </button>
          )}
        </div>
      )}
      {access.isError && (
        <p role="alert">
          Access could not be loaded.{" "}
          <button className={BUTTON_SECONDARY} onClick={() => void access.refetch()}>
            Try again
          </button>
        </p>
      )}
      {ready && result.isPending && <p role="status">Loading workspace evidence…</p>}
      {result.isError && (
        <p role="alert">
          The report could not be loaded.{" "}
          <button className={BUTTON_SECONDARY} onClick={() => void result.refetch()}>
            Try again
          </button>
        </p>
      )}
      {result.data && (
        <>
          <p className="text-sm text-muted-foreground">{result.data.scope}</p>
          <ul className="grid gap-4 md:grid-cols-2">
            {result.data.workspaces.map((w) => (
              <li key={w.workspace_id} className={`${SURFACE} space-y-2 p-5`}>
                <h2 className="font-semibold">{w.name}</h2>
                <p>
                  {w.unresolved} unresolved of {w.total} cases
                </p>
                <p>Expected: {rupees(w.expected_micros)}</p>
                <p>Allocated uploaded postings: {rupees(w.posted_micros)}</p>
                <p>Possible gap: {rupees(w.gap_micros)}</p>
                <p className="text-xs text-muted-foreground">
                  {w.as_of ? `Evidence as of ${w.as_of}` : "No current statement evidence"}
                </p>
              </li>
            ))}
          </ul>
          {!result.data.workspaces.length && (
            <p>No workspace evidence is available on this page.</p>
          )}
          <div className="flex gap-3">
            <button
              className={BUTTON_SECONDARY}
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous workspaces
            </button>
            <button
              className={BUTTON_SECONDARY}
              disabled={result.data.workspaces.length < 50}
              onClick={() => setOffset(offset + 50)}
            >
              Next workspaces
            </button>
          </div>
        </>
      )}
      {upgrade.dialog}
    </div>
  );
}
