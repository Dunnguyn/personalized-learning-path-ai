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
