import type {
  AdaptiveRecommendation,
  ConfidenceOverview,
  GoalProgressConceptItem,
  GoalProgressResponse,
  PersonalizedRecommendationResponse,
  ProgressOverview,
  ProgressSummary,
  ProgressUpdateResponse,
  RecommendedConceptApiItem,
  RecommendedConceptsResponse,
  RecommendedResourceItem,
  ResourceSearchResponse,
} from '../../types/dashboard';

export type ApiRecord = Record<string, unknown>;

export const asRecord = (value: unknown): ApiRecord =>
  typeof value === 'object' && value !== null ? (value as ApiRecord) : {};

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const asBoolean = (value: unknown, fallback = false): boolean =>
  typeof value === 'boolean' ? value : fallback;

const normalizeRecommendedConcept = (value: unknown): RecommendedConceptApiItem => {
  const record = asRecord(value);

  return {
    concept_id: asNumber(record.concept_id),
    concept_name: asString(record.concept_name, 'Khái niệm học tập'),
    difficulty: typeof record.difficulty === 'number' ? record.difficulty : undefined,
    topic: typeof record.topic === 'string' ? record.topic : undefined,
  };
};

const normalizeRecommendedResource = (value: unknown): RecommendedResourceItem => {
  const record = asRecord(value);

  return {
    resource_id:
      typeof record.resource_id === 'string' || typeof record.resource_id === 'number'
        ? record.resource_id
        : '',
    title: asString(record.title, 'Tài nguyên học tập'),
    source: asString(record.source, 'web'),
    level: asString(record.level, 'beginner'),
    topic: asString(record.topic),
    url: typeof record.url === 'string' ? record.url : null,
    reason: asString(record.reason, 'Phù hợp với lộ trình học hiện tại của bạn.'),
    relevance_score: asNumber(record.relevance_score),
  };
};

const normalizeGoalProgressConcept = (value: unknown): GoalProgressConceptItem => {
  const record = asRecord(value);

  return {
    concept_id: asNumber(record.concept_id),
    concept_name: asString(record.concept_name, 'Khái niệm học tập'),
    difficulty: asNumber(record.difficulty),
    mastery: asNumber(record.mastery),
    status: asString(record.status, 'not_started'),
  };
};

const normalizeConceptProgress = (value: unknown): ProgressSummary['concepts'][number] => {
  const record = asRecord(value);

  return {
    concept_id: asNumber(record.concept_id),
    concept_name: asString(record.concept_name, 'Khái niệm học tập'),
    mastery: asNumber(record.mastery),
    confidence: asNumber(record.confidence),
    total_attempts: asNumber(record.total_attempts),
    successful_attempts: asNumber(record.successful_attempts),
    status:
      record.status === 'not_started' ||
      record.status === 'in_progress' ||
      record.status === 'proficient' ||
      record.status === 'complete'
        ? record.status
        : 'not_started',
    last_updated: asString(record.last_updated),
    progress_percentage: asNumber(record.progress_percentage),
  };
};

const normalizeProgressSummary = (value: unknown): ProgressSummary => {
  const record = asRecord(value);

  return {
    user_id: asString(record.user_id),
    total_concepts_started: asNumber(record.total_concepts_started),
    total_concepts_completed: asNumber(record.total_concepts_completed),
    average_mastery: asNumber(record.average_mastery),
    average_confidence: asNumber(record.average_confidence),
    concepts: Array.isArray(record.concepts) ? record.concepts.map(normalizeConceptProgress) : [],
  };
};

export const normalizeRecommendedConceptsResponse = (value: unknown): RecommendedConceptsResponse => {
  const record = asRecord(value);

  return {
    success: asBoolean(record.success),
    user_id: asString(record.user_id),
    recommended: Array.isArray(record.recommended)
      ? record.recommended.map(normalizeRecommendedConcept)
      : [],
  };
};

export const normalizeProgressOverview = (value: unknown): ProgressOverview => {
  const record = asRecord(value);

  return {
    success: asBoolean(record.success),
    user_id: asString(record.user_id),
    overall_progress_percent: asNumber(record.overall_progress_percent),
    progress_bar: asNumber(record.progress_bar),
    weekly_comparison_percent: asNumber(record.weekly_comparison_percent),
    summary: normalizeProgressSummary(record.summary),
  };
};

export const normalizeConfidenceOverview = (value: unknown): ConfidenceOverview => {
  const record = asRecord(value);

  return {
    success: asBoolean(record.success),
    user_id: asString(record.user_id),
    confidence: asNumber(record.confidence),
    level: asString(record.level, 'beginner'),
    trend: asString(record.trend),
    explanation: asString(record.explanation),
  };
};

export const normalizeProgressSummaryResponse = (
  value: unknown
): { success: boolean; user_id: string; summary: ProgressSummary } => {
  const record = asRecord(value);

  return {
    success: asBoolean(record.success),
    user_id: asString(record.user_id),
    summary: normalizeProgressSummary(record.summary),
  };
};

export const normalizeAdaptiveRecommendation = (
  concept: RecommendedConceptApiItem,
  index: number
): AdaptiveRecommendation => ({
  concept_id: concept.concept_id,
  concept_name: concept.concept_name,
  reasons: [
    concept.topic
      ? `Nên ưu tiên tiếp tục với chủ đề ${concept.topic.toLowerCase()}.`
      : 'Đây là khái niệm phù hợp với tiến độ học tập hiện tại của bạn.',
    typeof concept.difficulty === 'number'
      ? `Độ khó tham chiếu: ${concept.difficulty}/10.`
      : 'Mức độ phù hợp để học tiếp ngay lúc này.',
    index === 0
      ? 'Được ưu tiên cao nhất từ dữ liệu tiến độ gần đây.'
      : 'Được đề xuất tiếp theo từ dữ liệu tiến độ gần đây.',
  ],
  priority_score: Math.max(0.2, 1 - index * 0.2),
});

export const buildSummaryFallback = (summary: ProgressSummary): AdaptiveRecommendation[] =>
  summary.concepts
    .filter((concept) => concept.mastery < 0.8 && concept.status !== 'not_started')
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 3)
    .map((concept, index) => ({
      concept_id: concept.concept_id,
      concept_name: concept.concept_name,
      reasons: [
        concept.mastery < 0.5
          ? 'Bạn đang cần củng cố thêm phần nền tảng của khái niệm này.'
          : 'Khái niệm này nên được ôn lại để tăng độ chắc chắn.',
        `Mức độ thành thạo hiện tại: ${Math.round(concept.mastery * 100)}%.`,
        index === 0
          ? 'Đây là ưu tiên cao nhất từ dữ liệu tiến độ hiện có.'
          : 'Đây là một trong những bước học tiếp theo phù hợp.',
      ],
      priority_score: 1 - concept.mastery,
    }));

export const normalizeProgressUpdateResponse = (value: unknown): ProgressUpdateResponse => {
  const record = asRecord(value);
  const message = asString(record.message);

  return {
    success: asBoolean(record.success),
    message: message || undefined,
  };
};

export const normalizeResourceSearchResponse = (value: unknown): ResourceSearchResponse => {
  const record = asRecord(value);

  return {
    results: Array.isArray(record.results) ? record.results : [],
    total: typeof record.total === 'number' ? record.total : undefined,
    page: typeof record.page === 'number' ? record.page : undefined,
    size: typeof record.size === 'number' ? record.size : undefined,
  };
};

export const normalizePersonalizedRecommendationResponse = (
  value: unknown
): PersonalizedRecommendationResponse => {
  const record = asRecord(value);

  return {
    user_id:
      typeof record.user_id === 'number' || typeof record.user_id === 'string'
        ? record.user_id
        : '',
    goal: asString(record.goal),
    level: asString(record.level, 'beginner'),
    recommended_resources: Array.isArray(record.recommended_resources)
      ? record.recommended_resources.map(normalizeRecommendedResource)
      : [],
    completed_concepts: asNumber(record.completed_concepts),
    total_concepts: asNumber(record.total_concepts),
    progress_percentage: asNumber(record.progress_percentage),
    message: asString(record.message),
  };
};

export const normalizeGoalLearningProgressResponse = (value: unknown): GoalProgressResponse => {
  const record = asRecord(value);

  return {
    user_id:
      typeof record.user_id === 'number' || typeof record.user_id === 'string'
        ? record.user_id
        : '',
    goal: asString(record.goal),
    concepts: Array.isArray(record.concepts) ? record.concepts.map(normalizeGoalProgressConcept) : [],
    overall_mastery: asNumber(record.overall_mastery),
    message: asString(record.message),
  };
};
