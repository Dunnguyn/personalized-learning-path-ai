import type {
  BloomLevel,
  ConceptNode,
  LearningLevel,
  LearningPath,
  LearningPathChapter,
  LearningPathDeleteResponse,
  LearningPathHistory,
  LearningPathLesson,
  LearningPathLlmStatus,
  LearningPathSubjectId,
  LessonProgressApiResponse,
  LessonQuestion,
  LessonQuestionBank,
  LessonQuestionGenerationResponse,
  LessonQuestionType,
  LessonRecommendedChunks,
  LessonStatus,
} from '../../types/learningPath';

const DEFAULT_GENERATED_AT = () => new Date().toISOString();
export type ApiRecord = Record<string, unknown>;

export const asRecord = (value: unknown): ApiRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as ApiRecord) : {};

export const normalizeLessonStatus = (value: unknown): LessonStatus => {
  if (value === 'complete' || value === 'in_progress') {
    return value;
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

const normalizeSubjectId = (value: unknown): LearningPathSubjectId | undefined => {
  if (value === 'python' || value === 'cpp' || value === 'csharp' || value === 'java' || value === 'web') {
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

const normalizeConceptNode = (item: unknown, index: number): ConceptNode => {
  const conceptRecord = asRecord(item);
  const conceptId = typeof conceptRecord.concept_id === 'number' ? conceptRecord.concept_id : 900000 + index;
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
    bloom_level: typeof conceptRecord.bloom_level === 'string' ? conceptRecord.bloom_level : undefined,
    mode: String(conceptRecord.mode ?? 'normal'),
    priority_score: typeof conceptRecord.priority_score === 'number' ? conceptRecord.priority_score : 0.5,
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
    cooldown_active: typeof llmRecord.cooldown_active === 'boolean' ? llmRecord.cooldown_active : undefined,
    reason: typeof llmRecord.reason === 'string' ? llmRecord.reason : null,
    model: typeof llmRecord.model === 'string' ? llmRecord.model : null,
  };
};

const normalizeChapter = (chapter: unknown): LearningPathChapter => {
  const chapterRecord = asRecord(chapter);

  return {
    chapter_id: String(chapterRecord.chapter_id ?? ''),
    title: String(chapterRecord.title ?? 'Chương học'),
    lessons: Array.isArray(chapterRecord.lessons) ? chapterRecord.lessons.map(normalizeLesson) : [],
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
    curriculum_source: typeof source.curriculum_source === 'string' ? source.curriculum_source : undefined,
    curriculum_notice: typeof source.curriculum_notice === 'string' ? source.curriculum_notice : null,
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
    generated_at: String(itemRecord.generated_at ?? itemRecord.created_at ?? DEFAULT_GENERATED_AT()),
    chapter_count: typeof itemRecord.chapter_count === 'number' ? itemRecord.chapter_count : undefined,
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
      itemRecord.metadata && typeof itemRecord.metadata === 'object' && !Array.isArray(itemRecord.metadata)
        ? (itemRecord.metadata as Record<string, unknown>)
        : {},
    created_at: String(itemRecord.created_at ?? DEFAULT_GENERATED_AT()),
  };
};

export const normalizeLessonQuestionBank = (payload: unknown): LessonQuestionBank => {
  const payloadRecord = asRecord(payload);

  return {
    lesson_id: String(payloadRecord.lesson_id ?? ''),
    total: typeof payloadRecord.total === 'number' ? payloadRecord.total : 0,
    questions: Array.isArray(payloadRecord.questions) ? payloadRecord.questions.map(normalizeLessonQuestion) : [],
  };
};

export const normalizeLessonRecommendedChunks = (payload: unknown): LessonRecommendedChunks => {
  const payloadRecord = asRecord(payload);

  return {
    recommendation_id: String(payloadRecord.recommendation_id ?? ''),
    subject_id: String(payloadRecord.subject_id ?? ''),
    chapter_id: String(payloadRecord.chapter_id ?? ''),
    lesson_id: String(payloadRecord.lesson_id ?? ''),
    chunk_ids: Array.isArray(payloadRecord.chunk_ids)
      ? payloadRecord.chunk_ids.map((item: unknown) => String(item))
      : [],
    resource_ids: Array.isArray(payloadRecord.resource_ids)
      ? payloadRecord.resource_ids.map((item: unknown) => String(item))
      : [],
    selection_strategy: String(payloadRecord.selection_strategy ?? ''),
    metadata:
      payloadRecord.metadata && typeof payloadRecord.metadata === 'object' && !Array.isArray(payloadRecord.metadata)
        ? (payloadRecord.metadata as Record<string, unknown>)
        : {},
    recommended_chunks: Array.isArray(payloadRecord.recommended_chunks)
        ? payloadRecord.recommended_chunks.map((item: unknown) => {
          const chunkRecord = asRecord(item);
          return {
            chunk_id: String(chunkRecord.chunk_id ?? ''),
            resource_id: String(chunkRecord.resource_id ?? ''),
            chunk_index: typeof chunkRecord.chunk_index === 'number' ? chunkRecord.chunk_index : 0,
            page_number: typeof chunkRecord.page_number === 'number' ? chunkRecord.page_number : undefined,
            score: typeof chunkRecord.score === 'number' ? chunkRecord.score : 0,
            preview: String(chunkRecord.preview ?? ''),
            resource_title: typeof chunkRecord.resource_title === 'string' ? chunkRecord.resource_title : undefined,
            resource_source: typeof chunkRecord.resource_source === 'string' ? chunkRecord.resource_source : undefined,
            resource_url: typeof chunkRecord.resource_url === 'string' ? chunkRecord.resource_url : undefined,
          };
        })
      : [],
    created_at: String(payloadRecord.created_at ?? DEFAULT_GENERATED_AT()),
  };
};

export const normalizeLearningPathDeleteResponse = (
  payload: unknown,
  fallbackPathId: string
): LearningPathDeleteResponse => {
  const response = asRecord(payload);
  return {
    path_id: String(response.path_id ?? fallbackPathId),
    deleted: Boolean(response.deleted),
    removed_lessons: typeof response.removed_lessons === 'number' ? response.removed_lessons : 0,
    removed_chapters: typeof response.removed_chapters === 'number' ? response.removed_chapters : 0,
    removed_recommendations: typeof response.removed_recommendations === 'number' ? response.removed_recommendations : 0,
    removed_questions: typeof response.removed_questions === 'number' ? response.removed_questions : 0,
  };
};

export const normalizeLessonProgressResponse = (
  payload: unknown,
  fallback: { path_id: string; lesson_id: string }
): LessonProgressApiResponse => {
  const response = asRecord(payload);
  return {
    path_id: String(response.path_id ?? fallback.path_id),
    lesson_id: String(response.lesson_id ?? fallback.lesson_id),
    status: normalizeLessonStatus(response.status),
    updated_at: String(response.updated_at ?? DEFAULT_GENERATED_AT()),
  };
};

export const normalizeLessonQuestionGenerationResponse = (
  payload: unknown,
  fallbackLessonId: string
): LessonQuestionGenerationResponse => {
  const response = asRecord(payload);
  return {
    lesson_id: String(response.lesson_id ?? fallbackLessonId),
    status: String(response.status ?? ''),
    generated_count: typeof response.generated_count === 'number' ? response.generated_count : 0,
    question_ids: Array.isArray(response.question_ids) ? response.question_ids.map(String) : [],
    chunks_used: Array.isArray(response.chunks_used) ? response.chunks_used.map(String) : [],
    insufficient_data: Boolean(response.insufficient_data),
    reused_existing: Boolean(response.reused_existing),
    existing_count: typeof response.existing_count === 'number' ? response.existing_count : 0,
    message: String(response.message ?? ''),
  };
};
