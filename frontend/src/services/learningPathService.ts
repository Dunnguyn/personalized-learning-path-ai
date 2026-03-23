import { apiClient } from '../utils/apiClient';

export type LearningLevel = 'beginner' | 'intermediate' | 'advanced';
export type LearningPathSubjectId = 'python' | 'cpp' | 'csharp' | 'java' | 'web';
export type LessonStatus = 'not_started' | 'in_progress' | 'complete';
export type LessonQuestionType = 'multiple_choice' | 'short_answer' | 'true_false';
export type BloomLevel = 'remember' | 'understand' | 'apply' | 'analyze' | 'evaluate' | 'create';

export interface ConceptNode {
  concept_id: number;
  concept_name: string;
  difficulty: number;
  bloom_level?: string;
  mode: string;
  priority_score: number;
  resources: Array<{ title?: string; url?: string; source?: string }>;
}

export interface LearningPathLesson {
  lesson_id: string;
  title: string;
  summary: string;
  resources: string[];
  status: LessonStatus;
  recommended_chunk_ids?: string[];
}

export interface LearningPathChapter {
  chapter_id: string;
  title: string;
  lessons: LearningPathLesson[];
}

export interface LearningPath {
  path_id: string;
  user_id?: string;
  subject_id?: LearningPathSubjectId;
  goal: string;
  level: LearningLevel;
  generated_at: string;
  recommended_path: ConceptNode[];
  chapters: LearningPathChapter[];
  curriculum: LearningPathChapter[];
  curriculum_source?: 'ai' | 'fallback' | string;
  curriculum_notice?: string | null;
  llm_status?: {
    provider: string;
    enabled: boolean;
    cooldown_active?: boolean;
    reason?: string | null;
    model?: string | null;
  } | null;
  message: string;
}

export interface LearningPathHistory {
  path_id: string;
  subject_id?: LearningPathSubjectId;
  goal: string;
  level: LearningLevel;
  generated_at: string;
  chapter_count?: number;
  lesson_count?: number;
}

export interface LearningPathDeleteResponse {
  path_id: string;
  deleted: boolean;
  removed_lessons: number;
  removed_chapters: number;
  removed_recommendations: number;
  removed_questions: number;
}

export interface LessonProgressApiResponse {
  path_id: string;
  lesson_id: string;
  status: LessonStatus;
  updated_at: string;
}

export interface LessonQuestion {
  question_id: string;
  subject_id: string;
  chapter_id: string;
  lesson_id: string;
  chunk_ids: string[];
  resource_ids: string[];
  question_type: LessonQuestionType;
  question: string;
  correct_answer: string;
  distractors: string[];
  explanation: string;
  difficulty: LearningLevel;
  bloom_level: BloomLevel;
  is_ai_generated: boolean;
  llm_provider?: string | null;
  llm_model?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface LessonQuestionBank {
  lesson_id: string;
  total: number;
  questions: LessonQuestion[];
}

export interface LessonQuestionGenerationResponse {
  lesson_id: string;
  status: string;
  generated_count: number;
  question_ids: string[];
  chunks_used: string[];
  insufficient_data: boolean;
  reused_existing: boolean;
  existing_count: number;
  message: string;
}

export interface RecommendedChunkItem {
  chunk_id: string;
  resource_id: string;
  chunk_index: number;
  score: number;
  preview: string;
}

export interface LessonRecommendedChunks {
  recommendation_id: string;
  subject_id: string;
  chapter_id: string;
  lesson_id: string;
  chunk_ids: string[];
  resource_ids: string[];
  selection_strategy: string;
  metadata: Record<string, unknown>;
  recommended_chunks: RecommendedChunkItem[];
  created_at: string;
}

const DEFAULT_GENERATED_AT = () => new Date().toISOString();

const normalizeLessonStatus = (value: unknown): LessonStatus => {
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

const normalizeLesson = (lesson: any): LearningPathLesson => ({
  lesson_id: String(lesson?.lesson_id ?? ''),
  title: String(lesson?.title ?? 'B?i h?c'),
  summary: String(lesson?.summary ?? ''),
  resources: Array.isArray(lesson?.resources)
    ? lesson.resources
        .filter((item: unknown): item is string => typeof item === 'string')
        .map((item: string) => item.trim())
        .filter(Boolean)
    : [],
  status: normalizeLessonStatus(lesson?.status),
  recommended_chunk_ids: Array.isArray(lesson?.recommended_chunk_ids)
    ? lesson.recommended_chunk_ids.map((item: unknown) => String(item))
    : [],
});

const normalizeChapter = (chapter: any): LearningPathChapter => ({
  chapter_id: String(chapter?.chapter_id ?? ''),
  title: String(chapter?.title ?? 'Ch??ng h?c'),
  lessons: Array.isArray(chapter?.lessons) ? chapter.lessons.map(normalizeLesson) : [],
});

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

export const normalizeLearningPath = (payload: any): LearningPath => {
  const source = payload?.path ?? payload ?? {};
  const chapters = Array.isArray(source?.chapters)
    ? source.chapters.map(normalizeChapter)
    : Array.isArray(source?.curriculum)
    ? source.curriculum.map(normalizeChapter)
    : [];

  const recommendedPath = Array.isArray(source?.recommended_path)
    ? (source.recommended_path as ConceptNode[])
    : deriveRecommendedPathFromChapters(chapters);

  return {
    path_id: String(source?.path_id ?? ''),
    user_id: source?.user_id ? String(source.user_id) : undefined,
    subject_id: source?.subject_id as LearningPathSubjectId | undefined,
    goal: String(source?.goal ?? ''),
    level: (source?.level ?? 'beginner') as LearningLevel,
    generated_at: String(source?.generated_at ?? source?.created_at ?? DEFAULT_GENERATED_AT()),
    recommended_path: recommendedPath,
    chapters,
    curriculum: chapters,
    curriculum_source: source?.curriculum_source,
    curriculum_notice: source?.curriculum_notice ?? null,
    llm_status: source?.llm_status ?? null,
    message: String(source?.message ?? ''),
  };
};

const normalizeHistoryItem = (item: any): LearningPathHistory => ({
  path_id: String(item?.path_id ?? ''),
  subject_id: item?.subject_id as LearningPathSubjectId | undefined,
  goal: String(item?.goal ?? ''),
  level: (item?.level ?? 'beginner') as LearningLevel,
  generated_at: String(item?.generated_at ?? item?.created_at ?? DEFAULT_GENERATED_AT()),
  chapter_count: typeof item?.chapter_count === 'number' ? item.chapter_count : undefined,
  lesson_count: typeof item?.lesson_count === 'number' ? item.lesson_count : undefined,
});

const normalizeLessonQuestion = (item: any): LessonQuestion => ({
  question_id: String(item?.question_id ?? ''),
  subject_id: String(item?.subject_id ?? ''),
  chapter_id: String(item?.chapter_id ?? ''),
  lesson_id: String(item?.lesson_id ?? ''),
  chunk_ids: Array.isArray(item?.chunk_ids) ? item.chunk_ids.map((chunkId: unknown) => String(chunkId)) : [],
  resource_ids: Array.isArray(item?.resource_ids)
    ? item.resource_ids.map((resourceId: unknown) => String(resourceId))
    : [],
  question_type: normalizeQuestionType(item?.question_type),
  question: String(item?.question ?? ''),
  correct_answer: String(item?.correct_answer ?? ''),
  distractors: Array.isArray(item?.distractors)
    ? item.distractors.map((choice: unknown) => String(choice)).filter(Boolean)
    : [],
  explanation: String(item?.explanation ?? ''),
  difficulty: (item?.difficulty ?? 'beginner') as LearningLevel,
  bloom_level: normalizeBloomLevel(item?.bloom_level),
  is_ai_generated: Boolean(item?.is_ai_generated),
  llm_provider: item?.llm_provider ? String(item.llm_provider) : null,
  llm_model: item?.llm_model ? String(item.llm_model) : null,
  metadata:
    item?.metadata && typeof item.metadata === 'object' && !Array.isArray(item.metadata) ? item.metadata : {},
  created_at: String(item?.created_at ?? DEFAULT_GENERATED_AT()),
});

const normalizeLessonQuestionBank = (payload: any): LessonQuestionBank => ({
  lesson_id: String(payload?.lesson_id ?? ''),
  total: typeof payload?.total === 'number' ? payload.total : 0,
  questions: Array.isArray(payload?.questions) ? payload.questions.map(normalizeLessonQuestion) : [],
});

const normalizeLessonRecommendedChunks = (payload: any): LessonRecommendedChunks => ({
  recommendation_id: String(payload?.recommendation_id ?? ''),
  subject_id: String(payload?.subject_id ?? ''),
  chapter_id: String(payload?.chapter_id ?? ''),
  lesson_id: String(payload?.lesson_id ?? ''),
  chunk_ids: Array.isArray(payload?.chunk_ids) ? payload.chunk_ids.map((item: unknown) => String(item)) : [],
  resource_ids: Array.isArray(payload?.resource_ids)
    ? payload.resource_ids.map((item: unknown) => String(item))
    : [],
  selection_strategy: String(payload?.selection_strategy ?? ''),
  metadata:
    payload?.metadata && typeof payload.metadata === 'object' && !Array.isArray(payload.metadata)
      ? payload.metadata
      : {},
  recommended_chunks: Array.isArray(payload?.recommended_chunks)
    ? payload.recommended_chunks.map((item: any) => ({
        chunk_id: String(item?.chunk_id ?? ''),
        resource_id: String(item?.resource_id ?? ''),
        chunk_index: typeof item?.chunk_index === 'number' ? item.chunk_index : 0,
        score: typeof item?.score === 'number' ? item.score : 0,
        preview: String(item?.preview ?? ''),
      }))
    : [],
  created_at: String(payload?.created_at ?? DEFAULT_GENERATED_AT()),
});

export const learningPathService = {
  async generateLearningPath(data: {
    user_id?: string;
    subject_id: LearningPathSubjectId;
    goal: string;
    level: LearningLevel;
  }): Promise<LearningPath> {
    const response = await apiClient.post('/learning-paths/generate', {
      subject_id: data.subject_id,
      goal: data.goal,
      level: data.level,
    });
    return normalizeLearningPath(response);
  },

  async getLearningPathHistory(): Promise<LearningPathHistory[]> {
    const response = (await apiClient.get('/learning-paths/history')) as unknown;
    if (Array.isArray(response)) {
      return response.map(normalizeHistoryItem);
    }
    if (Array.isArray((response as { paths?: any[] })?.paths)) {
      return ((response as { paths?: any[] }).paths || []).map(normalizeHistoryItem);
    }
    return [];
  },

  async getLearningPathById(pathId: string): Promise<LearningPath> {
    const response = await apiClient.get(`/learning-paths/${pathId}`);
    return normalizeLearningPath(response);
  },

  async deleteLearningPath(pathId: string): Promise<LearningPathDeleteResponse> {
    return apiClient.delete(`/learning-paths/${pathId}`) as Promise<LearningPathDeleteResponse>;
  },

  async updateLessonProgress(data: {
    path_id: string;
    lesson_id: string;
    status: LessonStatus;
  }): Promise<LessonProgressApiResponse> {
    return apiClient.post('/learning-paths/lesson-progress', data) as Promise<LessonProgressApiResponse>;
  },

  async getLessonQuestions(lessonId: string): Promise<LessonQuestionBank> {
    const response = await apiClient.get(`/lessons/${lessonId}/questions`);
    return normalizeLessonQuestionBank(response);
  },

  async generateLessonQuestions(
    lessonId: string,
    payload?: {
      target_count?: number;
      question_types?: LessonQuestionType[];
      difficulty?: LearningLevel;
      bloom_levels?: BloomLevel[];
      overwrite?: boolean;
      metadata?: Record<string, unknown>;
    }
  ): Promise<LessonQuestionGenerationResponse> {
    return apiClient.post(`/lessons/${lessonId}/generate-questions`, {
      target_count: payload?.target_count ?? 4,
      question_types: payload?.question_types ?? ['multiple_choice', 'short_answer'],
      difficulty: payload?.difficulty ?? 'beginner',
      bloom_levels: payload?.bloom_levels ?? ['remember', 'understand', 'apply'],
      overwrite: payload?.overwrite ?? false,
      metadata: payload?.metadata ?? {},
    }) as Promise<LessonQuestionGenerationResponse>;
  },

  async getLessonRecommendedChunks(lessonId: string): Promise<LessonRecommendedChunks> {
    const response = await apiClient.get(`/lessons/${lessonId}/recommended-chunks`);
    return normalizeLessonRecommendedChunks(response);
  },

  async recommendLessonChunks(
    lessonId: string,
    payload?: {
      max_chunks?: number;
      selection_strategy?: string;
      resource_ids?: string[];
      metadata?: Record<string, unknown>;
    }
  ): Promise<LessonRecommendedChunks> {
    const response = await apiClient.post(`/lessons/${lessonId}/recommended-chunks`, {
      max_chunks: payload?.max_chunks ?? 6,
      selection_strategy: payload?.selection_strategy ?? 'local_semantic_lesson_scope_v1',
      resource_ids: payload?.resource_ids ?? [],
      metadata: payload?.metadata ?? {},
    });
    return normalizeLessonRecommendedChunks(response);
  },

  async getConcepts(): Promise<any[]> {
    try {
      const response = (await apiClient.get('/concepts')) as { concepts?: any[] };
      return response.concepts || [];
    } catch (error) {
      console.error('Error fetching concepts:', error);
      return [];
    }
  },

  async getConceptDetails(conceptId: number): Promise<any> {
    return apiClient.get(`/concepts/${conceptId}`);
  },

  async getUserProgress(userId?: string): Promise<any> {
    const endpoint = userId ? `/progress/summary?user_id=${userId}` : '/progress/summary';
    return apiClient.get(endpoint);
  },

  async getConceptProgress(conceptId: number, userId?: string): Promise<any> {
    const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
    return apiClient.get(`/progress/concept/${conceptId}${query}`);
  },

  async updateConceptProgress(data: {
    user_id: string;
    concept_id: number;
    mastery: number;
    confidence: number;
    total_attempts?: number;
  }): Promise<any> {
    return apiClient.post('/progress/update', data);
  },

  async getConceptResources(conceptId: number): Promise<any[]> {
    try {
      const response = (await apiClient.get(`/resources?concept_id=${conceptId}`)) as { resources?: any[] };
      return response.resources || [];
    } catch (error) {
      console.error('Error fetching concept resources:', error);
      return [];
    }
  },
};
