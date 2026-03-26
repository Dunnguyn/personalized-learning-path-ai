import { apiClient } from '../utils/apiClient';
import type {
  RecommendationFeedbackPayload,
  RecommendationInteractionPayload,
} from '../types/recommendation';

export const recommendationInteractionService = {
  async trackClick(payload: RecommendationInteractionPayload): Promise<{ ok: boolean }> {
    return (await apiClient.post('/recommendations/events/click', payload)) as { ok: boolean };
  },

  async trackResourceCompleted(
    payload: RecommendationInteractionPayload,
  ): Promise<{ ok: boolean }> {
    return (await apiClient.post('/recommendations/events/resource-completed', payload)) as {
      ok: boolean;
    };
  },

  async submitFeedback(payload: RecommendationFeedbackPayload): Promise<{
    ok: boolean;
    message?: string;
    feedback_type?: string;
  }> {
    return (await apiClient.post('/recommendations/feedback', payload)) as {
      ok: boolean;
      message?: string;
      feedback_type?: string;
    };
  },
};
