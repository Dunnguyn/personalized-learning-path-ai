export type RecommendationFeedbackType = 'helpful' | 'not_helpful' | 'save_for_later' | 'hide';

export interface RecommendationInteractionPayload {
  recommendation_id?: string;
  resource_id?: number;
  concept_id?: number;
  lesson_id?: string;
  goal?: string;
  level?: string;
  metadata?: Record<string, unknown>;
}

export interface RecommendationFeedbackPayload {
  recommendation_id?: string;
  resource_id?: number;
  lesson_id?: string;
  concept_id?: number;
  feedback_type: RecommendationFeedbackType;
  rating?: number;
  comment?: string;
  metadata?: Record<string, unknown>;
}
