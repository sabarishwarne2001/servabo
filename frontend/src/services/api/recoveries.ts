/**
 * Final session 2A (N-191) — Recoveries: money issues from Found to Being fixed to Verified.
 *
 * The server holds every rule: closure only on evidence, "Not money" never counted, Found and "Recovered, verified"
 * never added. A plan without Recoveries gets `included: false` and a preview of counts and what was found.
 */
import apiClient from "@/services/api/client";
import { RECOVERIES_ENDPOINTS } from "@/services/api/endpoints";
import type { components } from "@/types/api.generated";

export type RecoveriesView = components["schemas"]["RecoveriesOut"];
export type RecoveryIssue = components["schemas"]["RecoveryIssueOut"];
export type RecoveryState = RecoveryIssue["state"];
export type RecoveryAmount = components["schemas"]["RecoveryAmount"];
export type RecoveryCheck = components["schemas"]["RecoveryCheckOut"];

/** The server refuses a shorter "Not money" reason (422). */
export const MIN_REASON = 10;

export const listRecoveries = async (workspaceId: string): Promise<RecoveriesView> =>
  (await apiClient.get<RecoveriesView>(RECOVERIES_ENDPOINTS.list(workspaceId))).data;

export const getRecovery = async (workspaceId: string, issueId: string): Promise<RecoveryIssue> =>
  (await apiClient.get<RecoveryIssue>(RECOVERIES_ENDPOINTS.detail(workspaceId, issueId))).data;

export const checkRecoveries = async (workspaceId: string): Promise<RecoveryCheck> =>
  (await apiClient.post<RecoveryCheck>(RECOVERIES_ENDPOINTS.check(workspaceId), {})).data;

export const setRecoveryOwner = async (workspaceId: string, issueId: string, ownerUserId: string | null,
  version: number): Promise<RecoveryIssue> =>
  (await apiClient.put<RecoveryIssue>(RECOVERIES_ENDPOINTS.owner(workspaceId, issueId),
    { owner_user_id: ownerUserId, version })).data;

export const setRecoveryDueDate = async (workspaceId: string, issueId: string, dueDate: string | null,
  version: number): Promise<RecoveryIssue> =>
  (await apiClient.put<RecoveryIssue>(RECOVERIES_ENDPOINTS.dueDate(workspaceId, issueId),
    { due_date: dueDate, version })).data;

export const closeRecoveryNotMoney = async (workspaceId: string, issueId: string, reason: string,
  version: number): Promise<RecoveryIssue> =>
  (await apiClient.post<RecoveryIssue>(RECOVERIES_ENDPOINTS.notMoney(workspaceId, issueId), { reason, version })).data;

export const reopenRecovery = async (workspaceId: string, issueId: string, version: number): Promise<RecoveryIssue> =>
  (await apiClient.post<RecoveryIssue>(RECOVERIES_ENDPOINTS.reopen(workspaceId, issueId), { version })).data;
