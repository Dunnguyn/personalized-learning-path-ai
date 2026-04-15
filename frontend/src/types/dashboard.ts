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

export interface RecommendedConceptApiItem {
  concept_id: number;
  concept_name: string;
  difficulty?: number;
  topic?: string;
}

export interface RecommendedConceptsResponse {
  success: boolean;
  user_id: string;
  recommended: RecommendedConceptApiItem[];
}

export interface RecommendedResourceItem {
  resource_id: number | string;
  title: string;
  source: string;
  level: string;
  topic: string;
  url?: string | null;
  reason: string;
  why_selected: string[];
  supports_concepts: string[];
  fit_level?: string | null;
  relevance_score: number;
  estimated_time?: number | null;
  primary_concepts: string[];
  quality_score?: number | null;
  expected_learning_gain?: number | null;
  retrieval_signals?: Record<string, unknown> | null;
  rank_position?: number | null;
  chunk_match_score?: number | null;
  chunk_coverage_score?: number | null;
  matched_chunk_preview?: string | null;
  matched_chunk_terms: string[];
  supporting_chunk_count?: number | null;
}

export interface PersonalizedRecommendationResponse {
  user_id: number | string;
  goal: string;
  level: string;
  mode?: string;
  recommended_resources: RecommendedResourceItem[];
  completed_concepts: number;
  total_concepts: number;
  progress_percentage: number;
  message: string;
  reranking_metadata?: Record<string, unknown> | null;
}

export interface GoalProgressConceptItem {
  concept_id: number;
  concept_name: string;
  difficulty: number;
  mastery: number;
  status: string;
}

export interface GoalProgressResponse {
  user_id: number | string;
  goal: string;
  concepts: GoalProgressConceptItem[];
  overall_mastery: number;
  message: string;
}

export interface ProgressUpdateResponse {
  success: boolean;
  message?: string;
}

export interface ResourceSearchResponse {
  results?: unknown[];
  total?: number;
  page?: number;
  size?: number;
}

export interface DashboardData {
  progressOverview: ProgressOverview;
  confidenceOverview: ConfidenceOverview;
  concepts: ConceptProgress[];
  recommendations: AdaptiveRecommendation[];
}
