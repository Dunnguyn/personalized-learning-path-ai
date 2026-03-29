import { apiClient } from '../utils/apiClient';
import type {
  AdaptiveNextAction,
  AdaptiveRecommendationPayload,
  LearnerStateSnapshot,
} from '../types/adaptive';

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const normalizeNextAction = (value: unknown): AdaptiveNextAction => {
  const record = asRecord(value);
  return {
    user_id: asString(record.user_id),
    next_best_action: asString(record.next_best_action, 'continue_resource') as AdaptiveNextAction['next_best_action'],
    reason: asString(record.reason),
    priority: asString(record.priority, 'medium') as AdaptiveNextAction['priority'],
    recommended_mode: asString(
      record.recommended_mode,
      'continue_learning',
    ) as AdaptiveNextAction['recommended_mode'],
    target_concepts: Array.isArray(record.target_concepts)
      ? record.target_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    lesson_id: typeof record.lesson_id === 'string' ? record.lesson_id : null,
    resource_id: typeof record.resource_id === 'string' ? record.resource_id : null,
    estimated_total_time:
      typeof record.estimated_total_time === 'number' ? record.estimated_total_time : null,
  };
};

const normalizeAdaptiveRecommendation = (value: unknown): AdaptiveRecommendationPayload => {
  const record = asRecord(value);
  return {
    user_id: asString(record.user_id),
    action: asString(record.action, 'continue_resource') as AdaptiveRecommendationPayload['action'],
    recommendation_type: asString(
      record.recommendation_type,
      'resource',
    ) as AdaptiveRecommendationPayload['recommendation_type'],
    recommendation_mode:
      typeof record.recommendation_mode === 'string'
        ? (record.recommendation_mode as AdaptiveRecommendationPayload['recommendation_mode'])
        : null,
    items: Array.isArray(record.items)
      ? record.items.map((item) => asRecord(item))
      : [],
    reason: asString(record.reason),
    target_concepts: Array.isArray(record.target_concepts)
      ? record.target_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    estimated_total_time: asNumber(record.estimated_total_time),
    lesson_id: typeof record.lesson_id === 'string' ? record.lesson_id : null,
    resource_id: typeof record.resource_id === 'string' ? record.resource_id : null,
  };
};

const normalizeLearnerStateSnapshot = (value: unknown): LearnerStateSnapshot => {
  const record = asRecord(value);
  const masteryByConcept = asRecord(record.mastery_by_concept);
  const confidenceByConcept = asRecord(record.confidence_by_concept);
  return {
    user_id: asString(record.user_id),
    snapshot_time: asString(record.snapshot_time, new Date().toISOString()),
    mastery_by_concept: Object.fromEntries(
      Object.entries(masteryByConcept).map(([key, item]) => [key, asNumber(item)]),
    ),
    confidence_by_concept: Object.fromEntries(
      Object.entries(confidenceByConcept).map(([key, item]) => [key, asNumber(item)]),
    ),
    recent_active_days: asNumber(record.recent_active_days),
    avg_session_duration: asNumber(record.avg_session_duration),
    unfinished_resources: asNumber(record.unfinished_resources),
    quiz_fail_streak: asNumber(record.quiz_fail_streak),
    retry_count: asNumber(record.retry_count),
    learning_velocity: asNumber(record.learning_velocity),
    preferred_time_window: asString(record.preferred_time_window, 'evening'),
    current_focus_concepts: Array.isArray(record.current_focus_concepts)
      ? record.current_focus_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    frustration_score: asNumber(record.frustration_score),
    recovery_need_flag: Boolean(record.recovery_need_flag),
    risk_level: asString(record.risk_level, 'low') as LearnerStateSnapshot['risk_level'],
    last_event_type: typeof record.last_event_type === 'string' ? record.last_event_type : null,
    last_recommended_action:
      typeof record.last_recommended_action === 'string' ? record.last_recommended_action : null,
  };
};

export const adaptiveService = {
  async trackEvent(payload: {
    event_type: string;
    resource_id?: string;
    lesson_id?: string;
    path_id?: string;
    concept_ids?: string[];
    metadata?: Record<string, unknown>;
  }) {
    return apiClient.post('/adaptive/events', payload);
  },

  async getNextBestAction(params?: {
    user_id?: string;
    lesson_id?: string;
  }): Promise<AdaptiveNextAction> {
    const query = new URLSearchParams();
    if (params?.user_id) {
      query.set('user_id', params.user_id);
    }
    if (params?.lesson_id) {
      query.set('lesson_id', params.lesson_id);
    }
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return normalizeNextAction(await apiClient.get(`/adaptive/next-action${suffix}`));
  },

  async getAdaptiveRecommendation(params?: {
    user_id?: string;
    lesson_id?: string;
    goal?: string;
    level?: string;
  }): Promise<AdaptiveRecommendationPayload> {
    const query = new URLSearchParams();
    if (params?.user_id) {
      query.set('user_id', params.user_id);
    }
    if (params?.lesson_id) {
      query.set('lesson_id', params.lesson_id);
    }
    if (params?.goal) {
      query.set('goal', params.goal);
    }
    if (params?.level) {
      query.set('level', params.level);
    }
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return normalizeAdaptiveRecommendation(
      await apiClient.get(`/adaptive/recommendation${suffix}`),
    );
  },

  async getLearnerStateSnapshot(params?: { user_id?: string }): Promise<LearnerStateSnapshot> {
    const suffix = params?.user_id ? `?user_id=${encodeURIComponent(params.user_id)}` : '';
    return normalizeLearnerStateSnapshot(await apiClient.get(`/adaptive/learner-state${suffix}`));
  },

  async recomputeLearnerState(user_id?: string) {
    return apiClient.post('/adaptive/recompute', user_id ? { user_id } : {});
  },
};
