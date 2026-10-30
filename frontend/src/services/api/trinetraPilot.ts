/**
 * The operator's TRINETRA pilot console (platform superadmins only: the server answers 404 to anyone else).
 * The same three endpoints `scripts/trinetra_pilot.py` and the browser specs use.
 */
import { apiClient } from "@/services/api/client";
import type { RevOpsOrganization } from "@/types/revops";

export interface TrinetraPilotEntry {
  organization_id: string;
  name: string | null;
  /** Tells two organizations of the same name apart. */
  slug?: string | null;
  /** False when the plan has no TRINETRA (Starter): enrolled, but still on the examples. */
  entitled?: boolean;
  reason: string;
  enrolled_by: string | null;
  enrolled_at: string;
}

export interface TrinetraPilot {
  mode: "off" | "pilot" | "on" | string;
  items: TrinetraPilotEntry[];
}

const BASE = "/admin/trinetra/pilot";
const seg = (value: string): string => encodeURIComponent(value);

export const trinetraPilotKeys = {
  all: () => ["trinetra-pilot"] as const,
  organizations: (query: string) => ["trinetra-pilot", "organizations", query] as const,
};

export const getTrinetraPilot = async (): Promise<TrinetraPilot> => (await apiClient.get<TrinetraPilot>(BASE)).data;

/** Organizations by name or slug (the operator's existing picker, `/admin/revops/organizations`). */
export const searchOrganizations = async (query: string): Promise<readonly RevOpsOrganization[]> =>
  (await apiClient.get<RevOpsOrganization[]>("/admin/revops/organizations", { params: query ? { q: query } : {} })).data;

export const enrolOrganization = async (organizationId: string, reason: string): Promise<TrinetraPilotEntry> =>
  (await apiClient.put<TrinetraPilotEntry>(`${BASE}/${seg(organizationId)}`, { reason })).data;

export const withdrawOrganization = async (
  organizationId: string,
  reason: string,
): Promise<{ organization_id: string; withdrawn: boolean }> =>
  (await apiClient.post<{ organization_id: string; withdrawn: boolean }>(`${BASE}/${seg(organizationId)}/withdraw`, { reason })).data;
