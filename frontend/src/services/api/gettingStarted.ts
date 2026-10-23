/** The first-run checklist (Final session 1, 2C). Every tick is computed by the server from real data. */
import apiClient from "@/services/api/client";

export type GettingStartedKey = "documents" | "read" | "gst" | "helm" | "recipe" | "invite";

export interface GettingStartedStep {
  readonly key: GettingStartedKey;
  readonly title: string;
  readonly done: boolean;
  /** Set when the step's feature is a preview on this plan: what the add-on or plan unlocks. */
  readonly note: string | null;
}

export interface GettingStartedMoney {
  readonly text: string;
  readonly amount_text: string;
  readonly period: string;
}

export interface GettingStartedView {
  readonly steps: readonly GettingStartedStep[];
  readonly done: number;
  readonly total: number;
  readonly money: GettingStartedMoney | null;
}

export const gettingStartedKeys = {
  all: (workspaceId: string) => ["ws", workspaceId, "getting-started"] as const,
};

export const getGettingStarted = async (workspaceId: string): Promise<GettingStartedView> =>
  (await apiClient.get<GettingStartedView>(`/workspaces/${encodeURIComponent(workspaceId)}/getting-started`)).data;
