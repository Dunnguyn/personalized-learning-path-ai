export interface LearnerCompletionMetrics {
  total_lessons: number;
  completed_lessons: number;
  in_progress_lessons: number;
  completion_rate: number;
  dropout_rate: number;
}

export interface LearnerGainMetrics {
  mastery_gain: number;
  confidence_gain: number;
  overall_mastery: number;
  overall_confidence: number;
}

export interface LearnerTimeAndStreakMetrics {
  time_spent_per_lesson: Record<string, number>;
  learning_streak_days: number;
  session_length_ms_avg: number;
}

export interface LearnerRecommendationAndQuizMetrics {
  recommendation_ctr: number;
  resource_completion_after_click: number;
  quiz_accuracy: number;
  retry_rate: number;
  quiz_attempts: number;
}

export interface LearnerAnalyticsDashboard {
  user_id: string;
  completion: LearnerCompletionMetrics;
  gain: LearnerGainMetrics;
  time_and_streak: LearnerTimeAndStreakMetrics;
  recommendation_and_quiz: LearnerRecommendationAndQuizMetrics;
}

export interface AdminDashboardMetrics {
  dau: number;
  wau: number;
  learning_path_generation_success_rate: number;
  average_study_hours_per_user: number;
  total_study_hours: number;
  user_count: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  api_error_rate: number;
  has_user_data: boolean;
  no_data_message: string | null;
  updated_at: string | null;
}

export interface AdminAverageStudyHoursMetrics {
  average_study_hours_per_user: number;
  total_study_hours: number;
  user_count: number;
}

export interface RecommendationTopResourceMetric {
  resource_id: string;
  title: string;
  shown: number;
  clicked: number;
  ctr: number;
  completion_after_click_rate: number;
}

export interface RecommendationResearchMetrics {
  window_days: number;
  shown_count: number;
  clicked_count: number;
  ctr: number;
  completion_after_recommendation: {
    completed_count: number;
    rate: number;
  };
  confidence_gain_after_recommendation: {
    avg_delta: number;
    sample_size: number;
  };
  top_resources: RecommendationTopResourceMetric[];
}

export interface LessonDropOffMetric {
  lesson_id: string;
  lesson_title: string;
  opened: number;
  completed: number;
  drop_off_rate: number;
}

export interface PathCompletionMetric {
  path_id: string;
  user_id: string;
  subject_id: string;
  completion_rate: number;
  completed_lessons: number;
  total_lessons: number;
}

export interface LearningPathResearchMetrics {
  window_days: number;
  path_count: number;
  completed_path_count: number;
  completion_rate: number;
  average_path_completion: number;
  lesson_drop_off: LessonDropOffMetric[];
  refinement_count: number;
  bridge_insertions: number;
  intervention_type_counts: Record<string, number>;
  lowest_completion_paths: PathCompletionMetric[];
}

export interface AITutorResearchMetrics {
  window_days: number;
  total_asks: number;
  retrieval_hit_ratio: number;
  average_answer_confidence: number;
  follow_up_ask_rate: number;
  follow_up_users: number;
  average_retrieval_sources: number;
  average_latency_ms: number;
  llm_call_count: number;
}

export interface AdminResearchDashboardMetrics {
  window_days: number;
  recommendation: RecommendationResearchMetrics;
  learning_path: LearningPathResearchMetrics;
  ai_tutor: AITutorResearchMetrics;
  analytics_schema_version: string;
}
