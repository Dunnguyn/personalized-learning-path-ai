export type LearningLevel = 'beginner' | 'intermediate' | 'advanced';
export type LearningPathSubjectId = string;
export type LessonStatus = 'not_started' | 'in_progress' | 'complete';
export type LessonQuestionType = 'multiple_choice' | 'short_answer' | 'true_false';
export type BloomLevel = 'remember' | 'understand' | 'apply' | 'analyze' | 'evaluate' | 'create';
export type LessonSize = 'small' | 'medium' | 'large';
export type LessonCompletionStatus = 'completed' | 'reinforce_required' | 'retry_required';

export interface DistributionPlan {
  ratios?: Record<string, number>;
  counts?: Record<string, number>;
  level_counts?: Record<string, number>;
  mastery?: number;
}

export interface RecommendedLessonResource {
  resource_id?: string | null;
  title?: string | null;
  type?: string | null;
  source?: string | null;
  topic?: string | null;
  level?: string | null;
  url?: string | null;
  [key: string]: unknown;
}

export interface LessonRefinementState {
  preferred_format?: string | null;
  pace?: string | null;
  bridge_required?: boolean;
  extra_practice?: boolean;
  skip_easy_content?: boolean;
  actions?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface ConceptNode {
  concept_id: number;
  concept_name: string;
  difficulty: number;
  bloom_level?: string;
  mode: string;
  priority_score: number;
  resources: Array<{ title?: string; url?: string; source?: string }>;
}

export interface LearningPathLesson {
  lesson_id: string;
  title: string;
  summary: string;
  resources: string[];
  status: LessonStatus;
  objectives?: string[];
  prerequisites?: string[];
  target_concepts?: string[];
  prerequisite_concepts?: string[];
  difficulty?: number;
  lesson_kind?: string | null;
  unlock_strategy?: string | null;
  recommended_resources?: RecommendedLessonResource[];
  adaptation_metadata?: Record<string, unknown>;
  refinement?: LessonRefinementState;
  recommended_chunk_ids?: string[];
  last_confidence?: number | null;
  confidence_updated_at?: string | null;
  is_locked?: boolean;
  reason_locked?: string;
  blocking_lesson_id?: string | null;
  blocking_concepts?: string[];
  missing_prerequisite_concepts?: string[];
  prerequisite_mastery?: Record<string, number>;
  bridge_recommendations?: Array<Record<string, unknown>>;
  mastery_threshold?: number | null;
}

export interface LearningPathChapter {
  chapter_id: string;
  title: string;
  lessons: LearningPathLesson[];
}

export interface LearningPathLlmStatus {
  provider: string;
  enabled: boolean;
  cooldown_active?: boolean;
  reason?: string | null;
  model?: string | null;
}

export interface LearningPath {
  path_id: string;
  user_id?: string;
  subject_id?: LearningPathSubjectId;
  goal: string;
  level: LearningLevel;
  generated_at: string;
  recommended_path: ConceptNode[];
  chapters: LearningPathChapter[];
  curriculum: LearningPathChapter[];
  curriculum_source?: 'ai' | 'fallback' | string;
  curriculum_notice?: string | null;
  llm_status?: LearningPathLlmStatus | null;
  message: string;
}

export interface LearningPathHistory {
  path_id: string;
  subject_id?: LearningPathSubjectId;
  goal: string;
  level: LearningLevel;
  generated_at: string;
  chapter_count?: number;
  lesson_count?: number;
}

export interface LearningPathDeleteResponse {
  path_id: string;
  deleted: boolean;
  removed_lessons: number;
  removed_chapters: number;
  removed_recommendations: number;
  removed_questions: number;
}

export interface LessonProgressApiResponse {
  path_id: string;
  lesson_id: string;
  status: LessonStatus;
  updated_at: string;
  auto_completed?: boolean;
  is_locked?: boolean;
  reason_locked?: string;
  blocking_lesson_id?: string | null;
  blocking_concepts?: string[];
  missing_prerequisite_concepts?: string[];
  prerequisite_mastery?: Record<string, number>;
  bridge_recommendations?: Array<Record<string, unknown>>;
  mastery_threshold?: number | null;
  last_confidence?: number;
  confidence_updated_at?: string;
  accuracy?: number | null;
  updated_mastery?: number | null;
  mastery_score?: number | null;
  completion_status?: LessonCompletionStatus | null;
  reinforce_required?: boolean;
  retry_required?: boolean;
  bloom_score?: number | null;
  bloom_accuracy_by_level?: Partial<Record<BloomLevel, number>>;
  concept_coverage_score?: number | null;
  concept_coverage_rate?: number | null;
  difficulty_weighted_score?: number | null;
  confidence_score?: number | null;
  weak_concepts?: string[];
  next_action?: Record<string, unknown> | null;
  adaptive_next_quiz?: Record<string, unknown> | null;
}

export interface LessonLockInfo {
  is_locked: boolean;
  reason: string | null;
  blocking_lesson_id?: string | null;
  blocking_concepts: string[];
  missing_prerequisite_concepts: string[];
  prerequisite_mastery: Record<string, number>;
  bridge_recommendations: Array<Record<string, unknown>>;
  mastery_threshold?: number | null;
}

export interface LessonLocksResponse {
  success: boolean;
  path_id: string;
  lesson_locks: Record<string, LessonLockInfo>;
}

export interface LessonStudyTimeResponse {
  path_id: string;
  lesson_id: string;
  seconds_spent: number;
  total_seconds: number;
  tracked_date: string;
  updated_at: string;
}

export interface StudySummaryDay {
  date: string;
  seconds: number;
  hours: number;
}

export interface StudySummary {
  user_id: string;
  total_seconds: number;
  total_hours: number;
  last_7_days: StudySummaryDay[];
  updated_at?: string | null;
}

export interface LessonQuestion {
  question_id: string;
  subject_id: string;
  chapter_id: string;
  lesson_id: string;
  chunk_ids: string[];
  resource_ids: string[];
  question_type: LessonQuestionType;
  question: string;
  correct_answer: string;
  distractors: string[];
  explanation: string;
  difficulty: LearningLevel;
  bloom_level: BloomLevel;
  is_ai_generated: boolean;
  llm_provider?: string | null;
  llm_model?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface LessonQuestions {
  lesson_id: string;
  total: number;
  questions: LessonQuestion[];
}

export interface LessonAnsweredQuestion {
  question_id: string;
  question: string;
  question_type: LessonQuestionType;
  user_answer: string;
  correct_answer: string;
  is_correct: boolean;
  difficulty: LearningLevel;
  bloom_level: BloomLevel;
}

export interface LessonQuestionGenerationResponse {
  lesson_id: string;
  status: string;
  generated_count: number;
  saved_count?: number;
  question_ids: string[];
  chunks_used: string[];
  insufficient_data: boolean;
  reused_existing: boolean;
  existing_count: number;
  fallback_used?: boolean;
  filtered_count?: number;
  cache_stats?: Record<string, unknown>;
  sources?: Record<string, unknown>;
  lesson_size?: LessonSize | null;
  target_count?: number | null;
  target_count_auto?: number | null;
  difficulty_mix?: DistributionPlan;
  bloom_mix?: DistributionPlan;
  concept_coverage_rate?: number | null;
  message: string;
}

export interface AdaptiveQuizNextActionPlan {
  type: 'adaptive_quiz_next';
  recommended_difficulty?: LearningLevel | null;
  recommended_bloom_levels: BloomLevel[];
  target_chunk_ids: string[];
  target_concepts: string[];
  question_types?: LessonQuestionType[];
  policy_version?: string | null;
  policy_bucket?: string | null;
  why_this_quiz?: string | null;
}

export interface AdaptiveQuizGenerationRequest {
  lesson_id: string;
  target_count: number;
  recommended_difficulty?: LearningLevel | null;
  recommended_bloom_levels: BloomLevel[];
  target_chunk_ids: string[];
  target_concepts: string[];
  allow_llm: boolean;
  prefer_template: boolean;
  retry_strategy?: string | null;
  question_types?: LessonQuestionType[];
  policy_version?: string | null;
  policy_bucket?: string | null;
  why_this_quiz?: string | null;
  generation_strategy?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface AdaptiveQuizNextResponse {
  lesson_id: string;
  next_action: AdaptiveQuizNextActionPlan;
  generation_request: AdaptiveQuizGenerationRequest;
  generated: LessonQuestionGenerationResponse;
}

export interface LessonAttemptStatistics {
  total_attempts: number;
  passed_attempts: number;
  best_confidence: number | null;
  best_bloom_score?: number | null;
  best_attempt_confidence?: number | null;
  best_attempt_bloom_score?: number | null;
  best_attempt_mastery_score?: number | null;
  avg_confidence: number | null;
  latest_confidence: number | null;
  improvement: number | null;
  success_rate: number;
  best_mastery_score?: number | null;
  latest_mastery_score?: number | null;
  best_attempt_number?: number | null;
  best_attempt_completion_status?: LessonCompletionStatus | null;
  latest_completion_status?: LessonCompletionStatus | null;
  lesson_id?: string | null;
}

export interface RecommendedChunkItem {
  chunk_id: string;
  resource_id: string;
  chunk_index: number;
  page_number?: number;
  score: number;
  preview: string;
  resource_title?: string;
  resource_source?: string;
  resource_url?: string;
  instruction_role?: string;
  covered_objectives: string[];
  covered_concepts: string[];
  estimated_read_time?: number;
  sequence_position?: number;
  questionability_score?: number;
}

export interface LessonRecommendedChunks {
  recommendation_id: string;
  subject_id: string;
  chapter_id: string;
  lesson_id: string;
  chunk_ids: string[];
  resource_ids: string[];
  selection_strategy: string;
  metadata: Record<string, unknown>;
  sequence_metadata: Record<string, unknown>;
  recommended_chunks: RecommendedChunkItem[];
  created_at: string;
}
