/**
 * Session J — the shapes of the automation endpoints added with "safe at volume" and the recipe library.
 */

import type { AutomationRuleCreateRequest, ConditionTrace } from "@/types/automation";

export interface AutomationPauseState {
  readonly paused: boolean;
  readonly paused_at: string | null;
  readonly paused_by_user_id: string | null;
}

export interface RuleVersion {
  readonly id: string;
  readonly version: number;
  readonly note: string;
  readonly created_at: string;
  readonly created_by_user_id: string | null;
  readonly created_by_name: string | null;
  readonly restored_from_version: number | null;
  /** The plain-words diff against the version before: "Added condition: Total amount is greater than 1000000 INR". */
  readonly changes: readonly string[];
}

export interface RuleVersionPage {
  readonly total: number;
  readonly items: readonly RuleVersion[];
}

export interface PreviewResult {
  readonly days: number;
  readonly events_examined: number;
  readonly truncated: boolean;
  readonly would_run: number;
  readonly average_per_day: number;
  readonly peak_per_day: number;
  readonly per_day: Readonly<Record<string, number>>;
  readonly actions: readonly { readonly action_type: string; readonly label: string; readonly times: number }[];
  readonly messages_per_day_peak: number;
  readonly would_be_throttled: number;
  readonly warnings: readonly string[];
  readonly samples: readonly {
    readonly occurred_at: string;
    readonly work_item_id: string | null;
    readonly filename: string | null;
    readonly trigger: string;
  }[];
  readonly no_history: readonly string[];
}

export type ExplainOutcome =
  | "ran"
  | "held_back"
  | "failed"
  | "off"
  | "not_triggered"
  | "conditions_not_met"
  | "no_actions";

export interface RuleExplanation {
  readonly rule_id: string;
  readonly rule_name: string;
  readonly is_active: boolean;
  readonly triggers: readonly string[];
  readonly trigger_fired: boolean;
  readonly conditions: readonly ConditionTrace[];
  readonly conditions_met: boolean | null;
  readonly last_run: {
    readonly execution_id: string;
    readonly status: string;
    readonly at: string;
    readonly actions_executed: number;
    readonly reason: string | null;
  } | null;
  readonly verdict: string;
  readonly outcome: ExplainOutcome;
}

export interface DocumentExplanation {
  readonly work_item_id: string;
  readonly rules: readonly RuleExplanation[];
}

export interface RecipeFillIn {
  /** Where the answer goes in the rule: `actions.0.config.endpoint_id`. */
  readonly path: string;
  readonly kind: "chat_endpoint" | "member_email" | "email";
  readonly label: string;
  readonly hint: string;
}

export interface Recipe {
  readonly id: string;
  readonly title: string;
  readonly summary: string;
  readonly category: string;
  readonly icon: string;
  readonly fill_ins: readonly RecipeFillIn[];
  readonly rule: AutomationRuleCreateRequest;
  readonly available: boolean;
  readonly unavailable_reason: string | null;
  readonly trigger_labels: readonly string[];
}

export interface RecipeList {
  readonly categories: readonly string[];
  readonly recipes: readonly Recipe[];
}
