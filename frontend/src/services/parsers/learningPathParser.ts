import type {
  BloomLevel,
  ConceptNode,
  DistributionPlan,
  LearningLevel,
  LearningPath,
  LearningPathChapter,
  LearningPathDeleteResponse,
  LearningPathHistory,
  LearningPathLesson,
  LearningPathLlmStatus,
  LearningPathSubjectId,
  LessonLockInfo,
  LessonLocksResponse,
  LessonProgressApiResponse,
  LessonRefinementState,
  LessonStudyTimeResponse,
  LessonQuestion,
  LessonQuestions,
  RecommendedLessonResource,
  AdaptiveQuizNextResponse,
  LessonQuestionGenerationResponse,
  LessonQuestionType,
  LessonRecommendedChunks,
  LessonStatus,
  StudySummary,
  LessonAttemptStatistics,
  LessonCompletionStatus,
  LessonSize,
} from '../../types/learningPath';

const DEFAULT_GENERATED_AT = () => new Date().toISOString();
export type ApiRecord = Record<string, unknown>;

export const asRecord = (value: unknown): ApiRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as ApiRecord) : {};

export const normalizeLessonStatus = (value: unknown): LessonStatus => {
  if (value === 'in_progress') {
    return value;
  }
  if (value === 'complete' || value === 'completed') {
    return 'complete';
  }
  return 'not_started';
};

const normalizeQuestionType = (value: unknown): LessonQuestionType => {
  if (value === 'short_answer' || value === 'true_false') {
    return value;
  }
  return 'multiple_choice';
};

const normalizeBloomLevel = (value: unknown): BloomLevel => {
  switch (value) {
    case 'apply':
    case 'analyze':
    case 'evaluate':
    case 'create':
    case 'understand':
      return value;
    default:
      return 'remember';
  }
};

const normalizeLearningLevel = (value: unknown): LearningLevel => {
  if (value === 'intermediate' || value === 'advanced') {
    return value;
  }
  return 'beginner';
};

const normalizeLessonCompletionStatus = (value: unknown): LessonCompletionStatus | null => {
  if (
    value === 'completed' ||
    value === 'reinforce_required' ||
    value === 'retry_required'
  ) {
    return value;
  }
  return null;
};

const normalizeLessonSize = (value: unknown): LessonSize | null => {
  if (value === 'small' || value === 'medium' || value === 'large') {
    return value;
  }
  return null;
};

const normalizeDistributionPlan = (value: unknown): DistributionPlan => {
  const record = asRecord(value);
  const normalizeNumberMap = (source: unknown) => {
    const sourceRecord = asRecord(source);
    return Object.fromEntries(
      Object.entries(sourceRecord).map(([key, item]) => [key, Number(item ?? 0)]),
    );
  };

  return {
    ratios: normalizeNumberMap(record.ratios),
    counts: normalizeNumberMap(record.counts),
    level_counts: normalizeNumberMap(record.level_counts),
    mastery:
      typeof record.mastery === 'number' ? record.mastery : Number(record.mastery ?? 0),
  };
};

const normalizeSubjectId = (value: unknown): LearningPathSubjectId | undefined => {
  if (
    value === 'python' ||
    value === 'cpp' ||
    value === 'csharp' ||
    value === 'java' ||
    value === 'web'
  ) {
    return value;
  }
  return undefined;
};

const normalizeLesson = (lesson: unknown): LearningPathLesson => {
  const lessonRecord = asRecord(lesson);

  return {
    lesson_id: String(lessonRecord.lesson_id ?? ''),
    title: String(lessonRecord.title ?? 'Bài học'),
    summary: String(lessonRecord.summary ?? ''),
    resources: Array.isArray(lessonRecord.resources)
      ? lessonRecord.resources
          .filter((item: unknown): item is string => typeof item === 'string')
          .map((item: string) => item.trim())
          .filter(Boolean)
      : [],
    status: normalizeLessonStatus(lessonRecord.status),
    recommended_chunk_ids: Array.isArray(lessonRecord.recommended_chunk_ids)
      ? lessonRecord.recommended_chunk_ids.map((item: unknown) => String(item))
      : [],
  };
};

const normalizeLessonWithExtras = (lesson: unknown): LearningPathLesson => {
  const baseLesson = normalizeLesson(lesson);
  const lessonRecord = asRecord(lesson);
  const recommendedResources = Array.isArray(lessonRecord.recommended_resources)
    ? lessonRecord.recommended_resources.map((item) => {
        const resourceRecord = asRecord(item);
        return {
          ...resourceRecord,
          resource_id:
            resourceRecord.resource_id == null ? null : String(resourceRecord.resource_id),
          title: typeof resourceRecord.title === 'string' ? resourceRecord.title : null,
          type: typeof resourceRecord.type === 'string' ? resourceRecord.type : null,
          source: typeof resourceRecord.source === 'string' ? resourceRecord.source : null,
          topic: typeof resourceRecord.topic === 'string' ? resourceRecord.topic : null,
          level: typeof resourceRecord.level === 'string' ? resourceRecord.level : null,
          url: typeof resourceRecord.url === 'string' ? resourceRecord.url : null,
        } as RecommendedLessonResource;
      })
    : [];
  const refinementRecord = asRecord(lessonRecord.refinement);

  return {
    ...baseLesson,
    resources:
      baseLesson.resources.length > 0
        ? baseLesson.resources
        : recommendedResources
            .map((item) => (typeof item.title === 'string' ? item.title.trim() : ''))
            .filter(Boolean)
            .slice(0, 4),
    objectives: Array.isArray(lessonRecord.objectives)
      ? lessonRecord.objectives.map((item: unknown) => String(item))
      : [],
    prerequisites: Array.isArray(lessonRecord.prerequisites)
      ? lessonRecord.prerequisites.map((item: unknown) => String(item))
      : [],
    target_concepts: Array.isArray(lessonRecord.target_concepts)
      ? lessonRecord.target_concepts.map((item: unknown) => String(item))
      : [],
    prerequisite_concepts: Array.isArray(lessonRecord.prerequisite_concepts)
      ? lessonRecord.prerequisite_concepts.map((item: unknown) => String(item))
      : [],
    difficulty:
      typeof lessonRecord.difficulty === 'number' ? lessonRecord.difficulty : undefined,
    lesson_kind: typeof lessonRecord.lesson_kind === 'string' ? lessonRecord.lesson_kind : null,
    unlock_strategy:
      typeof lessonRecord.unlock_strategy === 'string' ? lessonRecord.unlock_strategy : null,
    recommended_resources: recommendedResources,
    adaptation_metadata:
      lessonRecord.adaptation_metadata &&
      typeof lessonRecord.adaptation_metadata === 'object' &&
      !Array.isArray(lessonRecord.adaptation_metadata)
        ? (lessonRecord.adaptation_metadata as Record<string, unknown>)
        : {},
    refinement: {
      ...refinementRecord,
      preferred_format:
        typeof refinementRecord.preferred_format === 'string'
          ? refinementRecord.preferred_format
          : null,
      pace: typeof refinementRecord.pace === 'string' ? refinementRecord.pace : null,
      bridge_required: Boolean(refinementRecord.bridge_required),
      extra_practice: Boolean(refinementRecord.extra_practice),
      skip_easy_content: Boolean(refinementRecord.skip_easy_content),
      actions: Array.isArray(refinementRecord.actions)
        ? refinementRecord.actions.map((item) => asRecord(item))
        : [],
    } as LessonRefinementState,
    last_confidence:
      typeof lessonRecord.last_confidence === 'number' ? lessonRecord.last_confidence : null,
    confidence_updated_at:
      typeof lessonRecord.confidence_updated_at === 'string'
        ? lessonRecord.confidence_updated_at
        : lessonRecord.confidence_updated_at instanceof Date
          ? lessonRecord.confidence_updated_at.toISOString()
          : null,
    is_locked: typeof lessonRecord.is_locked === 'boolean' ? lessonRecord.is_locked : undefined,
    reason_locked:
      typeof lessonRecord.reason_locked === 'string' ? lessonRecord.reason_locked : undefined,
    blocking_lesson_id:
      typeof lessonRecord.blocking_lesson_id === 'string'
        ? lessonRecord.blocking_lesson_id
        : null,
    blocking_concepts: Array.isArray(lessonRecord.blocking_concepts)
      ? lessonRecord.blocking_concepts.map((item: unknown) => String(item))
      : [],
    missing_prerequisite_concepts: Array.isArray(lessonRecord.missing_prerequisite_concepts)
      ? lessonRecord.missing_prerequisite_concepts.map((item: unknown) => String(item))
      : [],
    prerequisite_mastery:
      lessonRecord.prerequisite_mastery &&
      typeof lessonRecord.prerequisite_mastery === 'object' &&
      !Array.isArray(lessonRecord.prerequisite_mastery)
        ? Object.fromEntries(
            Object.entries(lessonRecord.prerequisite_mastery).map(([key, value]) => [
              key,
              typeof value === 'number' ? value : Number(value || 0),
            ]),
          )
        : {},
    bridge_recommendations: Array.isArray(lessonRecord.bridge_recommendations)
      ? lessonRecord.bridge_recommendations.map((item) => asRecord(item))
      : [],
    mastery_threshold:
      typeof lessonRecord.mastery_threshold === 'number' ? lessonRecord.mastery_threshold : null,
  };
};

const normalizeConceptNode = (item: unknown, index: number): ConceptNode => {
  const conceptRecord = asRecord(item);
  const conceptId =
    typeof conceptRecord.concept_id === 'number' ? conceptRecord.concept_id : 900000 + index;
  const resources = Array.isArray(conceptRecord.resources)
    ? conceptRecord.resources.map((resource) => {
        const resourceRecord = asRecord(resource);
        return {
          title: typeof resourceRecord.title === 'string' ? resourceRecord.title : undefined,
          url: typeof resourceRecord.url === 'string' ? resourceRecord.url : undefined,
          source: typeof resourceRecord.source === 'string' ? resourceRecord.source : undefined,
        };
      })
    : [];

  return {
    concept_id: conceptId,
    concept_name: String(conceptRecord.concept_name ?? `Khái niệm ${index}`),
    difficulty: typeof conceptRecord.difficulty === 'number' ? conceptRecord.difficulty : 1,
    bloom_level:
      typeof conceptRecord.bloom_level === 'string' ? conceptRecord.bloom_level : undefined,
    mode: String(conceptRecord.mode ?? 'normal'),
    priority_score:
      typeof conceptRecord.priority_score === 'number' ? conceptRecord.priority_score : 0.5,
    resources,
  };
};

const normalizeLlmStatus = (value: unknown): LearningPathLlmStatus | null => {
  const llmRecord = asRecord(value);
  if (!Object.keys(llmRecord).length) {
    return null;
  }

  return {
    provider: String(llmRecord.provider ?? ''),
    enabled: Boolean(llmRecord.enabled),
    cooldown_active:
      typeof llmRecord.cooldown_active === 'boolean' ? llmRecord.cooldown_active : undefined,
    reason: typeof llmRecord.reason === 'string' ? llmRecord.reason : null,
    model: typeof llmRecord.model === 'string' ? llmRecord.model : null,
  };
};

const normalizeChapter = (chapter: unknown): LearningPathChapter => {
  const chapterRecord = asRecord(chapter);

  return {
    chapter_id: String(chapterRecord.chapter_id ?? ''),
    title: String(chapterRecord.title ?? 'Chương học'),
    lessons: Array.isArray(chapterRecord.lessons)
      ? chapterRecord.lessons.map(normalizeLessonWithExtras)
      : [],
  };
};

const deriveRecommendedPathFromChapters = (chapters: LearningPathChapter[]): ConceptNode[] => {
  const concepts: ConceptNode[] = [];
  let index = 1;

  chapters.forEach((chapter) => {
    chapter.lessons.forEach((lesson) => {
      concepts.push({
        concept_id: 900000 + index,
        concept_name: lesson.title,
        difficulty: Math.min(4, 1 + Math.floor((index - 1) / 2)),
        bloom_level: index <= 2 ? 'understand' : 'apply',
        mode: 'normal',
        priority_score: Math.max(0.5, 1 - index * 0.03),
        resources: lesson.resources.map((title) => ({ title })),
      });
      index += 1;
    });
  });

  return concepts;
};

export const normalizeLearningPath = (payload: unknown): LearningPath => {
  const payloadRecord = asRecord(payload);
  const source = asRecord(payloadRecord.path ?? payloadRecord);
  const chapters = Array.isArray(source.chapters)
    ? source.chapters.map(normalizeChapter)
    : Array.isArray(source.curriculum)
      ? source.curriculum.map(normalizeChapter)
      : [];

  const recommendedPath = Array.isArray(source.recommended_path)
    ? source.recommended_path.map((item, index) => normalizeConceptNode(item, index + 1))
    : deriveRecommendedPathFromChapters(chapters);

  return {
    path_id: String(source.path_id ?? ''),
    user_id: source.user_id ? String(source.user_id) : undefined,
    subject_id: normalizeSubjectId(source.subject_id),
    goal: String(source.goal ?? ''),
    level: normalizeLearningLevel(source.level),
    generated_at: String(source.generated_at ?? source.created_at ?? DEFAULT_GENERATED_AT()),
    recommended_path: recommendedPath,
    chapters,
    curriculum: chapters,
    curriculum_source:
      typeof source.curriculum_source === 'string' ? source.curriculum_source : undefined,
    curriculum_notice:
      typeof source.curriculum_notice === 'string' ? source.curriculum_notice : null,
    llm_status: normalizeLlmStatus(source.llm_status),
    message: String(source.message ?? ''),
  };
};

export const normalizeHistoryItem = (item: unknown): LearningPathHistory => {
  const itemRecord = asRecord(item);

  return {
    path_id: String(itemRecord.path_id ?? ''),
    subject_id: normalizeSubjectId(itemRecord.subject_id),
    goal: String(itemRecord.goal ?? ''),
    level: normalizeLearningLevel(itemRecord.level),
    generated_at: String(
      itemRecord.generated_at ?? itemRecord.created_at ?? DEFAULT_GENERATED_AT(),
    ),
    chapter_count:
      typeof itemRecord.chapter_count === 'number' ? itemRecord.chapter_count : undefined,
    lesson_count: typeof itemRecord.lesson_count === 'number' ? itemRecord.lesson_count : undefined,
  };
};

const normalizeLessonQuestion = (item: unknown): LessonQuestion => {
  const itemRecord = asRecord(item);

  return {
    question_id: String(itemRecord.question_id ?? ''),
    subject_id: String(itemRecord.subject_id ?? ''),
    chapter_id: String(itemRecord.chapter_id ?? ''),
    lesson_id: String(itemRecord.lesson_id ?? ''),
    chunk_ids: Array.isArray(itemRecord.chunk_ids)
      ? itemRecord.chunk_ids.map((chunkId: unknown) => String(chunkId))
      : [],
    resource_ids: Array.isArray(itemRecord.resource_ids)
      ? itemRecord.resource_ids.map((resourceId: unknown) => String(resourceId))
      : [],
    question_type: normalizeQuestionType(itemRecord.question_type),
    question: String(itemRecord.question ?? ''),
    correct_answer: String(itemRecord.correct_answer ?? ''),
    distractors: Array.isArray(itemRecord.distractors)
      ? itemRecord.distractors.map((choice: unknown) => String(choice)).filter(Boolean)
      : [],
    explanation: String(itemRecord.explanation ?? ''),
    difficulty: normalizeLearningLevel(itemRecord.difficulty),
    bloom_level: normalizeBloomLevel(itemRecord.bloom_level),
    is_ai_generated: Boolean(itemRecord.is_ai_generated),
    llm_provider: itemRecord.llm_provider ? String(itemRecord.llm_provider) : null,
    llm_model: itemRecord.llm_model ? String(itemRecord.llm_model) : null,
    metadata:
      itemRecord.metadata &&
      typeof itemRecord.metadata === 'object' &&
      !Array.isArray(itemRecord.metadata)
        ? (itemRecord.metadata as Record<string, unknown>)
        : {},
    created_at: String(itemRecord.created_at ?? DEFAULT_GENERATED_AT()),
  };
};

export const normalizeLessonQuestions = (payload: unknown): LessonQuestions => {
  const payloadRecord = asRecord(payload);
  const questions = Array.isArray(payloadRecord.questions)
    ? payloadRecord.questions
    : Array.isArray(payloadRecord.items)
      ? payloadRecord.items
      : [];

  return {
    lesson_id: String(payloadRecord.lesson_id ?? ''),
    total:
      typeof payloadRecord.total === 'number'
        ? payloadRecord.total
        : Array.isArray(questions)
          ? questions.length
          : 0,
    questions: Array.isArray(questions) ? questions.map(normalizeLessonQuestion) : [],
  };
};

export const normalizeLessonRecommendedChunks = (payload: unknown): LessonRecommendedChunks => {
  const payloadRecord = asRecord(payload);
  const source =
    payloadRecord.recommendation &&
    typeof payloadRecord.recommendation === 'object' &&
    !Array.isArray(payloadRecord.recommendation)
      ? asRecord(payloadRecord.recommendation)
      : payloadRecord;

  return {
    recommendation_id: String(source.recommendation_id ?? ''),
    subject_id: String(source.subject_id ?? ''),
    chapter_id: String(source.chapter_id ?? ''),
    lesson_id: String(source.lesson_id ?? ''),
    chunk_ids: Array.isArray(source.chunk_ids)
      ? source.chunk_ids.map((item: unknown) => String(item))
      : [],
    resource_ids: Array.isArray(source.resource_ids)
      ? source.resource_ids.map((item: unknown) => String(item))
      : [],
    selection_strategy: String(source.selection_strategy ?? ''),
    metadata:
      source.metadata && typeof source.metadata === 'object' && !Array.isArray(source.metadata)
        ? (source.metadata as Record<string, unknown>)
        : {},
    sequence_metadata:
      source.sequence_metadata &&
      typeof source.sequence_metadata === 'object' &&
      !Array.isArray(source.sequence_metadata)
        ? (source.sequence_metadata as Record<string, unknown>)
        : {},
    recommended_chunks: Array.isArray(source.recommended_chunks)
      ? source.recommended_chunks.map((item: unknown) => {
          const chunkRecord = asRecord(item);
          return {
            chunk_id: String(chunkRecord.chunk_id ?? ''),
            resource_id: String(chunkRecord.resource_id ?? ''),
            chunk_index: typeof chunkRecord.chunk_index === 'number' ? chunkRecord.chunk_index : 0,
            page_number:
              typeof chunkRecord.page_number === 'number' ? chunkRecord.page_number : undefined,
            score: typeof chunkRecord.score === 'number' ? chunkRecord.score : 0,
            preview: String(chunkRecord.preview ?? ''),
            resource_title:
              typeof chunkRecord.resource_title === 'string'
                ? chunkRecord.resource_title
                : undefined,
            resource_source:
              typeof chunkRecord.resource_source === 'string'
                ? chunkRecord.resource_source
                : undefined,
            resource_url:
              typeof chunkRecord.resource_url === 'string' ? chunkRecord.resource_url : undefined,
            instruction_role:
              typeof chunkRecord.instruction_role === 'string'
                ? chunkRecord.instruction_role
                : undefined,
            covered_objectives: Array.isArray(chunkRecord.covered_objectives)
              ? chunkRecord.covered_objectives.map((value: unknown) => String(value))
              : [],
            covered_concepts: Array.isArray(chunkRecord.covered_concepts)
              ? chunkRecord.covered_concepts.map((value: unknown) => String(value))
              : [],
            estimated_read_time:
              typeof chunkRecord.estimated_read_time === 'number'
                ? chunkRecord.estimated_read_time
                : undefined,
            sequence_position:
              typeof chunkRecord.sequence_position === 'number'
                ? chunkRecord.sequence_position
                : undefined,
            questionability_score:
              typeof chunkRecord.questionability_score === 'number'
                ? chunkRecord.questionability_score
                : undefined,
          };
        })
      : [],
    created_at: String(source.created_at ?? DEFAULT_GENERATED_AT()),
  };
};

export const normalizeLessonAttemptStatistics = (
  payload: unknown,
  fallbackLessonId?: string,
): LessonAttemptStatistics => {
  const response = asRecord(payload);
  const asNullableNumber = (value: unknown): number | null =>
    value == null ? null : Number(value);

  return {
    lesson_id:
      typeof response.lesson_id === 'string' ? response.lesson_id : fallbackLessonId || null,
    total_attempts: Number(response.total_attempts ?? 0),
    passed_attempts: Number(response.passed_attempts ?? 0),
    best_confidence: asNullableNumber(response.best_confidence),
    best_bloom_score: asNullableNumber(response.best_bloom_score),
    best_attempt_confidence: asNullableNumber(response.best_attempt_confidence),
    best_attempt_bloom_score: asNullableNumber(response.best_attempt_bloom_score),
    best_attempt_mastery_score: asNullableNumber(response.best_attempt_mastery_score),
    avg_confidence: asNullableNumber(response.avg_confidence),
    latest_confidence: asNullableNumber(response.latest_confidence),
    improvement: asNullableNumber(response.improvement),
    success_rate: Number(response.success_rate ?? 0),
    best_mastery_score: asNullableNumber(response.best_mastery_score),
    latest_mastery_score: asNullableNumber(response.latest_mastery_score),
    best_attempt_number: response.best_attempt_number == null ? null : Number(response.best_attempt_number),
    best_attempt_completion_status: normalizeLessonCompletionStatus(
      response.best_attempt_completion_status,
    ),
    latest_completion_status: normalizeLessonCompletionStatus(
      response.latest_completion_status,
    ),
  };
};

export const normalizeLearningPathDeleteResponse = (
  payload: unknown,
  fallbackPathId: string,
): LearningPathDeleteResponse => {
  const response = asRecord(payload);
  return {
    path_id: String(response.path_id ?? fallbackPathId),
    deleted: Boolean(response.deleted),
    removed_lessons: typeof response.removed_lessons === 'number' ? response.removed_lessons : 0,
    removed_chapters: typeof response.removed_chapters === 'number' ? response.removed_chapters : 0,
    removed_recommendations:
      typeof response.removed_recommendations === 'number' ? response.removed_recommendations : 0,
    removed_questions:
      typeof response.removed_questions === 'number' ? response.removed_questions : 0,
  };
};

export const normalizeLessonProgressResponse = (
  payload: unknown,
  fallback: { path_id: string; lesson_id: string },
): LessonProgressApiResponse => {
  const response = asRecord(payload);
  const lessonAssessment = asRecord(response.lesson_assessment);
  const bloomAccuracyByLevelSource =
    response.bloom_accuracy_by_level &&
    typeof response.bloom_accuracy_by_level === 'object' &&
    !Array.isArray(response.bloom_accuracy_by_level)
      ? response.bloom_accuracy_by_level
      : lessonAssessment.bloom_accuracy_by_level &&
          typeof lessonAssessment.bloom_accuracy_by_level === 'object' &&
          !Array.isArray(lessonAssessment.bloom_accuracy_by_level)
        ? lessonAssessment.bloom_accuracy_by_level
        : {};
  return {
    path_id: String(response.path_id ?? fallback.path_id),
    lesson_id: String(response.lesson_id ?? fallback.lesson_id),
    status: normalizeLessonStatus(response.status),
    updated_at: String(response.updated_at ?? DEFAULT_GENERATED_AT()),
    auto_completed: Boolean(response.auto_completed),
    is_locked: Boolean(response.is_locked),
    reason_locked: response.reason_locked ? String(response.reason_locked) : undefined,
    blocking_lesson_id:
      typeof response.blocking_lesson_id === 'string' ? response.blocking_lesson_id : null,
    blocking_concepts: Array.isArray(response.blocking_concepts)
      ? response.blocking_concepts.map((item: unknown) => String(item))
      : [],
    missing_prerequisite_concepts: Array.isArray(response.missing_prerequisite_concepts)
      ? response.missing_prerequisite_concepts.map((item: unknown) => String(item))
      : [],
    prerequisite_mastery:
      response.prerequisite_mastery &&
      typeof response.prerequisite_mastery === 'object' &&
      !Array.isArray(response.prerequisite_mastery)
        ? Object.fromEntries(
            Object.entries(response.prerequisite_mastery).map(([key, value]) => [
              key,
              typeof value === 'number' ? value : Number(value || 0),
            ]),
          )
        : {},
    bridge_recommendations: Array.isArray(response.bridge_recommendations)
      ? response.bridge_recommendations.map((item) => asRecord(item))
      : [],
    mastery_threshold:
      typeof response.mastery_threshold === 'number' ? response.mastery_threshold : null,
    last_confidence:
      response.last_confidence === null || response.last_confidence === undefined
        ? undefined
        : Number(response.last_confidence),
    confidence_updated_at: response.confidence_updated_at
      ? String(response.confidence_updated_at)
      : undefined,
    accuracy:
      response.accuracy === null || response.accuracy === undefined
        ? null
        : Number(response.accuracy),
    updated_mastery:
      response.updated_mastery === null || response.updated_mastery === undefined
        ? null
        : Number(response.updated_mastery),
    mastery_score:
      response.mastery_score === null || response.mastery_score === undefined
        ? lessonAssessment.mastery_score === null || lessonAssessment.mastery_score === undefined
          ? null
          : Number(lessonAssessment.mastery_score)
        : Number(response.mastery_score),
    completion_status: normalizeLessonCompletionStatus(response.completion_status),
    reinforce_required: Boolean(response.reinforce_required),
    retry_required: Boolean(response.retry_required),
    bloom_score:
      response.bloom_score === null || response.bloom_score === undefined
        ? lessonAssessment.bloom_score === null || lessonAssessment.bloom_score === undefined
          ? null
          : Number(lessonAssessment.bloom_score)
        : Number(response.bloom_score),
    bloom_accuracy_by_level:
      bloomAccuracyByLevelSource &&
      typeof bloomAccuracyByLevelSource === 'object' &&
      !Array.isArray(bloomAccuracyByLevelSource)
        ? Object.fromEntries(
            Object.entries(bloomAccuracyByLevelSource).map(([key, value]) => [
              key,
              Number(value ?? 0),
            ]),
          )
        : {},
    concept_coverage_score:
      response.concept_coverage_score === null || response.concept_coverage_score === undefined
        ? lessonAssessment.concept_coverage_score === null ||
          lessonAssessment.concept_coverage_score === undefined
          ? null
          : Number(lessonAssessment.concept_coverage_score)
        : Number(response.concept_coverage_score),
    concept_coverage_rate:
      response.concept_coverage_rate === null || response.concept_coverage_rate === undefined
        ? lessonAssessment.concept_coverage_rate === null ||
          lessonAssessment.concept_coverage_rate === undefined
          ? null
          : Number(lessonAssessment.concept_coverage_rate)
        : Number(response.concept_coverage_rate),
    difficulty_weighted_score:
      response.difficulty_weighted_score === null ||
      response.difficulty_weighted_score === undefined
        ? lessonAssessment.difficulty_weighted_score === null ||
          lessonAssessment.difficulty_weighted_score === undefined
          ? null
          : Number(lessonAssessment.difficulty_weighted_score)
        : Number(response.difficulty_weighted_score),
    confidence_score:
      response.confidence_score === null || response.confidence_score === undefined
        ? lessonAssessment.confidence_score === null ||
          lessonAssessment.confidence_score === undefined
          ? null
          : Number(lessonAssessment.confidence_score)
        : Number(response.confidence_score),
    weak_concepts: Array.isArray(response.weak_concepts)
      ? response.weak_concepts.map((item: unknown) => String(item))
      : Array.isArray(lessonAssessment.weak_concepts)
        ? lessonAssessment.weak_concepts.map((item: unknown) => String(item))
        : [],
    next_action:
      response.next_action && typeof response.next_action === 'object' && !Array.isArray(response.next_action)
        ? asRecord(response.next_action)
        : null,
    adaptive_next_quiz:
      response.adaptive_next_quiz &&
      typeof response.adaptive_next_quiz === 'object' &&
      !Array.isArray(response.adaptive_next_quiz)
        ? asRecord(response.adaptive_next_quiz)
        : null,
  };
};

export const normalizeLessonLocksResponse = (payload: unknown): LessonLocksResponse => {
  const response = asRecord(payload);
  const lessonLocks = asRecord(response.lesson_locks);
  return {
    success: response.success !== false,
    path_id: String(response.path_id ?? ''),
    lesson_locks: Object.fromEntries(
      Object.entries(lessonLocks).map(([lessonId, item]) => {
        const lockRecord = asRecord(item);
        const normalized: LessonLockInfo = {
          is_locked: Boolean(lockRecord.is_locked),
          reason: typeof lockRecord.reason === 'string' ? lockRecord.reason : null,
          blocking_lesson_id:
            typeof lockRecord.blocking_lesson_id === 'string'
              ? lockRecord.blocking_lesson_id
              : null,
          blocking_concepts: Array.isArray(lockRecord.blocking_concepts)
            ? lockRecord.blocking_concepts.map((entry: unknown) => String(entry))
            : [],
          missing_prerequisite_concepts: Array.isArray(
            lockRecord.missing_prerequisite_concepts,
          )
            ? lockRecord.missing_prerequisite_concepts.map((entry: unknown) => String(entry))
            : [],
          prerequisite_mastery:
            lockRecord.prerequisite_mastery &&
            typeof lockRecord.prerequisite_mastery === 'object' &&
            !Array.isArray(lockRecord.prerequisite_mastery)
              ? Object.fromEntries(
                  Object.entries(lockRecord.prerequisite_mastery).map(([key, value]) => [
                    key,
                    typeof value === 'number' ? value : Number(value || 0),
                  ]),
                )
              : {},
          bridge_recommendations: Array.isArray(lockRecord.bridge_recommendations)
            ? lockRecord.bridge_recommendations.map((entry) => asRecord(entry))
            : [],
          mastery_threshold:
            typeof lockRecord.mastery_threshold === 'number'
              ? lockRecord.mastery_threshold
              : null,
        };
        return [lessonId, normalized];
      }),
    ),
  };
};

export const normalizeLessonStudyTimeResponse = (
  payload: unknown,
  fallback: { path_id: string; lesson_id: string; seconds_spent: number },
): LessonStudyTimeResponse => {
  const response = asRecord(payload);
  return {
    path_id: String(response.path_id ?? fallback.path_id),
    lesson_id: String(response.lesson_id ?? fallback.lesson_id),
    seconds_spent:
      typeof response.seconds_spent === 'number' ? response.seconds_spent : fallback.seconds_spent,
    total_seconds:
      typeof response.total_seconds === 'number' ? response.total_seconds : fallback.seconds_spent,
    tracked_date: String(response.tracked_date ?? DEFAULT_GENERATED_AT()),
    updated_at: String(response.updated_at ?? DEFAULT_GENERATED_AT()),
  };
};

export const normalizeStudySummary = (payload: unknown): StudySummary => {
  const response = asRecord(payload);
  return {
    user_id: String(response.user_id ?? ''),
    total_seconds: typeof response.total_seconds === 'number' ? response.total_seconds : 0,
    total_hours: typeof response.total_hours === 'number' ? response.total_hours : 0,
    last_7_days: Array.isArray(response.last_7_days)
      ? response.last_7_days.map((item) => {
          const itemRecord = asRecord(item);
          return {
            date: String(itemRecord.date ?? DEFAULT_GENERATED_AT()),
            seconds: typeof itemRecord.seconds === 'number' ? itemRecord.seconds : 0,
            hours: typeof itemRecord.hours === 'number' ? itemRecord.hours : 0,
          };
        })
      : [],
    updated_at: response.updated_at ? String(response.updated_at) : null,
  };
};

export const normalizeLessonQuestionGenerationResponse = (
  payload: unknown,
  fallbackLessonId: string,
): LessonQuestionGenerationResponse => {
  const response = asRecord(payload);
  return {
    lesson_id: String(response.lesson_id ?? fallbackLessonId),
    status: String(response.status ?? ''),
    generated_count: typeof response.generated_count === 'number' ? response.generated_count : 0,
    saved_count: typeof response.saved_count === 'number' ? response.saved_count : 0,
    question_ids: Array.isArray(response.question_ids) ? response.question_ids.map(String) : [],
    chunks_used: Array.isArray(response.chunks_used) ? response.chunks_used.map(String) : [],
    insufficient_data: Boolean(response.insufficient_data),
    reused_existing: Boolean(response.reused_existing),
    existing_count: typeof response.existing_count === 'number' ? response.existing_count : 0,
    fallback_used: Boolean(response.fallback_used),
    filtered_count: typeof response.filtered_count === 'number' ? response.filtered_count : 0,
    cache_stats:
      response.cache_stats &&
      typeof response.cache_stats === 'object' &&
      !Array.isArray(response.cache_stats)
        ? (response.cache_stats as Record<string, unknown>)
        : {},
    sources:
      response.sources && typeof response.sources === 'object' && !Array.isArray(response.sources)
        ? (response.sources as Record<string, unknown>)
        : {},
    lesson_size: normalizeLessonSize(response.lesson_size),
    target_count:
      response.target_count === null || response.target_count === undefined
        ? null
        : Number(response.target_count),
    target_count_auto:
      response.target_count_auto === null || response.target_count_auto === undefined
        ? null
        : Number(response.target_count_auto),
    difficulty_mix: normalizeDistributionPlan(response.difficulty_mix),
    bloom_mix: normalizeDistributionPlan(response.bloom_mix),
    concept_coverage_rate:
      response.concept_coverage_rate === null || response.concept_coverage_rate === undefined
        ? null
        : Number(response.concept_coverage_rate),
    message: String(response.message ?? ''),
  };
};

export const normalizeAdaptiveQuizNextResponse = (
  payload: unknown,
  fallbackLessonId: string,
): AdaptiveQuizNextResponse => {
  const response = asRecord(payload);
  const nextAction = asRecord(response.next_action);
  const generationRequest = asRecord(response.generation_request);

  const normalizeDifficulty = (value: unknown): LearningLevel | null =>
    value === 'intermediate' || value === 'advanced'
      ? value
      : value === 'beginner'
        ? 'beginner'
        : null;

  return {
    lesson_id: String(response.lesson_id ?? fallbackLessonId),
    next_action: {
      type: 'adaptive_quiz_next',
      recommended_difficulty: normalizeDifficulty(nextAction.recommended_difficulty),
      recommended_bloom_levels: Array.isArray(nextAction.recommended_bloom_levels)
        ? nextAction.recommended_bloom_levels.map(normalizeBloomLevel)
        : [],
      target_chunk_ids: Array.isArray(nextAction.target_chunk_ids)
        ? nextAction.target_chunk_ids.map((item: unknown) => String(item))
        : [],
      target_concepts: Array.isArray(nextAction.target_concepts)
        ? nextAction.target_concepts.map((item: unknown) => String(item))
        : [],
      question_types: Array.isArray(nextAction.question_types)
        ? nextAction.question_types.map((item: unknown) => String(item) as LessonQuestionType)
        : [],
      policy_version:
        typeof nextAction.policy_version === 'string' ? nextAction.policy_version : null,
      policy_bucket:
        typeof nextAction.policy_bucket === 'string' ? nextAction.policy_bucket : null,
      why_this_quiz:
        typeof nextAction.why_this_quiz === 'string' ? nextAction.why_this_quiz : null,
    },
    generation_request: {
      lesson_id: String(generationRequest.lesson_id ?? fallbackLessonId),
      target_count:
        typeof generationRequest.target_count === 'number' ? generationRequest.target_count : 0,
      recommended_difficulty: normalizeDifficulty(generationRequest.recommended_difficulty),
      recommended_bloom_levels: Array.isArray(generationRequest.recommended_bloom_levels)
        ? generationRequest.recommended_bloom_levels.map(normalizeBloomLevel)
        : [],
      target_chunk_ids: Array.isArray(generationRequest.target_chunk_ids)
        ? generationRequest.target_chunk_ids.map((item: unknown) => String(item))
        : [],
      target_concepts: Array.isArray(generationRequest.target_concepts)
        ? generationRequest.target_concepts.map((item: unknown) => String(item))
        : [],
      allow_llm: Boolean(generationRequest.allow_llm),
      prefer_template: generationRequest.prefer_template !== false,
      retry_strategy:
        typeof generationRequest.retry_strategy === 'string'
          ? generationRequest.retry_strategy
          : null,
      question_types: Array.isArray(generationRequest.question_types)
        ? generationRequest.question_types.map((item: unknown) => String(item) as LessonQuestionType)
        : [],
      policy_version:
        typeof generationRequest.policy_version === 'string'
          ? generationRequest.policy_version
          : null,
      policy_bucket:
        typeof generationRequest.policy_bucket === 'string'
          ? generationRequest.policy_bucket
          : null,
      why_this_quiz:
        typeof generationRequest.why_this_quiz === 'string'
          ? generationRequest.why_this_quiz
          : null,
      generation_strategy:
        generationRequest.generation_strategy &&
        typeof generationRequest.generation_strategy === 'object' &&
        !Array.isArray(generationRequest.generation_strategy)
          ? (generationRequest.generation_strategy as Record<string, unknown>)
          : {},
      metadata:
        generationRequest.metadata &&
        typeof generationRequest.metadata === 'object' &&
        !Array.isArray(generationRequest.metadata)
          ? (generationRequest.metadata as Record<string, unknown>)
          : {},
    },
    generated: normalizeLessonQuestionGenerationResponse(response.generated, fallbackLessonId),
  };
};
