import { apiClient } from '../utils/apiClient';
import type {
  AdaptiveBloomLevel,
  AdaptiveDifficulty,
  AdaptiveExplanationResponse,
  AdaptiveNextAction,
  AdaptiveNextStepResponse,
  AdaptiveQuestionType,
  AdaptiveQuizPlan,
  AdaptiveRetryStrategy,
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

const asBoolean = (value: unknown, fallback = false): boolean =>
  typeof value === 'boolean' ? value : fallback;

const asAdaptiveDifficulty = (value: unknown): AdaptiveDifficulty | null =>
  value === 'intermediate' || value === 'advanced' ? value : value === 'beginner' ? 'beginner' : null;

const asAdaptiveBloomLevels = (value: unknown): AdaptiveBloomLevel[] =>
  Array.isArray(value)
    ? value
        .map((item) => asString(item))
        .filter(
          (item): item is AdaptiveBloomLevel =>
            item === 'remember' ||
            item === 'understand' ||
            item === 'apply' ||
            item === 'analyze' ||
            item === 'evaluate' ||
            item === 'create',
        )
    : [];

const asAdaptiveRetryStrategy = (value: unknown): AdaptiveRetryStrategy | null =>
  value === 'same_question'
    ? 'paraphrase_question'
    : value === 'paraphrase_question' ||
  value === 'simplify_question' ||
  value === 'explain_then_question'
    ? value
    : null;

const asAdaptiveQuestionTypes = (value: unknown): AdaptiveQuestionType[] =>
  Array.isArray(value)
    ? value
        .map((item) => asString(item))
        .filter(
          (item): item is AdaptiveQuestionType =>
            item === 'multiple_choice' || item === 'short_answer' || item === 'true_false',
        )
    : [];

const normalizeAdaptiveQuizPlan = (value: unknown): AdaptiveQuizPlan | null => {
  const record = asRecord(value);
  if (!Object.keys(record).length) {
    return null;
  }
  return {
    lesson_id: typeof record.lesson_id === 'string' ? record.lesson_id : null,
    target_count: asNumber(record.target_count),
    recommended_difficulty: asAdaptiveDifficulty(record.recommended_difficulty),
    recommended_bloom_levels: asAdaptiveBloomLevels(record.recommended_bloom_levels),
    target_chunk_ids: Array.isArray(record.target_chunk_ids)
      ? record.target_chunk_ids.map((item) => asString(item)).filter(Boolean)
      : [],
    target_concepts: Array.isArray(record.target_concepts)
      ? record.target_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    retry_strategy: asAdaptiveRetryStrategy(record.retry_strategy),
    question_types: asAdaptiveQuestionTypes(record.question_types),
    adaptive_explanation:
      typeof record.adaptive_explanation === 'string' ? record.adaptive_explanation : null,
  };
};

const normalizeNextAction = (value: unknown): AdaptiveNextAction => {
  const record = asRecord(value);
  return {
    user_id: asString(record.user_id),
    next_best_action: asString(record.next_best_action, 'review_summary') as AdaptiveNextAction['next_best_action'],
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
    action: asString(record.action, 'review_summary') as AdaptiveRecommendationPayload['action'],
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
    unfinished_resources: asNumber(record.unfinished_resources),
    quiz_fail_streak: asNumber(record.quiz_fail_streak),
    learning_velocity: asNumber(record.learning_velocity),
    current_focus_concepts: Array.isArray(record.current_focus_concepts)
      ? record.current_focus_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    needs_reinforcement: Boolean(record.needs_reinforcement),
    path_id: typeof record.path_id === 'string' ? record.path_id : null,
    current_lesson_id: typeof record.current_lesson_id === 'string' ? record.current_lesson_id : null,
    engagement_score:
      typeof record.engagement_score === 'number' ? record.engagement_score : undefined,
    quiz_accuracy: typeof record.quiz_accuracy === 'number' ? record.quiz_accuracy : undefined,
    completion_rate:
      typeof record.completion_rate === 'number' ? record.completion_rate : undefined,
    avg_session_duration:
      typeof record.avg_session_duration === 'number' ? record.avg_session_duration : undefined,
    retry_count: typeof record.retry_count === 'number' ? record.retry_count : undefined,
    fail_streak: typeof record.fail_streak === 'number' ? record.fail_streak : undefined,
    fatigue_score: typeof record.fatigue_score === 'number' ? record.fatigue_score : undefined,
    risk_level: typeof record.risk_level === 'string' ? record.risk_level : undefined,
    preferred_resource_type:
      typeof record.preferred_resource_type === 'string' ? record.preferred_resource_type : null,
    last_event_type: typeof record.last_event_type === 'string' ? record.last_event_type : null,
    last_recommended_action:
      typeof record.last_recommended_action === 'string' ? record.last_recommended_action : null,
  };
};

const normalizeAdaptiveNextStep = (value: unknown): AdaptiveNextStepResponse => {
  const record = asRecord(value);
  return {
    action: asString(record.action, 'NO_ACTION') as AdaptiveNextStepResponse['action'],
    reason: asString(record.reason),
    target_concepts: Array.isArray(record.target_concepts)
      ? record.target_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    resources: Array.isArray(record.resources) ? record.resources.map((item) => asRecord(item)) : [],
    should_generate_quiz: asBoolean(record.should_generate_quiz),
    should_unlock_next: asBoolean(record.should_unlock_next),
    recommended_difficulty: asAdaptiveDifficulty(record.recommended_difficulty),
    recommended_bloom_levels: asAdaptiveBloomLevels(record.recommended_bloom_levels),
    retry_strategy: asAdaptiveRetryStrategy(record.retry_strategy),
    question_types: asAdaptiveQuestionTypes(record.question_types),
    adaptive_explanation:
      typeof record.adaptive_explanation === 'string' ? record.adaptive_explanation : null,
    quiz: normalizeAdaptiveQuizPlan(record.quiz),
    metadata: record.metadata && typeof record.metadata === 'object' ? (record.metadata as Record<string, unknown>) : {},
    snapshot: normalizeLearnerStateSnapshot(record.snapshot),
  };
};

const normalizeAdaptiveExplanation = (value: unknown): AdaptiveExplanationResponse => {
  const record = asRecord(value);
  return {
    user_id: asString(record.user_id),
    path_id: asString(record.path_id),
    lesson_id: asString(record.lesson_id),
    action: asString(record.action, 'NO_ACTION') as AdaptiveExplanationResponse['action'],
    reason: asString(record.reason),
    target_concepts: Array.isArray(record.target_concepts)
      ? record.target_concepts.map((item) => asString(item)).filter(Boolean)
      : [],
    explanation: asString(record.explanation),
    recommended_difficulty: asAdaptiveDifficulty(record.recommended_difficulty),
    recommended_bloom_levels: asAdaptiveBloomLevels(record.recommended_bloom_levels),
    retry_strategy: asAdaptiveRetryStrategy(record.retry_strategy),
    question_types: asAdaptiveQuestionTypes(record.question_types),
    adaptive_explanation:
      typeof record.adaptive_explanation === 'string' ? record.adaptive_explanation : null,
    quiz: normalizeAdaptiveQuizPlan(record.quiz),
    snapshot: normalizeLearnerStateSnapshot(record.snapshot),
  };
};

const mapNextStepToLegacyAction = (
  nextStep: AdaptiveNextStepResponse,
  userId: string,
  lessonId: string,
): AdaptiveNextAction => {
  const mappedAction: AdaptiveNextAction['next_best_action'] =
    nextStep.action === 'UNLOCK_NEXT_LESSON'
      ? 'move_to_next_lesson'
      : nextStep.action === 'ASSIGN_REMEDIAL_RESOURCE' ||
          nextStep.action === 'GENERATE_REINFORCEMENT_QUIZ' ||
          nextStep.action === 'REVIEW_WEAK_CONCEPT'
        ? 'reinforce_weak_concept'
        : nextStep.action === 'RECOMMEND_SHORT_RESOURCE'
          ? 'resume_unfinished'
          : 'review_summary';

  return {
    user_id: userId,
    next_best_action: mappedAction,
    reason: nextStep.adaptive_explanation || nextStep.reason,
    priority:
      nextStep.action === 'ASSIGN_REMEDIAL_RESOURCE' || nextStep.action === 'REVIEW_WEAK_CONCEPT'
        ? 'high'
        : nextStep.action === 'UNLOCK_NEXT_LESSON'
          ? 'low'
          : 'medium',
    recommended_mode:
      nextStep.action === 'UNLOCK_NEXT_LESSON'
        ? 'learn_new'
        : nextStep.action === 'ASSIGN_REMEDIAL_RESOURCE' ||
            nextStep.action === 'REVIEW_WEAK_CONCEPT'
          ? 'reinforce_weaknesses'
          : 'continue_learning',
    target_concepts: nextStep.target_concepts,
    lesson_id: lessonId,
    resource_id:
      typeof nextStep.resources[0]?.resource_id === 'string' ? nextStep.resources[0].resource_id : null,
    estimated_total_time:
      typeof nextStep.resources[0]?.estimated_time === 'number'
        ? nextStep.resources[0].estimated_time
        : typeof nextStep.resources[0]?.estimated_read_time === 'number'
          ? nextStep.resources[0].estimated_read_time
          : null,
  };
};

const mapNextStepToLegacyRecommendation = (
  nextStep: AdaptiveNextStepResponse,
  userId: string,
  lessonId: string,
): AdaptiveRecommendationPayload => ({
  user_id: userId,
  action:
    nextStep.action === 'UNLOCK_NEXT_LESSON'
      ? 'move_to_next_lesson'
      : nextStep.action === 'RECOMMEND_SHORT_RESOURCE'
        ? 'resume_unfinished'
        : nextStep.action === 'NO_ACTION'
          ? 'review_summary'
          : 'reinforce_weak_concept',
  recommendation_type: nextStep.resources.length > 0 ? 'resource' : nextStep.should_unlock_next ? 'lesson' : 'chunk',
  recommendation_mode:
    nextStep.action === 'UNLOCK_NEXT_LESSON'
      ? 'learn_new'
      : nextStep.action === 'ASSIGN_REMEDIAL_RESOURCE' ||
          nextStep.action === 'REVIEW_WEAK_CONCEPT'
        ? 'reinforce_weaknesses'
        : 'continue_learning',
  items: nextStep.resources,
  reason: nextStep.adaptive_explanation || nextStep.reason,
  target_concepts: nextStep.target_concepts,
  estimated_total_time:
    typeof nextStep.resources[0]?.estimated_time === 'number'
      ? nextStep.resources[0].estimated_time
      : typeof nextStep.resources[0]?.estimated_read_time === 'number'
        ? nextStep.resources[0].estimated_read_time
        : 0,
  lesson_id: lessonId,
  resource_id:
    typeof nextStep.resources[0]?.resource_id === 'string' ? nextStep.resources[0].resource_id : null,
});

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
    path_id?: string;
    lesson_id?: string;
  }): Promise<AdaptiveNextAction> {
    if (params?.user_id && params?.path_id && params?.lesson_id) {
      const nextStep = await this.getAdaptiveNextStep({
        user_id: params.user_id,
        path_id: params.path_id,
        lesson_id: params.lesson_id,
      });
      return mapNextStepToLegacyAction(nextStep, params.user_id, params.lesson_id);
    }
    const query = new URLSearchParams();
    if (params?.user_id) {
      query.set('user_id', params.user_id);
    }
    if (params?.path_id) {
      query.set('path_id', params.path_id);
    }
    if (params?.lesson_id) {
      query.set('lesson_id', params.lesson_id);
    }
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return normalizeNextAction(await apiClient.get(`/adaptive/next-action${suffix}`));
  },

  async getAdaptiveRecommendation(params?: {
    user_id?: string;
    path_id?: string;
    lesson_id?: string;
    goal?: string;
    level?: string;
  }): Promise<AdaptiveRecommendationPayload> {
    if (params?.user_id && params?.path_id && params?.lesson_id) {
      const nextStep = await this.getAdaptiveNextStep({
        user_id: params.user_id,
        path_id: params.path_id,
        lesson_id: params.lesson_id,
      });
      return mapNextStepToLegacyRecommendation(nextStep, params.user_id, params.lesson_id);
    }
    const query = new URLSearchParams();
    if (params?.user_id) {
      query.set('user_id', params.user_id);
    }
    if (params?.path_id) {
      query.set('path_id', params.path_id);
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

  async getLearnerStateSnapshot(params?: {
    user_id?: string;
    path_id?: string;
    lesson_id?: string;
  }): Promise<LearnerStateSnapshot> {
    if (params?.user_id && params?.path_id) {
      const query = new URLSearchParams();
      query.set('path_id', params.path_id);
      if (params.lesson_id) {
        query.set('lesson_id', params.lesson_id);
      }
      const suffix = `?${query.toString()}`;
      return normalizeLearnerStateSnapshot(
        await apiClient.get(`/adaptive/state/${encodeURIComponent(params.user_id)}${suffix}`),
      );
    }
    const suffix = params?.user_id ? `?user_id=${encodeURIComponent(params.user_id)}` : '';
    return normalizeLearnerStateSnapshot(await apiClient.get(`/adaptive/learner-state${suffix}`));
  },

  async recomputeLearnerState(params: {
    user_id: string;
    path_id: string;
    lesson_id?: string;
  }): Promise<LearnerStateSnapshot> {
    const query = new URLSearchParams();
    query.set('path_id', params.path_id);
    if (params.lesson_id) {
      query.set('lesson_id', params.lesson_id);
    }
    return normalizeLearnerStateSnapshot(
      await apiClient.post(
        `/adaptive/recompute-state/${encodeURIComponent(params.user_id)}?${query.toString()}`,
      ),
    );
  },

  async getAdaptiveNextStep(params: {
    user_id: string;
    path_id: string;
    lesson_id: string;
  }): Promise<AdaptiveNextStepResponse> {
    return normalizeAdaptiveNextStep(await apiClient.post('/adaptive/next-step', params));
  },

  async getAdaptiveExplanation(params: {
    user_id: string;
    path_id: string;
    lesson_id: string;
  }): Promise<AdaptiveExplanationResponse> {
    const query = new URLSearchParams();
    query.set('path_id', params.path_id);
    query.set('lesson_id', params.lesson_id);
    return normalizeAdaptiveExplanation(
      await apiClient.get(
        `/adaptive/explanations/${encodeURIComponent(params.user_id)}?${query.toString()}`,
      ),
    );
  },
};
