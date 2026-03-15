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
  };
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
    return apiClient.post('/learning-path/generate', data);
  },

  /**
   * Get learning path history for user
   */
  async getLearningPathHistory(userId?: string): Promise<LearningPathHistory[]> {
    const endpoint = userId ? `/learning-path/history?user_id=${userId}` : '/learning-path/history';
    const response = await apiClient.get(endpoint);
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
    answered_questions?: string[];
  }): Promise<LessonProgressApiResponse> {
    return apiClient.post('/learning-path/lesson-progress', data) as Promise<LessonProgressApiResponse>;
  },

  /**
   * Get all concepts for graph display
   */
  async getConcepts(): Promise<any[]> {
    try {
      const response = await apiClient.get('/concepts');
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
      const response = await apiClient.get(`/resources?concept_id=${conceptId}`);
      return response.resources || [];
    } catch (error) {
      console.error('Error fetching concept resources:', error);
      return [];
    }
  },
};
