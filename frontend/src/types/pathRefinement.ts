export interface RefinementReason {
  intervention_type: string;
  trigger_reason?: string | null;
  impact_scope?: string | null;
}

export interface RefinementEffect {
  type: string;
  field?: string | null;
  label: string;
  value?: unknown;
}

export interface RefinementRecommendation {
  type: string;
  label: string;
}

export interface RefinementDiffOp {
  op?: string;
  lesson_id: string;
  applied_interventions: string[];
  reasons: RefinementReason[];
  effects: RefinementEffect[];
  recommendations: RefinementRecommendation[];
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
}

export interface RefinementPatchSummary {
  target_lesson_id?: string | null;
  intervention_count?: number;
  intervention_types?: string[];
}

export interface RefinementPatch {
  ops: RefinementDiffOp[];
  affected_lesson_ids?: string[];
  summary?: RefinementPatchSummary | null;
}

export interface PathRefinementAction {
  action_id: string;
  user_id: string;
  path_id: string;
  lesson_id: string;
  concept_id?: string | null;
  intervention_type: string[];
  trigger_reason?: string | null;
  old_path_snapshot?: Record<string, unknown>;
  new_path_patch?: RefinementPatch | null;
  summary?: {
    headline?: string | null;
    intervention_count?: number;
    intervention_types?: string[];
  } | null;
  outcome_status?: string | null;
  created_at?: string | null;
}

export interface PathRefinementActionsResponse {
  user_id: string;
  total: number;
  items: PathRefinementAction[];
}

export interface InterventionLogItem {
  action_id: string;
  user_id: string;
  path_id: string;
  lesson_id: string;
  intervention_type?: string | null;
  trigger_reason?: string | null;
  impact_scope?: string | null;
  action?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface InterventionLogsResponse {
  user_id: string;
  total: number;
  items: InterventionLogItem[];
}
