import apiClient from "@/services/api/client";
import { AUTOMATION_ENDPOINTS } from "@/services/api/endpoints";
import type {
  AutomationRule,
  AutomationLog,
  AutomationRuleCreateRequest,
  AutomationRuleUpdateRequest,
  AutomationRuleTestResponse,
} from "@/types/automation";
import type { FlowCatalog } from "@/types/automationFlow";
import type {
  AutomationPauseState,
  DocumentExplanation,
  DraftTestResult,
  HealthReport,
  PreviewResult,
  RecipeList,
  RuleVersionPage,
} from "@/types/automationVolume";

export const createAutomationRule = async (
  workspaceId: string,
  data: AutomationRuleCreateRequest,
): Promise<AutomationRule> => {
  const response = await apiClient.post<AutomationRule>(
    AUTOMATION_ENDPOINTS.rules(workspaceId),
    data,
    {
      headers: {
        "Accept": "application/json",
      },
    },
  );
  return response.data;
};

export const getAutomationRules = async (
  workspaceId: string,
): Promise<readonly AutomationRule[]> => {
  const response = await apiClient.get<readonly AutomationRule[]>(
    AUTOMATION_ENDPOINTS.rules(workspaceId),
    {
      headers: {
        "Accept": "application/json",
      },
    },
  );
  return response.data;
};

export const getAutomationRuleDetails = async (
  workspaceId: string,
  ruleId: string,
): Promise<AutomationRule> => {
  const response = await apiClient.get<AutomationRule>(
    AUTOMATION_ENDPOINTS.rule(workspaceId, ruleId),
    {
      headers: {
        "Accept": "application/json",
      },
    },
  );
  return response.data;
};

export const updateAutomationRule = async (
  workspaceId: string,
  ruleId: string,
  data: AutomationRuleUpdateRequest,
): Promise<AutomationRule> => {
  const response = await apiClient.patch<AutomationRule>(
    AUTOMATION_ENDPOINTS.rule(workspaceId, ruleId),
    data,
    {
      headers: {
        "Accept": "application/json",
      },
    },
  );
  return response.data;
};

export const deleteAutomationRule = async (
  workspaceId: string,
  ruleId: string,
): Promise<void> => {
  await apiClient.delete(AUTOMATION_ENDPOINTS.rule(workspaceId, ruleId), {
    headers: {
      "Accept": "application/json",
    },
  });
};

export const getAutomationLogs = async (
  workspaceId: string,
): Promise<readonly AutomationLog[]> => {
  const response = await apiClient.get<readonly AutomationLog[]>(
    AUTOMATION_ENDPOINTS.logs(workspaceId),
    {
      headers: {
        "Accept": "application/json",
      },
    },
  );
  return response.data;
};

export const testAutomationRule = async (
  workspaceId: string,
  ruleId: string,
  workItemId: string,
): Promise<AutomationRuleTestResponse> => {
  const response = await apiClient.post<AutomationRuleTestResponse>(
    `${AUTOMATION_ENDPOINTS.rule(workspaceId, ruleId)}/test`,
    { work_item_id: workItemId },
    {
      headers: {
        "Accept": "application/json",
      },
    },
  );
  return response.data;
};

/** ARCH37-S2:catalog-api. Every trigger, action and resource the builder may offer. */
export const getAutomationCatalog = async (
  workspaceId: string,
): Promise<FlowCatalog> => {
  const response = await apiClient.get<FlowCatalog>(
    AUTOMATION_ENDPOINTS.catalog(workspaceId),
    { headers: { Accept: "application/json" } },
  );
  return response.data;
};

export const getPauseState = async (workspaceId: string): Promise<AutomationPauseState> =>
  (await apiClient.get<AutomationPauseState>(AUTOMATION_ENDPOINTS.pause(workspaceId))).data;

export const setPaused = async (workspaceId: string, paused: boolean): Promise<AutomationPauseState> =>
  (await apiClient.put<AutomationPauseState>(AUTOMATION_ENDPOINTS.pause(workspaceId), { paused })).data;

export const getRuleVersions = async (workspaceId: string, ruleId: string): Promise<RuleVersionPage> =>
  (await apiClient.get<RuleVersionPage>(AUTOMATION_ENDPOINTS.versions(workspaceId, ruleId))).data;

export const restoreRuleVersion = async (
  workspaceId: string,
  ruleId: string,
  version: number,
): Promise<AutomationRule> =>
  (await apiClient.post<AutomationRule>(AUTOMATION_ENDPOINTS.restore(workspaceId, ruleId, version), {})).data;

/** What a rule that is not saved yet would have done on the last 30 days. Read-only on the server. */
export const previewDraft = async (
  workspaceId: string,
  data: AutomationRuleCreateRequest,
): Promise<PreviewResult> =>
  (await apiClient.post<PreviewResult>(AUTOMATION_ENDPOINTS.previewDraft(workspaceId), data)).data;

export const previewRule = async (workspaceId: string, ruleId: string): Promise<PreviewResult> =>
  (await apiClient.post<PreviewResult>(AUTOMATION_ENDPOINTS.previewRule(workspaceId, ruleId), {})).data;

export const runRuleByHand = async (
  workspaceId: string,
  ruleId: string,
  workItemId: string,
): Promise<{ readonly queued: boolean; readonly event_id: string }> =>
  (await apiClient.post<{ queued: boolean; event_id: string }>(
    AUTOMATION_ENDPOINTS.runByHand(workspaceId, ruleId),
    { work_item_id: workItemId },
  )).data;

export const explainDocument = async (workspaceId: string, workItemId: string): Promise<DocumentExplanation> =>
  (await apiClient.get<DocumentExplanation>(AUTOMATION_ENDPOINTS.explain(workspaceId, workItemId))).data;

export const getRecipes = async (workspaceId: string): Promise<RecipeList> =>
  (await apiClient.get<RecipeList>(AUTOMATION_ENDPOINTS.recipes(workspaceId))).data;

/** Which way a rule that may not be saved yet goes for one document, with each step's message filled in. Read-only. */
export const testDraft = async (
  workspaceId: string,
  data: AutomationRuleCreateRequest,
  workItemId: string,
): Promise<DraftTestResult> =>
  (await apiClient.post<DraftTestResult>(AUTOMATION_ENDPOINTS.testDraft(workspaceId), { ...data, work_item_id: workItemId })).data;

export const getHealth = async (workspaceId: string): Promise<HealthReport> =>
  (await apiClient.get<HealthReport>(AUTOMATION_ENDPOINTS.health(workspaceId))).data;

export const automationApi = {
  testDraft,
  getHealth,
  getPauseState,
  setPaused,
  getRuleVersions,
  restoreRuleVersion,
  previewDraft,
  previewRule,
  runRuleByHand,
  explainDocument,
  getRecipes,
  createAutomationRule,
  getAutomationRules,
  getAutomationRuleDetails,
  updateAutomationRule,
  deleteAutomationRule,
  getAutomationLogs,
  testAutomationRule,
  getAutomationCatalog,
};

export default automationApi;
