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
  message: string;
}

export interface LearningPathHistory {
  path_id: string;
  user_id: string;
  goal: string;
  level: string;
  generated_at: string;
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
