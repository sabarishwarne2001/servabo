import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye } from "lucide-react";
import PageHeader from "@/components/ui/PageHeader";
import { BUTTON_SECONDARY, SURFACE } from "@/components/ui/primitives";
import { useResolvedOrganization } from "@/routes/OrganizationGuard";
import { organizationBillingPath } from "@/routes/tenantPaths";
import { useGrantedCapabilities } from "@/hooks/useGrantedCapabilities";
import { useUpgradePrompt } from "@/hooks/useUpgradePrompt";
import { CAPABILITY } from "@/constants/capabilities";
import { apiClient } from "@/services/api/client";
import type { TrinetraAccess } from "@/services/api/trinetra";
import AccessNotice from "./AccessNotice";
import { rupees } from "./format";

interface Figures {
  total: number;
  unresolved: number;
  expected_micros: string;
  posted_micros: string;
  gap_micros: string;
}
interface WorkspaceFigure extends Figures {
  workspace_id: string;
  name: string;
  as_of: string | null;
}
interface EntityFigure extends Figures {
  entity_id: string;
  name: string;
  workspace_ids: string[];
}
interface OrganizationSummary {
  workspaces: WorkspaceFigure[];
  entities: EntityFigure[];
  totals: Figures | null;
  scope: string;
}

const FigureList = ({ figures }: { figures: Figures }) => (
  <dl className="grid gap-2 text-sm sm:grid-cols-2">
    <div>
      <dt className="text-muted-foreground">Cases</dt>
      <dd>
        {figures.unresolved} unresolved of {figures.total}
      </dd>
    </div>
    <div>
      <dt className="text-muted-foreground">Supported expected withholding</dt>
      <dd className="tabular-nums">{rupees(figures.expected_micros)}</dd>
    </div>
    <div>
      <dt className="text-muted-foreground">Allocated uploaded postings</dt>
      <dd className="tabular-nums">{rupees(figures.posted_micros)}</dd>
    </div>
    <div>
      <dt className="text-muted-foreground">Possible gap</dt>
      <dd className="tabular-nums">{rupees(figures.gap_micros)}</dd>
    </div>
  </dl>
);

/** TDS credit across the workspaces you may read (Enterprise): each legal entity counted once, then each workspace. */
export default function OrganizationTrinetra() {
  const { organization, organizationId, organizationRole } = useResolvedOrganization();
  const upgrade = useUpgradePrompt(
    organizationId,
    organization.organization_slug,
    organizationRole,
  );
  const capabilities = useGrantedCapabilities(organizationId);
  const [offset, setOffset] = useState(0);
  const base = `/organizations/${encodeURIComponent(organizationId)}/trinetra`;
  const access = useQuery({
    queryKey: ["trinetra", organizationId, "organization-access"],
    queryFn: async () => (await apiClient.get<TrinetraAccess>(`${base}/access`)).data,
  });
  const live = Boolean(access.data?.live_enabled && access.data.entitled);
  const enterprise = capabilities.granted.has(CAPABILITY.trinetraAllWorkspaces);
  const ready = live && enterprise;
  const result = useQuery({
    queryKey: ["trinetra", organizationId, "organization-summary", offset],
    enabled: ready,
    queryFn: async () =>
      (
        await apiClient.get<OrganizationSummary>(`${base}/summary`, {
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
        description="Review evidence exposure across the workspaces you may access. Each legal entity is counted once."
      />
      {access.data && (
        <AccessNotice
          access={access.data}
          billingPath={organizationBillingPath(organization.organization_slug)}
        />
      )}
      {live && !enterprise && !capabilities.isLoading && (
        <div className={`${SURFACE} space-y-3 p-5`} data-testid="trinetra-org-upgrade">
          <p>
            Reporting across workspaces comes with Enterprise. Each workspace has its own TDS credit
            page with its cases, statements and closures.
          </p>
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
        </div>
      )}
      {access.isPending && <p role="status">Checking access…</p>}
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
          {result.data.totals && (
            <section
              className={`${SURFACE} space-y-3 p-5`}
              aria-labelledby="org-totals"
              data-testid="trinetra-org-totals"
            >
              <h2 id="org-totals" className="font-semibold">
                All legal entities
              </h2>
              <FigureList figures={result.data.totals} />
            </section>
          )}
          {result.data.entities.length > 0 && (
            <section aria-labelledby="org-entities" data-testid="trinetra-org-entities">
              <h2 id="org-entities" className="mb-3 font-semibold">
                By legal entity
              </h2>
              <ul className="grid gap-4 md:grid-cols-2">
                {result.data.entities.map((entity) => (
                  <li key={entity.entity_id} className={`${SURFACE} space-y-2 p-5`}>
                    <h3 className="font-semibold">{entity.name}</h3>
                    <p className="text-xs text-muted-foreground">
                      In {entity.workspace_ids.length}{" "}
                      {entity.workspace_ids.length === 1 ? "workspace" : "workspaces"}
                    </p>
                    <FigureList figures={entity} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section aria-labelledby="org-workspaces">
            <h2 id="org-workspaces" className="mb-3 font-semibold">
              By workspace
            </h2>
            <ul className="grid gap-4 md:grid-cols-2">
              {result.data.workspaces.map((w) => (
                <li key={w.workspace_id} className={`${SURFACE} space-y-2 p-5`}>
                  <h3 className="font-semibold">{w.name}</h3>
                  <FigureList figures={w} />
                  <p className="text-xs text-muted-foreground">
                    {w.as_of ? `Evidence as of ${w.as_of}` : "No current statement evidence"}
                  </p>
                </li>
              ))}
            </ul>
          </section>
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
