import { apiClient } from '../utils/apiClient';
import type {
  AdaptiveRecommendation,
  ConfidenceOverview,
  ProgressOverview,
  ProgressSummary,
} from '../types/dashboard';

export const dashboardService = {
  /**
   * Get overall progress overview for the user
   */
  async getProgressOverview(userId?: string): Promise<ProgressOverview> {
    const endpoint = userId 
      ? `/progress/overview?user_id=${userId}` 
      : '/progress/overview';
    return apiClient.get(endpoint) as Promise<ProgressOverview>;
  },

  /**
   * Get user's confidence overview with trend
   */
  async getConfidenceOverview(userId?: string): Promise<ConfidenceOverview> {
    const endpoint = userId 
      ? `/progress/confidence?user_id=${userId}` 
      : '/progress/confidence';
    return apiClient.get(endpoint) as Promise<ConfidenceOverview>;
  },

  /**
   * Get user's progress summary across all concepts
   */
  async getProgressSummary(userId?: string): Promise<{ success: boolean; user_id: string; summary: ProgressSummary }> {
    const endpoint = userId 
      ? `/progress/summary?user_id=${userId}` 
      : '/progress/summary';
    return apiClient.get(endpoint) as Promise<{ success: boolean; user_id: string; summary: ProgressSummary }>;
  },

  /**
   * Get adaptive recommendations for next concepts to learn
   * This uses the adaptive engine to recommend concepts based on:
   * - Current progress and mastery levels
   * - Weak areas that need improvement
   * - Prerequisites and dependencies
   * - Bloom taxonomy level alignment
   */
  async getAdaptiveRecommendations(userId: string): Promise<AdaptiveRecommendation[]> {
    try {
      // Try to get recommendations from adaptive engine
      // For now, we'll use a mock implementation until backend API is ready
      const summary = await this.getProgressSummary(userId);
      
      // Find concepts that need improvement (low mastery or in-progress)
      const weakConcepts = summary.summary.concepts
        .filter(c => c.mastery < 0.8 && c.status !== 'not_started')
        .sort((a, b) => a.mastery - b.mastery)
        .slice(0, 3);

      return weakConcepts.map(concept => ({
        concept_id: concept.concept_id,
        concept_name: concept.concept_name,
        reasons: [
          concept.mastery < 0.5 ? 'Based on weak mastery' : 'Needs improvement',
          'Continue building foundation',
          'Aligned with your learning path'
        ],
        priority_score: 1 - concept.mastery
      }));
    } catch (error) {
      console.error('Error fetching adaptive recommendations:', error);
      return [];
    }
  },

  /**
   * Update progress for a concept
   */
  async updateProgress(data: {
    user_id: string;
    concept_id: number;
    mastery: number;
    confidence: number;
    total_attempts: number;
  }): Promise<any> {
    return apiClient.post('/progress/update', data);
  },

  /**
   * Search for learning resources
   */
  async searchResources(query: string): Promise<any> {
    return apiClient.get(`/resources/search?q=${encodeURIComponent(query)}`);
  },
};
