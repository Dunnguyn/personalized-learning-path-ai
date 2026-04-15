import { apiClient } from '../utils/apiClient';
import type {
  InterventionLogItem,
  InterventionLogsResponse,
  PathRefinementAction,
  PathRefinementActionsResponse,
  RefinementDiffOp,
  RefinementEffect,
  RefinementPatch,
  RefinementReason,
  RefinementRecommendation,
} from '../types/pathRefinement';

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const asString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value : null;

const normalizeReason = (value: unknown): RefinementReason => {
  const record = asRecord(value);
  return {
    intervention_type: asString(record.intervention_type) || 'unknown',
    trigger_reason: asString(record.trigger_reason),
    impact_scope: asString(record.impact_scope),
  };
};

const normalizeEffect = (value: unknown): RefinementEffect => {
  const record = asRecord(value);
  return {
    type: asString(record.type) || 'change',
    field: asString(record.field),
    label: asString(record.label) || 'Đã điều chỉnh lộ trình.',
    value: record.value,
  };
};

const normalizeRecommendation = (value: unknown): RefinementRecommendation => {
  const record = asRecord(value);
  return {
    type: asString(record.type) || 'continue',
    label: asString(record.label) || 'Tiếp tục học theo gợi ý mới.',
  };
};

const normalizeDiffOp = (value: unknown): RefinementDiffOp => {
  const record = asRecord(value);
  return {
    op: asString(record.op) || undefined,
    lesson_id: asString(record.lesson_id) || '',
    applied_interventions: Array.isArray(record.applied_interventions)
      ? record.applied_interventions.map((item) => String(item))
      : [],
    reasons: Array.isArray(record.reasons) ? record.reasons.map(normalizeReason) : [],
    effects: Array.isArray(record.effects) ? record.effects.map(normalizeEffect) : [],
    recommendations: Array.isArray(record.recommendations)
      ? record.recommendations.map(normalizeRecommendation)
      : [],
    before: asRecord(record.before),
    after: asRecord(record.after),
  };
};

const normalizePatch = (value: unknown): RefinementPatch | null => {
  const record = asRecord(value);
  if (!Object.keys(record).length) {
    return null;
  }
  return {
    ops: Array.isArray(record.ops) ? record.ops.map(normalizeDiffOp) : [],
    affected_lesson_ids: Array.isArray(record.affected_lesson_ids)
      ? record.affected_lesson_ids.map((item) => String(item))
      : [],
    summary:
      record.summary && typeof record.summary === 'object' && !Array.isArray(record.summary)
        ? {
            target_lesson_id: asString(asRecord(record.summary).target_lesson_id),
            intervention_count:
              typeof asRecord(record.summary).intervention_count === 'number'
                ? (asRecord(record.summary).intervention_count as number)
                : undefined,
            intervention_types: Array.isArray(asRecord(record.summary).intervention_types)
              ? (asRecord(record.summary).intervention_types as unknown[]).map((item) => String(item))
              : [],
          }
        : null,
  };
};

const normalizeAction = (value: unknown): PathRefinementAction => {
  const record = asRecord(value);
  return {
    action_id: asString(record.action_id) || '',
    user_id: asString(record.user_id) || '',
    path_id: asString(record.path_id) || '',
    lesson_id: asString(record.lesson_id) || '',
    concept_id: asString(record.concept_id),
    intervention_type: Array.isArray(record.intervention_type)
      ? record.intervention_type.map((item) => String(item))
      : [],
    trigger_reason: asString(record.trigger_reason),
    old_path_snapshot: asRecord(record.old_path_snapshot),
    new_path_patch: normalizePatch(record.new_path_patch),
    summary:
      record.summary && typeof record.summary === 'object' && !Array.isArray(record.summary)
        ? {
            headline: asString(asRecord(record.summary).headline),
            intervention_count:
              typeof asRecord(record.summary).intervention_count === 'number'
                ? (asRecord(record.summary).intervention_count as number)
                : undefined,
            intervention_types: Array.isArray(asRecord(record.summary).intervention_types)
              ? (asRecord(record.summary).intervention_types as unknown[]).map((item) => String(item))
              : [],
          }
        : null,
    outcome_status: asString(record.outcome_status),
    created_at: asString(record.created_at),
  };
};

const normalizeIntervention = (value: unknown): InterventionLogItem => {
  const record = asRecord(value);
  return {
    action_id: asString(record.action_id) || '',
    user_id: asString(record.user_id) || '',
    path_id: asString(record.path_id) || '',
    lesson_id: asString(record.lesson_id) || '',
    intervention_type: asString(record.intervention_type),
    trigger_reason: asString(record.trigger_reason),
    impact_scope: asString(record.impact_scope),
    action:
      record.action && typeof record.action === 'object' && !Array.isArray(record.action)
        ? asRecord(record.action)
        : null,
    created_at: asString(record.created_at),
  };
};

export const pathRefinementService = {
  async getRefinementActions(params: {
    user_id: string;
    path_id?: string;
    lesson_id?: string;
  }): Promise<PathRefinementActionsResponse> {
    const query = new URLSearchParams();
    if (params.path_id) {
      query.set('path_id', params.path_id);
    }
    if (params.lesson_id) {
      query.set('lesson_id', params.lesson_id);
    }
    const suffix = query.toString() ? `?${query.toString()}` : '';
    const response = asRecord(
      await apiClient.get(`/path/refinement/${encodeURIComponent(params.user_id)}${suffix}`),
    );
    return {
      user_id: asString(response.user_id) || params.user_id,
      total: typeof response.total === 'number' ? response.total : 0,
      items: Array.isArray(response.items) ? response.items.map(normalizeAction) : [],
    };
  },

  async getInterventions(params: {
    user_id: string;
    path_id?: string;
    lesson_id?: string;
  }): Promise<InterventionLogsResponse> {
    const query = new URLSearchParams();
    if (params.path_id) {
      query.set('path_id', params.path_id);
    }
    if (params.lesson_id) {
      query.set('lesson_id', params.lesson_id);
    }
    const suffix = query.toString() ? `?${query.toString()}` : '';
    const response = asRecord(
      await apiClient.get(`/interventions/${encodeURIComponent(params.user_id)}${suffix}`),
    );
    return {
      user_id: asString(response.user_id) || params.user_id,
      total: typeof response.total === 'number' ? response.total : 0,
      items: Array.isArray(response.items) ? response.items.map(normalizeIntervention) : [],
    };
  },
};
