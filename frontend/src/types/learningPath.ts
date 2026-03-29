export type LearningLevel = 'beginner' | 'intermediate' | 'advanced';
export type LearningPathSubjectId = 'python' | 'cpp' | 'csharp' | 'java' | 'web';
export type LessonStatus = 'not_started' | 'in_progress' | 'complete';
export type LessonQuestionType = 'multiple_choice' | 'short_answer' | 'true_false';
export type BloomLevel = 'remember' | 'understand' | 'apply' | 'analyze' | 'evaluate' | 'create';

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
  recommended_chunk_ids?: string[];
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
  last_confidence?: number;
  confidence_updated_at?: string;
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

export interface LessonQuestionBank {
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
  question_ids: string[];
  chunks_used: string[];
  insufficient_data: boolean;
  reused_existing: boolean;
  existing_count: number;
  message: string;
}

export interface LessonAttemptStatistics {
  total_attempts: number;
  passed_attempts: number;
  best_confidence: number | null;
  avg_confidence: number | null;
  latest_confidence: number | null;
  improvement: number | null;
  success_rate: number;
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
  difficulty?: string;
  covered_objectives: string[];
  covered_concepts: string[];
  estimated_read_time?: number;
  sequence_position?: number;
  questionability_score?: number;
  fact_density_score?: number;
  concept_explicitness_score?: number;
  example_presence_score?: number;
  score_breakdown?: Record<string, number>;
  cluster_id?: string | null;
  selected_as_representative?: boolean;
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
