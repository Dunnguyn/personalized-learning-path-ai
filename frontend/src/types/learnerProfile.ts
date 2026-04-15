export type LearnerLevel = 'beginner' | 'intermediate' | 'advanced';
export type TimeBudgetUnit = 'daily' | 'weekly';
export type PreferredResourceType = 'video' | 'pdf' | 'practice' | 'mixed';
export type LearningPace = 'light' | 'steady' | 'intensive';
export type SubjectId = 'python' | 'cpp' | 'csharp' | 'java' | 'web';

export interface TimeBudget {
  value: number;
  unit: TimeBudgetUnit;
}

export interface LearnerProfile {
  user_id: string;
  level: LearnerLevel;
  learning_goal?: string | null;
  target_role?: string | null;
  target_outcome?: string | null;
  time_budget: TimeBudget;
  preferred_resource_type: PreferredResourceType;
  learning_pace: LearningPace;
  desired_deadline?: string | null;
  prior_knowledge_by_subject: Record<string, LearnerLevel>;
  diagnostic_scores_by_subject: Record<string, Record<string, number>>;
  diagnostic_summary_by_subject: Record<
    string,
    {
      average_score?: number;
      recommended_level?: LearnerLevel;
      evaluated_at?: string;
      question_count?: number;
    }
  >;
  onboarding_status: {
    profile_completed: boolean;
    diagnostic_completed: boolean;
  };
  created_at?: string;
  updated_at?: string;
}

export interface LearnerProfileUpdatePayload {
  level?: LearnerLevel;
  learning_goal?: string;
  target_role?: string;
  target_outcome?: string;
  time_budget?: TimeBudget;
  preferred_resource_type?: PreferredResourceType;
  learning_pace?: LearningPace;
  desired_deadline?: string;
  prior_knowledge_by_subject?: Record<string, LearnerLevel>;
}

export interface DiagnosticQuestion {
  concept_key: string;
  title: string;
  prompt: string;
  difficulty?: number | null;
  subject_id: SubjectId;
}

export interface DiagnosticStartResponse {
  session_id: string;
  subject_id: SubjectId;
  questions: DiagnosticQuestion[];
  prior_knowledge_level?: LearnerLevel | string | null;
  message: string;
}

export interface DiagnosticAnswerPayload {
  concept_key: string;
  score: number;
}

export interface DiagnosticResult {
  subject_id: SubjectId;
  recommended_level: LearnerLevel;
  average_score: number;
  concept_scores: Record<string, number>;
  prior_knowledge_level?: LearnerLevel | string | null;
  completed: boolean;
  evaluated_at?: string | null;
  message: string;
}
