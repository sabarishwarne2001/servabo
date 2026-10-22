/** Zoho Books "Connect" and Tally Prime guided setup (Final session 1, 3C). */
import apiClient from "@/services/api/client";

export type ZohoState = "CONNECTED" | "CHOOSE_ORGANIZATION" | "RECONNECT" | "DISCONNECTED";

export interface ZohoConnection {
  readonly target_id: string;
  readonly name: string;
  readonly status: string;
  readonly state: ZohoState;
  readonly data_centre: string | null;
  readonly data_centre_label: string | null;
  readonly organization_id: string | null;
  readonly organization_name: string | null;
}

export interface ZohoOverview {
  readonly configured: boolean;
  readonly default_data_centre: string;
  readonly data_centres: readonly { readonly key: string; readonly label: string }[];
  readonly connections: readonly ZohoConnection[];
}

export interface ZohoOrganization {
  readonly organization_id: string;
  readonly name: string;
  readonly country: string | null;
}

export interface TallySetup {
  readonly company: string;
  readonly name?: string;
  readonly purchases?: string;
  readonly cgst?: string;
  readonly sgst?: string;
  readonly igst?: string;
  readonly tax?: string;
}

const ws = (workspaceId: string): string => `/workspaces/${encodeURIComponent(workspaceId)}`;

export const erpConnectKeys = {
  zoho: (workspaceId: string) => ["erp", workspaceId, "zoho"] as const,
  organizations: (workspaceId: string, targetId: string) => ["erp", workspaceId, "zoho", targetId, "organizations"] as const,
};

export const getZoho = async (workspaceId: string): Promise<ZohoOverview> =>
  (await apiClient.get<ZohoOverview>(`${ws(workspaceId)}/erp/zoho`)).data;

export const connectZoho = async (workspaceId: string, dataCentre: string, targetId?: string): Promise<{ authorize_url: string }> =>
  (await apiClient.post<{ authorize_url: string }>(`${ws(workspaceId)}/erp/zoho/connect`, {
    data_centre: dataCentre,
    ...(targetId ? { target_id: targetId } : {}),
  })).data;

export const listZohoOrganizations = async (workspaceId: string, targetId: string): Promise<readonly ZohoOrganization[]> =>
  (await apiClient.get<{ items: ZohoOrganization[] }>(`${ws(workspaceId)}/erp/targets/${encodeURIComponent(targetId)}/zoho/organizations`)).data.items;

export const chooseZohoOrganization = async (workspaceId: string, targetId: string, organizationId: string): Promise<ZohoConnection> =>
  (await apiClient.post<ZohoConnection>(`${ws(workspaceId)}/erp/targets/${encodeURIComponent(targetId)}/zoho/organization`, {
    organization_id: organizationId,
  })).data;

export const checkZoho = async (workspaceId: string, targetId: string): Promise<ZohoConnection> =>
  (await apiClient.post<ZohoConnection>(`${ws(workspaceId)}/erp/targets/${encodeURIComponent(targetId)}/zoho/check`)).data;

export const disconnectZoho = async (workspaceId: string, targetId: string): Promise<{ revoked_at_zoho: boolean }> =>
  (await apiClient.post<{ revoked_at_zoho: boolean }>(`${ws(workspaceId)}/erp/targets/${encodeURIComponent(targetId)}/zoho/disconnect`)).data;

export const setUpTally = async (workspaceId: string, body: TallySetup): Promise<{ target_id: string; name: string }> =>
  (await apiClient.post<{ target_id: string; name: string }>(`${ws(workspaceId)}/erp/tally/setup`, body)).data;
