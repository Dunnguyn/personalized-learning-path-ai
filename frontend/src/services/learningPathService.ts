import { apiClient } from '../utils/apiClient';

export type LearningLevel = 'beginner' | 'intermediate' | 'advanced';
export type LearningPathSubjectId = 'python' | 'cpp' | 'csharp' | 'java' | 'web';
export type LessonStatus = 'not_started' | 'in_progress' | 'complete';

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

export interface LessonProgressApiResponse {
  path_id: string;
  lesson_id: string;
  status: LessonStatus;
  updated_at: string;
}

const DEFAULT_GENERATED_AT = () => new Date().toISOString();

const normalizeLessonStatus = (value: unknown): LessonStatus => {
  if (value === 'complete' || value === 'in_progress') {
    return value;
  }
  return 'not_started';
};

const normalizeLesson = (lesson: any): LearningPathLesson => ({
  lesson_id: String(lesson?.lesson_id ?? ''),
  title: String(lesson?.title ?? 'Bài học'),
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
  title: String(chapter?.title ?? 'Chương học'),
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

  async updateLessonProgress(data: {
    path_id: string;
    lesson_id: string;
    status: LessonStatus;
  }): Promise<LessonProgressApiResponse> {
    return apiClient.post('/learning-paths/lesson-progress', data) as Promise<LessonProgressApiResponse>;
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
