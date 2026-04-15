export type AdaptiveAction =
  | 'resume_unfinished'
  | 'review_summary'
  | 'reinforce_weak_concept'
  | 'move_to_next_lesson';

export type AdaptiveLoopAction =
  | 'UNLOCK_NEXT_LESSON'
  | 'ASSIGN_REMEDIAL_RESOURCE'
  | 'GENERATE_REINFORCEMENT_QUIZ'
  | 'RECOMMEND_SHORT_RESOURCE'
  | 'REVIEW_WEAK_CONCEPT'
  | 'NO_ACTION';

export type AdaptivePriority = 'low' | 'medium' | 'high';
export type AdaptiveRecommendationType = 'resource' | 'chunk' | 'lesson';
export type RecommendationMode =
  | 'continue_learning'
  | 'reinforce_weaknesses'
  | 'learn_new';
export type AdaptiveRetryStrategy =
  | 'paraphrase_question'
  | 'simplify_question'
  | 'explain_then_question';
export type AdaptiveQuestionType = 'multiple_choice' | 'short_answer' | 'true_false';
export type AdaptiveDifficulty = 'beginner' | 'intermediate' | 'advanced';
export type AdaptiveBloomLevel =
  | 'remember'
  | 'understand'
  | 'apply'
  | 'analyze'
  | 'evaluate'
  | 'create';

export interface AdaptiveNextAction {
  user_id: string;
  next_best_action: AdaptiveAction;
  reason: string;
  priority: AdaptivePriority;
  recommended_mode: RecommendationMode;
  target_concepts: string[];
  lesson_id?: string | null;
  resource_id?: string | null;
  estimated_total_time?: number | null;
}

export interface AdaptiveRecommendationPayload {
  user_id: string;
  action: AdaptiveAction;
  recommendation_type: AdaptiveRecommendationType;
  recommendation_mode?: RecommendationMode | null;
  items: Array<Record<string, unknown>>;
  reason: string;
  target_concepts: string[];
  estimated_total_time: number;
  lesson_id?: string | null;
  resource_id?: string | null;
}

export interface AdaptiveResourceItem {
  resource_id?: string | null;
  lesson_id?: string | null;
  title?: string | null;
  summary?: string | null;
  type?: string | null;
  topic?: string | null;
  level?: string | null;
  url?: string | null;
  estimated_time?: number | null;
  estimated_read_time?: number | null;
  reason?: string | null;
  [key: string]: unknown;
}

export interface AdaptiveQuizPlan {
  lesson_id?: string | null;
  target_count: number;
  recommended_difficulty?: AdaptiveDifficulty | null;
  recommended_bloom_levels: AdaptiveBloomLevel[];
  target_chunk_ids: string[];
  target_concepts: string[];
  retry_strategy?: AdaptiveRetryStrategy | null;
  question_types: AdaptiveQuestionType[];
  adaptive_explanation?: string | null;
}

export interface AdaptiveNextStepResponse {
  action: AdaptiveLoopAction;
  reason: string;
  target_concepts: string[];
  resources: AdaptiveResourceItem[];
  should_generate_quiz: boolean;
  should_unlock_next: boolean;
  recommended_difficulty?: AdaptiveDifficulty | null;
  recommended_bloom_levels: AdaptiveBloomLevel[];
  retry_strategy?: AdaptiveRetryStrategy | null;
  question_types: AdaptiveQuestionType[];
  adaptive_explanation?: string | null;
  quiz?: AdaptiveQuizPlan | null;
  metadata?: Record<string, unknown>;
  snapshot: LearnerStateSnapshot;
}

export interface AdaptiveExplanationResponse {
  user_id: string;
  path_id: string;
  lesson_id: string;
  action: AdaptiveLoopAction;
  reason: string;
  target_concepts: string[];
  explanation: string;
  recommended_difficulty?: AdaptiveDifficulty | null;
  recommended_bloom_levels: AdaptiveBloomLevel[];
  retry_strategy?: AdaptiveRetryStrategy | null;
  question_types: AdaptiveQuestionType[];
  adaptive_explanation?: string | null;
  quiz?: AdaptiveQuizPlan | null;
  snapshot: LearnerStateSnapshot;
}

export interface LearnerStateSnapshot {
  user_id: string;
  snapshot_time: string;
  mastery_by_concept: Record<string, number>;
  confidence_by_concept: Record<string, number>;
  unfinished_resources: number;
  quiz_fail_streak: number;
  learning_velocity: number;
  current_focus_concepts: string[];
  needs_reinforcement: boolean;
  path_id?: string | null;
  current_lesson_id?: string | null;
  engagement_score?: number;
  quiz_accuracy?: number;
  completion_rate?: number;
  avg_session_duration?: number;
  retry_count?: number;
  fail_streak?: number;
  fatigue_score?: number;
  risk_level?: string;
  preferred_resource_type?: string | null;
  last_event_type?: string | null;
  last_recommended_action?: string | null;
}
