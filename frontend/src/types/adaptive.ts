export type AdaptiveAction =
  | 'continue_resource'
  | 'resume_unfinished'
  | 'review_summary'
  | 'practice_quiz'
  | 'retry_with_easier_resource'
  | 'study_worked_example'
  | 'study_misconception_fix'
  | 'reinforce_weak_concept'
  | 'move_to_next_lesson'
  | 'return_to_prerequisite'
  | 'switch_format_to_video'
  | 'switch_format_to_text'
  | 'quick_review_session';

export type AdaptivePriority = 'low' | 'medium' | 'high';
export type AdaptiveRecommendationType = 'resource' | 'chunk' | 'lesson';
export type RecommendationMode =
  | 'continue_learning'
  | 'reinforce_weaknesses'
  | 'learn_new'
  | 'quick_review';

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

export interface LearnerStateSnapshot {
  user_id: string;
  snapshot_time: string;
  mastery_by_concept: Record<string, number>;
  confidence_by_concept: Record<string, number>;
  recent_active_days: number;
  avg_session_duration: number;
  unfinished_resources: number;
  quiz_fail_streak: number;
  retry_count: number;
  learning_velocity: number;
  preferred_time_window: string;
  current_focus_concepts: string[];
  frustration_score: number;
  recovery_need_flag: boolean;
  risk_level: 'low' | 'medium' | 'high';
  last_event_type?: string | null;
  last_recommended_action?: string | null;
}
