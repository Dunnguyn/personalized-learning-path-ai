import { apiClient } from '../utils/apiClient';

export interface ConceptNode {
  concept_id: number;
  concept_name: string;
  difficulty: number;
  bloom_level?: string;
  mode: string;
  priority_score: number;
  resources: any[];
}

export interface LearningPath {
  path_id: string;
  user_id: string;
  goal: string;
  level: 'beginner' | 'intermediate' | 'advanced';
  generated_at: string;
  recommended_path: ConceptNode[];
  curriculum_source?: 'ai' | 'fallback' | string;
  curriculum_notice?: string | null;
  curriculum?: Array<{
    title: string;
    lessons: Array<{
      lesson_id: string;
      title: string;
      summary: string;
      resources: string[];
      status?: 'not_started' | 'in_progress' | 'complete';
      assessment?: {
        required_questions: number;
        attempted_questions: number;
        completed: boolean;
        correct_answers: number;
        min_correct_required: number;
        passed: boolean;
        score_percent: number;
        question_results: Array<{
          question_id: string;
          selected_answer: string;
          is_correct: boolean;
          correct_option: 'A' | 'B' | 'C' | 'D' | '';
          correct_answer: string;
          explanation: string;
        }>;
        questions: Array<{
          question_id: string;
          question: string;
          answer: string;
          explanation: string;
          difficulty: 'easy' | 'medium' | 'hard';
          concept: string;
          options: Array<{
            key: 'A' | 'B' | 'C' | 'D';
            text: string;
          }>;
          correct_option: 'A' | 'B' | 'C' | 'D';
        }>;
      };
    }>;
  }>;
  message: string;
}

export interface LearningPathHistory {
  path_id: string;
  user_id: string;
  goal: string;
  level: string;
  generated_at: string;
}

export interface LessonProgressApiResponse {
  path_id: string;
  lesson_id: string;
  status: 'not_started' | 'in_progress' | 'complete';
  updated_at: string;
  assessment_result?: {
    attempted_questions: number;
    correct_answers: number;
    required_questions: number;
    min_correct_required: number;
    passed: boolean;
    score_percent: number;
    restarted?: boolean;
    question_results: Array<{
      question_id: string;
      selected_answer: string;
      is_correct: boolean;
      correct_option: 'A' | 'B' | 'C' | 'D' | '';
      correct_answer: string;
      explanation: string;
    }>;
  };
}

export interface QuizOption {
  key: 'A' | 'B' | 'C' | 'D';
  text: string;
}

export interface LessonQuizQuestion {
  question_id: string;
  lesson_id: string;
  concept: string;
  relation_type: string;
  question_text: string;
  template_id: string;
  related_concepts: string[];
  options: QuizOption[];
}

export interface LessonQuizAttemptResponse {
  attempt_id: string;
  user_id: string;
  lesson_id: string;
  attempt_number: number;
  selected_question_ids: string[];
  pass_threshold_count: number;
  questions: LessonQuizQuestion[];
  created_at: string;
}

export interface LessonQuizSubmitResponse {
  attempt_id: string;
  lesson_id: string;
  score: number;
  correct_count: number;
  total_questions: number;
  attempt_number: number;
  confidence_score: number;
  pass_threshold_count: number;
  is_passed: boolean;
  submitted_at: string;
  results: Array<{
    question_id: string;
    selected_answer: string;
    correct_option: 'A' | 'B' | 'C' | 'D' | '';
    is_correct: boolean;
    answer: string;
  }>;
  can_retry: boolean;
}

export interface LessonQuestionBankSummary {
  lesson_id: string;
  chapter_id: string;
  concept_list: Array<{ id?: string; name?: string }>;
  total_questions: number;
  created_at: string;
  updated_at: string;
}

export interface LessonQuestionBankDetail extends LessonQuestionBankSummary {
  questions: Array<{
    question_id: string;
    lesson_id: string;
    concept: string;
    relation_type: string;
    bloom_level?: string;
    question_text: string;
    template_id: string;
    difficulty?: number;
    related_concepts: string[];
    options: QuizOption[];
  }>;
}

export interface LessonConfidenceResponse {
  lesson_id: string;
  confidence_score: number;
  mastery_score: number;
  best_confidence_score: number;
  correct_count: number;
  total_questions: number;
  attempt_number: number;
  is_passed: boolean;
  score: number;
  band: 'low' | 'medium' | 'high' | string;
  updated_at?: string;
}

export interface AttemptConfidenceResponse {
  attempt_id: string;
  lesson_id: string;
  confidence_score: number;
  correct_count: number;
  total_questions: number;
  attempt_number: number;
  is_passed: boolean;
  score: number;
  submitted_at?: string;
}

export const learningPathService = {
  /**
   * Generate a new personalized learning path
   */
  async generateLearningPath(data: {
    user_id: string;
    goal: string;
    level: 'beginner' | 'intermediate' | 'advanced';
  }): Promise<LearningPath> {
    return apiClient.post('/learning-path/generate', data) as Promise<LearningPath>;
  },

  /**
   * Get learning path history for user
   */
  async getLearningPathHistory(userId?: string): Promise<LearningPathHistory[]> {
    const endpoint = userId ? `/learning-path/history?user_id=${userId}` : '/learning-path/history';
    const response = await apiClient.get(endpoint) as { paths?: LearningPathHistory[] };
    return response.paths || [];
  },

  /**
   * Get learning path detail by path id
   */
  async getLearningPathById(pathId: string): Promise<any> {
    return apiClient.get(`/learning-path/${pathId}`);
  },

  /**
   * Update lesson progress status
   */
  async updateLessonProgress(data: {
    path_id: string;
    lesson_id: string;
    status: 'not_started' | 'in_progress' | 'complete';
  }): Promise<LessonProgressApiResponse> {
    return apiClient.post('/learning-path/lesson-progress', data) as Promise<LessonProgressApiResponse>;
  },

  async generateLessonQuestionBank(lessonId: string): Promise<any> {
    return apiClient.post('/lesson-question-bank/generate', {
      lesson_id: lessonId,
    }) as Promise<LessonQuestionBankDetail>;
  },

  async getLessonQuestionBank(lessonId: string): Promise<LessonQuestionBankDetail> {
    return apiClient.get(`/lesson-question-bank/${lessonId}`) as Promise<LessonQuestionBankDetail>;
  },

  async listLessonQuestionBanks(limit = 50): Promise<{ total: number; items: LessonQuestionBankSummary[] }> {
    return apiClient.get(`/lesson-question-banks?limit=${limit}`) as Promise<{ total: number; items: LessonQuestionBankSummary[] }>;
  },

  async createLessonQuizAttempt(lessonId: string): Promise<LessonQuizAttemptResponse> {
    return apiClient.post('/lesson-quiz/attempt', {
      lesson_id: lessonId,
    }) as Promise<LessonQuizAttemptResponse>;
  },

  async submitLessonQuiz(
    attemptId: string,
    userAnswers: Record<string, string>
  ): Promise<LessonQuizSubmitResponse> {
    return apiClient.post('/lesson-quiz/submit', {
      attempt_id: attemptId,
      user_answers: userAnswers,
    }) as Promise<LessonQuizSubmitResponse>;
  },

  async getLessonConfidence(lessonId: string): Promise<LessonConfidenceResponse> {
    return apiClient.get(`/progress/confidence/${lessonId}`) as Promise<LessonConfidenceResponse>;
  },

  async getAttemptConfidence(attemptId: string): Promise<AttemptConfidenceResponse> {
    return apiClient.get(`/progress/attempt-confidence/${attemptId}`) as Promise<AttemptConfidenceResponse>;
  },

  /**
   * Get all concepts for graph display
   */
  async getConcepts(): Promise<any[]> {
    try {
      const response = await apiClient.get('/concepts') as { concepts?: any[] };
      return response.concepts || [];
    } catch (error) {
      console.error('Error fetching concepts:', error);
      return [];
    }
  },

  /**
   * Get concept details by ID
   */
  async getConceptDetails(conceptId: number): Promise<any> {
    return apiClient.get(`/concepts/${conceptId}`);
  },

  /**
   * Get user's current learning progress
   */
  async getUserProgress(userId: string): Promise<any> {
    return apiClient.get(`/progress/summary?user_id=${userId}`);
  },

  /**
   * Update progress for a concept
   */
  async updateConceptProgress(data: {
    user_id: string;
    concept_id: number;
    mastery: number;
    confidence: number;
    total_attempts?: number;
  }): Promise<any> {
    return apiClient.post('/progress/update', data);
  },

  /**
   * Get resources for a specific concept
   */
  async getConceptResources(conceptId: number): Promise<any[]> {
    try {
      const response = await apiClient.get(`/resources?concept_id=${conceptId}`) as { resources?: any[] };
      return response.resources || [];
    } catch (error) {
      console.error('Error fetching concept resources:', error);
      return [];
    }
  },
};
