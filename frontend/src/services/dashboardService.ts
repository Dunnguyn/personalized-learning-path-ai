import { apiClient } from '../utils/apiClient';
import type {
  AdaptiveRecommendation,
  ConfidenceOverview,
  GoalProgressResponse,
  PersonalizedRecommendationResponse,
  ProgressOverview,
  ProgressSummary,
  ProgressUpdateResponse,
  RecommendedConceptsResponse,
  ResourceSearchResponse,
} from '../types/dashboard';
import {
  buildSummaryFallback,
  normalizeAdaptiveRecommendation,
  normalizeConfidenceOverview,
  normalizeGoalLearningProgressResponse,
  normalizePersonalizedRecommendationResponse,
  normalizeProgressOverview,
  normalizeProgressSummaryResponse,
  normalizeProgressUpdateResponse,
  normalizeRecommendedConceptsResponse,
  normalizeResourceSearchResponse,
} from './parsers/dashboardParser';

export type {
  GoalProgressConceptItem,
  GoalProgressResponse,
  PersonalizedRecommendationResponse,
  ProgressUpdateResponse,
  RecommendedConceptApiItem,
  RecommendedConceptsResponse,
  RecommendedResourceItem,
  ResourceSearchResponse,
} from '../types/dashboard';

export const dashboardService = {
  async getProgressOverview(userId?: string): Promise<ProgressOverview> {
    const endpoint = userId ? `/progress/overview?user_id=${userId}` : '/progress/overview';
    return normalizeProgressOverview(await apiClient.get(endpoint));
  },

  async getConfidenceOverview(userId?: string): Promise<ConfidenceOverview> {
    const endpoint = userId ? `/progress/confidence?user_id=${userId}` : '/progress/confidence';
    return normalizeConfidenceOverview(await apiClient.get(endpoint));
  },

  async getProgressSummary(
    userId?: string,
  ): Promise<{ success: boolean; user_id: string; summary: ProgressSummary }> {
    const endpoint = userId ? `/progress/summary?user_id=${userId}` : '/progress/summary';
    return normalizeProgressSummaryResponse(await apiClient.get(endpoint));
  },

  async getAdaptiveRecommendations(userId: string): Promise<AdaptiveRecommendation[]> {
    try {
      const response: RecommendedConceptsResponse = normalizeRecommendedConceptsResponse(
        await apiClient.get(
          `/ask/recommend-concepts?user_id=${encodeURIComponent(userId)}&limit=3`,
        ),
      );

      if (response.success && response.recommended.length > 0) {
        return response.recommended.map(normalizeAdaptiveRecommendation);
      }

      const summary = await this.getProgressSummary(userId);
      return buildSummaryFallback(summary.summary);
    } catch (error) {
      console.error('Error fetching adaptive recommendations:', error);

      try {
        const summary = await this.getProgressSummary(userId);
        return buildSummaryFallback(summary.summary);
      } catch (fallbackError) {
        console.error('Error building fallback recommendations:', fallbackError);
        return [];
      }
    }
  },

  async updateProgress(data: {
    user_id: string;
    concept_id: number;
    mastery: number;
    confidence: number;
    total_attempts: number;
  }): Promise<ProgressUpdateResponse> {
    return normalizeProgressUpdateResponse(await apiClient.post('/progress/update', data));
  },

  async searchResources(query: string): Promise<ResourceSearchResponse> {
    return normalizeResourceSearchResponse(
      await apiClient.get(`/resources/search?q=${encodeURIComponent(query)}`),
    );
  },

  async getPersonalizedResourceRecommendations(
    userId: string,
    goal: string,
    level: string,
    limit: number = 6,
    mode: 'continue_learning' | 'reinforce_weaknesses' | 'learn_new' | 'quick_review' = 'continue_learning',
  ): Promise<PersonalizedRecommendationResponse> {
    const query = new URLSearchParams({
      user_id: userId,
      goal,
      level,
      limit: String(limit),
      mode,
    });

    return normalizePersonalizedRecommendationResponse(
      await apiClient.get(`/recommendations/resources?${query.toString()}`),
    );
  },

  async getGoalLearningProgress(userId: string, goal: string): Promise<GoalProgressResponse> {
    const query = new URLSearchParams({
      user_id: userId,
      goal,
    });

    return normalizeGoalLearningProgressResponse(
      await apiClient.get(`/recommendations/progress?${query.toString()}`),
    );
  },
};
