export interface ProgressOverview {
  success: boolean;
  user_id: string;
  overall_progress_percent: number;
  progress_bar: number;
  weekly_comparison_percent: number;
  summary: ProgressSummary;
}

export interface ProgressSummary {
  user_id: string;
  total_concepts_started: number;
  total_concepts_completed: number;
  average_mastery: number;
  average_confidence: number;
  concepts: ConceptProgress[];
}

export interface ConceptProgress {
  concept_id: number;
  concept_name: string;
  mastery: number;
  confidence: number;
  total_attempts: number;
  successful_attempts: number;
  status: 'not_started' | 'in_progress' | 'proficient' | 'complete';
  last_updated: string;
  progress_percentage: number;
}

export interface ConfidenceOverview {
  success: boolean;
  user_id: string;
  confidence: number;
  level: string;
  trend: string;
  explanation: string;
}

export interface AdaptiveRecommendation {
  concept_id: number;
  concept_name: string;
  reasons: string[];
  priority_score: number;
}

export interface DashboardData {
  progressOverview: ProgressOverview;
  confidenceOverview: ConfidenceOverview;
  concepts: ConceptProgress[];
  recommendations: AdaptiveRecommendation[];
}
