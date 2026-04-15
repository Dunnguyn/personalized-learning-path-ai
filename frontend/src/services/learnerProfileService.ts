import { apiClient } from '../utils/apiClient';
import type {
  DiagnosticAnswerPayload,
  DiagnosticResult,
  DiagnosticStartResponse,
  LearnerLevel,
  LearnerProfile,
  LearnerProfileUpdatePayload,
  LearningPace,
  PreferredResourceType,
  SubjectId,
  TimeBudgetUnit,
} from '../types/learnerProfile';

type ApiRecord = Record<string, unknown>;

const asRecord = (value: unknown): ApiRecord =>
  typeof value === 'object' && value !== null ? (value as ApiRecord) : {};

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && !Number.isNaN(value) ? value : fallback;

const asLearnerLevel = (value: unknown, fallback: LearnerLevel = 'beginner'): LearnerLevel => {
  if (value === 'intermediate' || value === 'advanced') {
    return value;
  }
  return fallback;
};

const asResourceType = (
  value: unknown,
  fallback: PreferredResourceType = 'mixed',
): PreferredResourceType => {
  if (value === 'video' || value === 'pdf' || value === 'practice' || value === 'mixed') {
    return value;
  }
  return fallback;
};

const asLearningPace = (value: unknown, fallback: LearningPace = 'steady'): LearningPace => {
  if (value === 'light' || value === 'intensive') {
    return value;
  }
  return fallback;
};

const asTimeBudgetUnit = (value: unknown, fallback: TimeBudgetUnit = 'weekly'): TimeBudgetUnit =>
  value === 'daily' ? 'daily' : fallback;

const normalizeLevelMap = (value: unknown): Record<string, LearnerLevel> => {
  const record = asRecord(value);
  return Object.fromEntries(
    Object.entries(record)
      .filter(([, level]) => typeof level === 'string')
      .map(([subjectId, level]) => [subjectId, asLearnerLevel(level)]),
  );
};

const normalizeDiagnosticScores = (value: unknown): Record<string, Record<string, number>> => {
  const record = asRecord(value);
  return Object.fromEntries(
    Object.entries(record).map(([subjectId, scores]) => [
      subjectId,
      Object.fromEntries(
        Object.entries(asRecord(scores))
          .filter(([, score]) => typeof score === 'number')
          .map(([conceptKey, score]) => [conceptKey, asNumber(score)]),
      ),
    ]),
  );
};

export const normalizeLearnerProfile = (value: unknown): LearnerProfile => {
  const record = asRecord(value);
  const timeBudget = asRecord(record.time_budget);
  const onboardingStatus = asRecord(record.onboarding_status);

  return {
    user_id: asString(record.user_id),
    level: asLearnerLevel(record.level),
    learning_goal: typeof record.learning_goal === 'string' ? record.learning_goal : null,
    target_role: typeof record.target_role === 'string' ? record.target_role : null,
    target_outcome: typeof record.target_outcome === 'string' ? record.target_outcome : null,
    time_budget: {
      value: Math.max(30, asNumber(timeBudget.value, 300)),
      unit: asTimeBudgetUnit(timeBudget.unit),
    },
    preferred_resource_type: asResourceType(record.preferred_resource_type),
    learning_pace: asLearningPace(record.learning_pace),
    desired_deadline: typeof record.desired_deadline === 'string' ? record.desired_deadline : null,
    prior_knowledge_by_subject: normalizeLevelMap(record.prior_knowledge_by_subject),
    diagnostic_scores_by_subject: normalizeDiagnosticScores(record.diagnostic_scores_by_subject),
    diagnostic_summary_by_subject: asRecord(record.diagnostic_summary_by_subject) as LearnerProfile['diagnostic_summary_by_subject'],
    onboarding_status: {
      profile_completed: Boolean(onboardingStatus.profile_completed),
      diagnostic_completed: Boolean(onboardingStatus.diagnostic_completed),
    },
    created_at: typeof record.created_at === 'string' ? record.created_at : undefined,
    updated_at: typeof record.updated_at === 'string' ? record.updated_at : undefined,
  };
};

const normalizeDiagnosticQuestion = (value: unknown) => {
  const record = asRecord(value);
  return {
    concept_key: asString(record.concept_key),
    title: asString(record.title),
    prompt: asString(record.prompt),
    difficulty: typeof record.difficulty === 'number' ? record.difficulty : null,
    subject_id: asString(record.subject_id, 'python') as SubjectId,
  };
};

const normalizeDiagnosticStartResponse = (value: unknown): DiagnosticStartResponse => {
  const record = asRecord(value);
  const questions = Array.isArray(record.questions)
    ? record.questions.map(normalizeDiagnosticQuestion)
    : [];

  return {
    session_id: asString(record.session_id),
    subject_id: asString(record.subject_id, 'python') as SubjectId,
    questions,
    prior_knowledge_level:
      typeof record.prior_knowledge_level === 'string' ? record.prior_knowledge_level : null,
    message: asString(record.message),
  };
};

const normalizeDiagnosticResult = (value: unknown): DiagnosticResult => {
  const record = asRecord(value);
  return {
    subject_id: asString(record.subject_id, 'python') as SubjectId,
    recommended_level: asLearnerLevel(record.recommended_level),
    average_score: asNumber(record.average_score),
    concept_scores: Object.fromEntries(
      Object.entries(asRecord(record.concept_scores))
        .filter(([, score]) => typeof score === 'number')
        .map(([conceptKey, score]) => [conceptKey, asNumber(score)]),
    ),
    prior_knowledge_level:
      typeof record.prior_knowledge_level === 'string' ? record.prior_knowledge_level : null,
    completed: Boolean(record.completed),
    evaluated_at: typeof record.evaluated_at === 'string' ? record.evaluated_at : null,
    message: asString(record.message),
  };
};

export const learnerProfileService = {
  async getMyProfile(): Promise<LearnerProfile> {
    return normalizeLearnerProfile(await apiClient.get('/learner-profile/me'));
  },

  async updateMyProfile(payload: LearnerProfileUpdatePayload): Promise<LearnerProfile> {
    return normalizeLearnerProfile(await apiClient.put('/learner-profile/me', payload));
  },

  async startDiagnostic(payload: {
    subject_id?: SubjectId;
    goal?: string;
    max_questions?: number;
  }): Promise<DiagnosticStartResponse> {
    return normalizeDiagnosticStartResponse(
      await apiClient.post('/diagnostic/start', {
        subject_id: payload.subject_id,
        goal: payload.goal,
        max_questions: payload.max_questions ?? 5,
      }),
    );
  },

  async submitDiagnostic(payload: {
    session_id: string;
    subject_id?: SubjectId;
    answers: DiagnosticAnswerPayload[];
  }): Promise<DiagnosticResult> {
    return normalizeDiagnosticResult(await apiClient.post('/diagnostic/submit', payload));
  },

  async getDiagnosticResult(subjectId?: SubjectId): Promise<DiagnosticResult> {
    const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
    return normalizeDiagnosticResult(await apiClient.get(`/diagnostic/result${query}`));
  },
};
