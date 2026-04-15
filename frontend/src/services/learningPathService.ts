import { apiClient } from '../utils/apiClient';
import type {
  BloomLevel,
  LearningLevel,
  LearningPath,
  LearningPathDeleteResponse,
  LearningPathHistory,
  LearningPathSubjectId,
  LessonLocksResponse,
  LessonProgressApiResponse,
  LessonStudyTimeResponse,
  LessonQuestions,
  LessonAnsweredQuestion,
  LessonAttemptStatistics,
  AdaptiveQuizNextResponse,
  LessonQuestionGenerationResponse,
  LessonQuestionType,
  LessonRecommendedChunks,
  LessonStatus,
  StudySummary,
} from '../types/learningPath';
import {
  asRecord,
  normalizeHistoryItem,
  normalizeLearningPath,
  normalizeLearningPathDeleteResponse,
  normalizeLessonProgressResponse,
  normalizeLessonLocksResponse,
  normalizeLessonStudyTimeResponse,
  normalizeLessonQuestions,
  normalizeLessonQuestionGenerationResponse,
  normalizeAdaptiveQuizNextResponse,
  normalizeLessonRecommendedChunks,
  normalizeLessonAttemptStatistics,
  normalizeStudySummary,
  type ApiRecord,
} from './parsers/learningPathParser';

export type {
  BloomLevel,
  ConceptNode,
  LearningLevel,
  LearningPath,
  LearningPathChapter,
  LearningPathDeleteResponse,
  LearningPathHistory,
  LearningPathLesson,
  LearningPathSubjectId,
  LessonLockInfo,
  LessonLocksResponse,
  LessonProgressApiResponse,
  LessonStudyTimeResponse,
  LessonQuestion,
  LessonAnsweredQuestion,
  LessonAttemptStatistics,
  AdaptiveQuizGenerationRequest,
  AdaptiveQuizNextActionPlan,
  AdaptiveQuizNextResponse,
  LessonQuestions,
  LessonQuestionGenerationResponse,
  LessonQuestionType,
  LessonRecommendedChunks,
  LessonStatus,
  StudySummary,
} from '../types/learningPath';

export { normalizeLearningPath } from './parsers/learningPathParser';

export const learningPathService = {
  async generateLearningPath(data: {
    user_id?: string;
    subject_id: LearningPathSubjectId;
    goal: string;
    level: LearningLevel;
  }): Promise<LearningPath> {
    const response = await apiClient.post(
      '/learning-paths/generate',
      {
        subject_id: data.subject_id,
        goal: data.goal,
        level: data.level,
      },
      { timeoutMs: null },
    );
    return normalizeLearningPath(response);
  },

  async getLearningPathHistory(): Promise<LearningPathHistory[]> {
    const response = await apiClient.get('/learning-paths/history');
    if (Array.isArray(response)) {
      return response.map(normalizeHistoryItem);
    }

    const responseRecord = asRecord(response);
    if (Array.isArray(responseRecord.paths)) {
      return responseRecord.paths.map(normalizeHistoryItem);
    }

    return [];
  },

  async getLearningPathById(pathId: string): Promise<LearningPath> {
    const response = await apiClient.get(`/learning-paths/${pathId}`);
    return normalizeLearningPath(response);
  },

  async deleteLearningPath(pathId: string): Promise<LearningPathDeleteResponse> {
    const response = await apiClient.delete(`/learning-paths/${pathId}`);
    return normalizeLearningPathDeleteResponse(response, pathId);
  },

  async updateLessonProgress(data: {
    path_id: string;
    lesson_id: string;
    status: LessonStatus;
    confidence?: number;
    questions_answered?: LessonAnsweredQuestion[];
  }): Promise<LessonProgressApiResponse> {
    const payload = {
      ...data,
      // Backend expects "completed" while frontend uses "complete".
      status: data.status === 'complete' ? 'completed' : data.status,
    };
    const response = await apiClient.post('/learning-paths/lesson-progress', payload);
    return normalizeLessonProgressResponse(response, {
      path_id: data.path_id,
      lesson_id: data.lesson_id,
    });
  },

  async getLessonLocks(pathId: string): Promise<LessonLocksResponse> {
    const response = await apiClient.get(`/learning-paths/${pathId}/lesson-locks`);
    return normalizeLessonLocksResponse(response);
  },

  async recordLessonStudyTime(data: {
    path_id: string;
    lesson_id: string;
    seconds_spent: number;
  }): Promise<LessonStudyTimeResponse> {
    const response = await apiClient.post('/learning-paths/study-time', data);
    return normalizeLessonStudyTimeResponse(response, data);
  },

  async getStudySummary(): Promise<StudySummary> {
    const response = await apiClient.get('/learning-paths/study-summary');
    return normalizeStudySummary(response);
  },

  async getLessonQuestions(lessonId: string): Promise<LessonQuestions> {
    const response = await apiClient.get(`/lessons/${lessonId}/questions`);
    return normalizeLessonQuestions(response);
  },

  async getLessonAttemptStatistics(lessonId: string): Promise<LessonAttemptStatistics> {
    const response = await apiClient.get(`/exercise_attempts/lessons/${lessonId}/statistics`);
    return normalizeLessonAttemptStatistics(response, lessonId);
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
    },
  ): Promise<LessonQuestionGenerationResponse> {
    const response = await apiClient.post(`/lessons/${lessonId}/generate-questions`, {
      ...(payload?.target_count != null ? { target_count: payload.target_count } : {}),
      question_types: payload?.question_types ?? ['multiple_choice', 'short_answer'],
      difficulty: payload?.difficulty ?? 'beginner',
      bloom_levels: payload?.bloom_levels ?? ['remember', 'understand', 'apply'],
      overwrite: payload?.overwrite ?? false,
      metadata: payload?.metadata ?? {},
    });

    return normalizeLessonQuestionGenerationResponse(response, lessonId);
  },

  async getNextAdaptiveQuiz(
    lessonId: string,
    payload: {
      path_id?: string;
      target_count?: number;
    },
  ): Promise<AdaptiveQuizNextResponse> {
    const response = await apiClient.post(`/lessons/${lessonId}/adaptive-quiz/next`, {
      path_id: payload.path_id,
      ...(payload.target_count != null ? { target_count: payload.target_count } : {}),
    });
    return normalizeAdaptiveQuizNextResponse(response, lessonId);
  },

  async debugLessonQuestionGeneration(
    lessonId: string,
    payload?: {
      target_count?: number;
      question_types?: LessonQuestionType[];
      difficulty?: LearningLevel;
      bloom_levels?: BloomLevel[];
      allow_llm?: boolean;
      metadata?: Record<string, unknown>;
    },
  ): Promise<ApiRecord> {
    return asRecord(
      await apiClient.post(`/lessons/${lessonId}/question-generation-debug`, {
        target_count: payload?.target_count ?? 4,
        question_types: payload?.question_types ?? ['multiple_choice', 'short_answer'],
        difficulty: payload?.difficulty ?? 'beginner',
        bloom_levels: payload?.bloom_levels ?? ['remember', 'understand'],
        allow_llm: payload?.allow_llm ?? true,
        metadata: payload?.metadata ?? {},
      }),
    );
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
    },
  ): Promise<LessonRecommendedChunks> {
    const response = await apiClient.post(`/lessons/${lessonId}/recommended-chunks`, {
      max_chunks: payload?.max_chunks ?? 6,
      selection_strategy: payload?.selection_strategy ?? 'local_semantic_lesson_scope_v1',
      resource_ids: payload?.resource_ids ?? [],
      metadata: payload?.metadata ?? {},
    });
    return normalizeLessonRecommendedChunks(response);
  },

  async getConcepts(): Promise<ApiRecord[]> {
    try {
      const response = asRecord(await apiClient.get('/concepts'));
      return Array.isArray(response.concepts) ? response.concepts.map(asRecord) : [];
    } catch (error) {
      console.error('Error fetching concepts:', error);
      return [];
    }
  },

  async getConceptDetails(conceptId: number): Promise<ApiRecord> {
    return asRecord(await apiClient.get(`/concepts/${conceptId}`));
  },

  async getAdminPrerequisiteGraph(subjectId?: string): Promise<ApiRecord> {
    const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
    return asRecord(await apiClient.get(`/concepts/admin-graph/prerequisite-graph${query}`));
  },

  async updateConceptPrerequisites(
    conceptId: string,
    prerequisites: string[],
  ): Promise<ApiRecord> {
    return asRecord(
      await apiClient.put(`/concepts/${encodeURIComponent(conceptId)}/prerequisites`, {
        prerequisites,
      }),
    );
  },

  async getUserProgress(userId?: string): Promise<ApiRecord> {
    const endpoint = userId ? `/progress/summary?user_id=${userId}` : '/progress/summary';
    return asRecord(await apiClient.get(endpoint));
  },

  async getConceptProgress(conceptId: number, userId?: string): Promise<ApiRecord> {
    const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
    return asRecord(await apiClient.get(`/progress/concept/${conceptId}${query}`));
  },

  async updateConceptProgress(data: {
    user_id: string;
    concept_id: number;
    mastery: number;
    confidence: number;
    total_attempts?: number;
  }): Promise<ApiRecord> {
    return asRecord(await apiClient.post('/progress/update', data));
  },

  async getConceptResources(conceptId: number): Promise<ApiRecord[]> {
    try {
      const response = asRecord(await apiClient.get(`/resources?concept_id=${conceptId}`));
      const items = Array.isArray(response.resources)
        ? response.resources
        : Array.isArray(response.results)
          ? response.results
          : [];
      return items.map(asRecord);
    } catch (error) {
      console.error('Error fetching concept resources:', error);
      return [];
    }
  },
};
