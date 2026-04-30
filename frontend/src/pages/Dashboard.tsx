import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AdminDashboard from './AdminDashboard';
import DashboardLayout from '../components/layout/DashboardLayout';
import DesktopPageGrid from '../components/layout/DesktopPageGrid';
import PageHero from '../components/ui/PageHero';
import PanelHeader from '../components/ui/PanelHeader';
import SectionIntro from '../components/ui/SectionIntro';
import StatTile from '../components/ui/StatTile';
import StatusPanel from '../components/ui/StatusPanel';
import { useAuth } from '../contexts/AuthContext';
import { useSubjects } from '../hooks/useSubjects';
import { adaptiveService } from '../services/adaptiveService';
import { dashboardService } from '../services/dashboardService';
import { learningPathService } from '../services/learningPathService';
import { pathRefinementService } from '../services/pathRefinementService';
import { recommendationInteractionService } from '../services/recommendationInteractionService';
import type {
  AdaptiveNextAction,
  AdaptiveExplanationResponse,
  AdaptiveRecommendationPayload,
  LearnerStateSnapshot,
} from '../types/adaptive';
import type {
  AdaptiveRecommendation,
  ConfidenceOverview,
  ProgressOverview,
  RecommendedResourceItem,
} from '../types/dashboard';
import type { LearningPath, StudySummary } from '../types/learningPath';
import type { PathRefinementAction } from '../types/pathRefinement';
import type { RecommendationFeedbackType } from '../types/recommendation';
import {
  getSubjectLabel,
  matchSubjectByGoalPrefix,
  type SubjectOption,
} from '../utils/subjects';

type ResourceRecommendationMode =
  | 'continue_learning'
  | 'reinforce_weaknesses'
  | 'learn_new';

const RESOURCE_RECOMMENDATION_MODES: Array<{
  value: ResourceRecommendationMode;
  label: string;
}> = [
  { value: 'continue_learning', label: 'Tiếp tục học' },
  { value: 'reinforce_weaknesses', label: 'Củng cố lỗ hổng' },
  { value: 'learn_new', label: 'Mở bài mới' },
];

const getAdaptiveActionTitle = (action?: string) => {
  switch (action) {
    case 'resume_unfinished':
      return 'Tiếp tục tài liệu dang dở';
    case 'review_summary':
      return 'Đọc bản tóm tắt';
    case 'reinforce_weak_concept':
      return 'Củng cố khái niệm còn yếu';
    case 'move_to_next_lesson':
      return 'Sang bài học tiếp theo';
    default:
      return 'Bước học tiếp theo';
  }
};

const getRecommendationModeCaption = (mode: ResourceRecommendationMode) => {
  switch (mode) {
    case 'reinforce_weaknesses':
      return 'Ưu tiên lấp các lỗ hổng kiến thức trước khi mở rộng.';
    case 'learn_new':
      return 'Đề xuất tài liệu để mở khóa bước học mới tiếp theo.';
    case 'continue_learning':
    default:
      return 'Giữ nhịp học hiện tại bằng tài liệu phù hợp nhất để tiếp tục.';
  }
};

const getRecommendationModeLabel = (mode?: ResourceRecommendationMode | null) =>
  RESOURCE_RECOMMENDATION_MODES.find((item) => item.value === mode)?.label || 'Tiếp tục học';

const getPriorityLabel = (priority?: AdaptiveNextAction['priority']) => {
  switch (priority) {
    case 'high':
      return 'Ưu tiên cao';
    case 'low':
      return 'Ưu tiên thấp';
    case 'medium':
    default:
      return 'Ưu tiên vừa';
  }
};

const getAdaptiveRecommendationTypeLabel = (
  type?: AdaptiveRecommendationPayload['recommendation_type'],
) => {
  switch (type) {
    case 'lesson':
      return 'Bài học';
    case 'chunk':
      return 'Đoạn kiến thức';
    case 'resource':
    default:
      return 'Tài liệu';
  }
};

const resolveActiveAdaptiveContext = (
  paths: LearningPath[],
): { path_id: string; lesson_id: string } | null => {
  for (const path of paths) {
    for (const chapter of path.chapters || []) {
      const inProgressLesson = chapter.lessons.find((lesson) => lesson.status === 'in_progress');
      if (inProgressLesson?.lesson_id) {
        return {
          path_id: path.path_id,
          lesson_id: inProgressLesson.lesson_id,
        };
      }
    }
  }

  for (const path of paths) {
    for (const chapter of path.chapters || []) {
      const nextLesson = chapter.lessons.find((lesson) => lesson.status !== 'complete');
      if (nextLesson?.lesson_id) {
        return {
          path_id: path.path_id,
          lesson_id: nextLesson.lesson_id,
        };
      }
    }
  }

  const firstLesson = paths[0]?.chapters?.[0]?.lessons?.[0];
  if (paths[0]?.path_id && firstLesson?.lesson_id) {
    return {
      path_id: paths[0].path_id,
      lesson_id: firstLesson.lesson_id,
    };
  }

  return null;
};

const getAdaptiveItemTitle = (item: Record<string, unknown>) => {
  if (typeof item.title === 'string' && item.title.trim()) {
    return item.title;
  }
  if (typeof item.resource_title === 'string' && item.resource_title.trim()) {
    return item.resource_title;
  }
  if (typeof item.lesson_id === 'string' && item.lesson_id.trim()) {
    return `Bài học ${item.lesson_id}`;
  }
  return 'Gợi ý cá nhân hóa';
};

const getResourceSourceLabel = (source?: string | null) => {
  if (!source) {
    return 'Nguồn học';
  }

  return source
    .replace(/^https?:\/\//i, '')
    .replace(/^www\./i, '')
    .split('/')[0];
};

const formatConceptDisplay = (concept?: string | null, subjects: SubjectOption[] = []) => {
  if (!concept) {
    return null;
  }

  const normalized = concept.trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  const matchedSubject = subjects.find(
    (subject) =>
      normalized === subject.id ||
      normalized === (subject.slug || '').toLowerCase() ||
      normalized.includes(subject.id) ||
      normalized.includes(
        subject.label
          .toLowerCase()
          .normalize('NFD')
          .replace(/[\u0300-\u036f]/g, '')
          .replace(/\s+/g, '_'),
      ),
  );

  if (matchedSubject) {
    return matchedSubject.label;
  }

  if (/^[a-z](?:_[a-z])+/.test(normalized)) {
    return null;
  }

  const cleaned = concept
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned) {
    return null;
  }

  return cleaned.replace(/\b\w/g, (char) => char.toUpperCase());
};

const getLevelLabel = (level?: string | null) => {
  switch ((level || '').trim().toLowerCase()) {
    case 'beginner':
      return 'Người mới';
    case 'intermediate':
      return 'Trung cấp';
    case 'advanced':
      return 'Nâng cao';
    default:
      return level?.trim() || 'Mọi cấp độ';
  }
};

const getResourceQualityLabel = (score?: number | null) => {
  if (typeof score !== 'number' || Number.isNaN(score)) {
    return null;
  }

  const normalized = score <= 1 ? score * 100 : score;
  if (normalized >= 80) {
    return 'Chất lượng tốt';
  }
  if (normalized >= 60) {
    return 'Chất lượng ổn';
  }
  return 'Cần xem nhanh trước';
};

const getLearningGainLabel = (value?: number | null) => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null;
  }

  const normalized = value <= 1 ? Math.round(value * 100) : Math.round(value);
  return `Tăng ích dự kiến ${normalized}%`;
};

const buildRecommendationReasons = (
  resource: RecommendedResourceItem,
  subjects: SubjectOption[],
): string[] => {
  const reasons: string[] = [];

  if (resource.why_selected.length > 0) {
    reasons.push(...resource.why_selected);
  }

  if (resource.supports_concepts.length > 0) {
    reasons.push(
      `Ho tro truc tiep cho ${resource.supports_concepts
        .slice(0, 2)
        .map((concept) => formatConceptDisplay(concept, subjects) || concept)
        .join(', ')}.`,
    );
  }

  if (resource.matched_chunk_terms.length > 0) {
    reasons.push(
      `Các đoạn học liệu liên quan bao phủ ${resource.matched_chunk_terms.slice(0, 3).join(', ')}.`,
    );
  }

  if (resource.fit_level) {
    reasons.push(`Do kho phu hop voi muc ${getLevelLabel(resource.fit_level)}.`);
  }

  const gainLabel = getLearningGainLabel(resource.expected_learning_gain);
  if (gainLabel) {
    reasons.push(gainLabel);
  }

  const qualityLabel = getResourceQualityLabel(resource.quality_score);
  if (qualityLabel) {
    reasons.push(qualityLabel);
  }

  if (reasons.length === 0 && resource.reason) {
    reasons.push(resource.reason);
  }

  return Array.from(new Set(reasons)).slice(0, 4);
};

interface AdaptiveInsightMetrics {
  targetMastery: number | null;
  quizAccuracy: number | null;
}

interface DashboardAdaptiveAction extends AdaptiveNextAction {
  insightMetrics?: AdaptiveInsightMetrics | null;
}

interface AdaptiveInsightConcept {
  key: string;
  label: string;
  mastery: number | null;
  confidence: number | null;
}

const clampPercent = (value: number) => Math.max(0, Math.min(100, Math.round(value)));

const normalizePercentMetric = (value?: number | null) => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null;
  }

  return clampPercent(value <= 1 ? value * 100 : value);
};

const extractPercentFromReason = (reason: string, label: string) => {
  const match = reason.match(new RegExp(`${label}\\s*=\\s*(\\d{1,3})%`, 'i'));
  return match ? clampPercent(Number(match[1])) : null;
};

const buildAdaptiveInsightMetrics = (
  action: AdaptiveNextAction,
  explanation?: AdaptiveExplanationResponse | null,
): AdaptiveInsightMetrics | null => {
  const snapshot = explanation?.snapshot;
  const targetConceptMastery = action.target_concepts
    .map((concept) => snapshot?.mastery_by_concept?.[concept])
    .filter((value): value is number => typeof value === 'number' && !Number.isNaN(value));

  const fallbackMasteryPool = Object.values(snapshot?.mastery_by_concept || {}).filter(
    (value): value is number => typeof value === 'number' && !Number.isNaN(value),
  );

  const masterySource = targetConceptMastery.length ? targetConceptMastery : fallbackMasteryPool;
  const targetMastery =
    masterySource.length > 0
      ? normalizePercentMetric(
          masterySource.reduce((total, value) => total + value, 0) / masterySource.length,
        )
      : extractPercentFromReason(action.reason, 'target mastery');

  const quizAccuracy =
    normalizePercentMetric(snapshot?.quiz_accuracy) ??
    extractPercentFromReason(action.reason, 'accuracy');
  if (targetMastery === null && quizAccuracy === null) {
    return null;
  }

  return {
    targetMastery,
    quizAccuracy,
  };
};

const getAdaptiveInsightSummary = (action: DashboardAdaptiveAction) => {
  if (!action.insightMetrics) {
    return action.reason;
  }

  switch (action.next_best_action) {
    case 'reinforce_weak_concept':
      return 'Các chỉ số gần nhất cho thấy bạn nên vá phần kiến thức chưa chắc trước khi mở rộng nội dung mới.';
    case 'resume_unfinished':
      return 'Nhịp học đang phù hợp để quay lại phần dang dở và hoàn tất mạch học hiện tại.';
    case 'move_to_next_lesson':
      return 'Các chỉ số đang ổn định, phù hợp để tiến sang bước học kế tiếp.';
    case 'review_summary':
    default:
      return 'Một lượt ôn nhanh lúc này sẽ giúp củng cố ghi nhớ và giữ nhịp học đều hơn.';
  }
};

const getAdaptiveRiskLabel = (riskLevel?: string | null) => {
  switch ((riskLevel || '').toLowerCase()) {
    case 'high':
      return 'Rủi ro cao';
    case 'medium':
      return 'Rủi ro trung bình';
    default:
      return 'Rủi ro thấp';
  }
};

const getAdaptiveDecisionLabel = (action?: AdaptiveNextAction['next_best_action']) => {
  switch (action) {
    case 'reinforce_weak_concept':
      return 'Nên ôn lại';
    case 'move_to_next_lesson':
      return 'Nên tiếp tục';
    case 'resume_unfinished':
      return 'Nên hoàn tất phần đang dở';
    case 'review_summary':
    default:
      return 'Nên củng cố nhanh';
  }
};

const getAdaptiveModeGuidance = (action?: AdaptiveNextAction['next_best_action']) => {
  switch (action) {
    case 'move_to_next_lesson':
      return 'Có thể tăng độ khó nhẹ hoặc mở bài mới.';
    case 'reinforce_weak_concept':
      return 'Ưu tiên ôn lại và làm thêm luyện tập mục tiêu.';
    case 'resume_unfinished':
      return 'Tiếp tục đúng tài liệu đang mở để giữ nhịp học.';
    case 'review_summary':
    default:
      return 'Ôn lại nhanh trước khi quyết định bước học kế tiếp.';
  }
};

const buildWeakConcepts = (
  snapshot?: LearnerStateSnapshot | null,
  explanation?: AdaptiveExplanationResponse | null,
  subjects: SubjectOption[] = [],
): AdaptiveInsightConcept[] => {
  const focusConcepts = explanation?.target_concepts || snapshot?.current_focus_concepts || [];
  const conceptPool = new Set<string>(focusConcepts);
  Object.keys(snapshot?.mastery_by_concept || {}).forEach((concept) => {
    conceptPool.add(concept);
  });

  return Array.from(conceptPool)
    .map((concept) => {
      const masteryRaw = snapshot?.mastery_by_concept?.[concept];
      const confidenceRaw = snapshot?.confidence_by_concept?.[concept];
      const mastery =
        typeof masteryRaw === 'number' && !Number.isNaN(masteryRaw)
          ? normalizePercentMetric(masteryRaw)
          : null;
      const confidence =
        typeof confidenceRaw === 'number' && !Number.isNaN(confidenceRaw)
          ? normalizePercentMetric(confidenceRaw)
          : null;
      return {
        key: concept,
        label: formatConceptDisplay(concept, subjects) || concept,
        mastery,
        confidence,
      };
    })
    .sort((left, right) => {
      const leftScore = left.mastery ?? left.confidence ?? 100;
      const rightScore = right.mastery ?? right.confidence ?? 100;
      return leftScore - rightScore;
    })
    .filter((item) => (item.mastery ?? item.confidence ?? 100) < 75)
    .slice(0, 4);
};

const getLatestRefinementForPath = (
  actions: PathRefinementAction[],
  pathId?: string | null,
): PathRefinementAction | null =>
  actions.find((item) => !pathId || item.path_id === pathId) || null;

const calculatePathProgress = (path: LearningPath) => {
  let totalLessons = 0;
  let completedLessons = 0;

  path.curriculum?.forEach((chapter) => {
    chapter.lessons?.forEach((lesson) => {
      totalLessons += 1;
      if (lesson.status === 'complete') {
        completedLessons += 1;
      }
    });
  });

  return totalLessons > 0 ? Math.round((completedLessons / totalLessons) * 100) : 0;
};

const ESTIMATED_HOURS_PER_ATTEMPT = 0.25;
const ESTIMATED_HOURS_PER_COMPLETED_LESSON = 1.2;
const ESTIMATED_HOURS_PER_IN_PROGRESS_LESSON = 0.5;

const formatHoursShort = (hours: number) => {
  if (hours <= 0) {
    return '0 giờ';
  }

  if (hours < 1) {
    const minutes = Math.max(Math.round(hours * 60), 1);
    return `${minutes} phút`;
  }

  return `${hours.toFixed(1).replace('.', ',')} giờ`;
};

const formatHoursForColumn = (hours: number) => {
  if (hours <= 0) {
    return '0h';
  }

  if (hours < 1) {
    return `${Math.max(Math.round(hours * 60), 1)}p`;
  }

  return `${hours.toFixed(1).replace('.', ',')}h`;
};

const formatDayKey = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

const addDays = (date: Date, amount: number) => {
  const nextDate = new Date(date);
  nextDate.setDate(nextDate.getDate() + amount);
  return nextDate;
};

const getWeekdayLabel = (date: Date) => {
  const day = date.getDay();
  if (day === 0) {
    return 'CN';
  }
  return `T${day + 1}`;
};

function LearnerDashboard() {
  const { user } = useAuth();
  const { subjects } = useSubjects();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progressOverview, setProgressOverview] = useState<ProgressOverview | null>(null);
  const [confidenceOverview, setConfidenceOverview] = useState<ConfidenceOverview | null>(null);
  const [recommendations, setRecommendations] = useState<AdaptiveRecommendation[]>([]);
  const [nextBestAction, setNextBestAction] = useState<DashboardAdaptiveAction | null>(null);
  const [adaptiveRecommendation, setAdaptiveRecommendation] =
    useState<AdaptiveRecommendationPayload | null>(null);
  const [adaptiveExplanation, setAdaptiveExplanation] =
    useState<AdaptiveExplanationResponse | null>(null);
  const [refinementActions, setRefinementActions] = useState<PathRefinementAction[]>([]);
  const [personalizedResources, setPersonalizedResources] = useState<RecommendedResourceItem[]>([]);
  const [adaptiveInsightError, setAdaptiveInsightError] = useState<string | null>(null);
  const [resourceRecommendationError, setResourceRecommendationError] = useState<string | null>(
    null,
  );
  const [resourceRecommendationGoal, setResourceRecommendationGoal] = useState('');
  const [resourceRecommendationMode, setResourceRecommendationMode] =
    useState<ResourceRecommendationMode>('continue_learning');
  const [learningPaths, setLearningPaths] = useState<LearningPath[]>([]);
  const [studySummary, setStudySummary] = useState<StudySummary | null>(null);
  const [isProgressPanelOpen, setIsProgressPanelOpen] = useState(false);
  const [isSendingRecommendationFeedback, setIsSendingRecommendationFeedback] = useState(false);

  const fetchDashboardData = useCallback(async () => {
    if (!user) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const [progressData, confidenceData, recommendationsData, pathHistory, studyTimeData] =
        await Promise.all([
          dashboardService.getProgressOverview(user.user_id),
          dashboardService.getConfidenceOverview(user.user_id),
          dashboardService.getAdaptiveRecommendations(user.user_id),
          learningPathService.getLearningPathHistory(),
          learningPathService.getStudySummary(),
        ]);

      setProgressOverview(progressData);
      setConfidenceOverview(confidenceData);
      setRecommendations(recommendationsData);
      setStudySummary(studyTimeData);

      let pathsWithDetails: LearningPath[] = [];
      if (pathHistory && pathHistory.length > 0) {
        pathsWithDetails = await Promise.all(
          pathHistory.map(async (path) => {
            try {
              return await learningPathService.getLearningPathById(path.path_id);
            } catch (detailError) {
              console.error('Error fetching learning path detail:', detailError);
              return {
                path_id: path.path_id,
                subject_id: path.subject_id,
                goal: path.goal,
                level: path.level,
                generated_at: path.generated_at,
                recommended_path: [],
                chapters: [],
                curriculum: [],
                message: '',
              } as LearningPath;
            }
          }),
        );
      }
      setLearningPaths(pathsWithDetails);

      const recommendationGoal =
        user.learning_goal?.trim() ||
        pathsWithDetails[0]?.goal?.trim() ||
        pathHistory[0]?.goal?.trim() ||
        '';
      setResourceRecommendationGoal(recommendationGoal);
      setAdaptiveInsightError(null);
      setResourceRecommendationError(null);
      const adaptiveContext = resolveActiveAdaptiveContext(pathsWithDetails);
      if (adaptiveContext) {
        const [nextStepAction, nextStepRecommendation, explanationResponse, refinementResponse] =
          await Promise.all([
          adaptiveService
            .getNextBestAction({
              user_id: user.user_id,
              path_id: adaptiveContext.path_id,
              lesson_id: adaptiveContext.lesson_id,
            })
            .catch(() => null),
          adaptiveService
            .getAdaptiveRecommendation({
              user_id: user.user_id,
              path_id: adaptiveContext.path_id,
              lesson_id: adaptiveContext.lesson_id,
              goal: recommendationGoal || undefined,
              level: user.level || 'beginner',
            })
            .catch(() => null),
          adaptiveService
            .getAdaptiveExplanation({
              user_id: user.user_id,
              path_id: adaptiveContext.path_id,
              lesson_id: adaptiveContext.lesson_id,
            })
            .catch(() => null),
          pathRefinementService
            .getRefinementActions({
              user_id: user.user_id,
              path_id: adaptiveContext.path_id,
            })
            .catch(() => null),
        ]);

        if (!nextStepAction && !nextStepRecommendation && !explanationResponse) {
          setAdaptiveInsightError(
            'Không thể đồng bộ adaptive insight cho lesson hiện tại. Dashboard vẫn hiển thị dữ liệu tiến độ đang có.',
          );
        }

        setAdaptiveExplanation(explanationResponse);
        setRefinementActions(refinementResponse?.items || []);

        setNextBestAction(
          nextStepAction
            ? (() => {
                const reason =
                  explanationResponse?.adaptive_explanation ||
                  explanationResponse?.explanation ||
                  nextStepAction.reason;

                return {
                  ...nextStepAction,
                  reason,
                  insightMetrics: buildAdaptiveInsightMetrics(
                    {
                      ...nextStepAction,
                      reason,
                    },
                    explanationResponse,
                  ),
                };
              })()
            : null,
        );
        setAdaptiveRecommendation(
          nextStepRecommendation
            ? {
                ...nextStepRecommendation,
                reason:
                  explanationResponse?.adaptive_explanation ||
                  explanationResponse?.explanation ||
                  nextStepRecommendation.reason,
              }
            : null,
        );
      } else {
        const [nextActionData, adaptiveRecommendationData] = await Promise.all([
          adaptiveService.getNextBestAction({ user_id: user.user_id }).catch(() => null),
          adaptiveService
            .getAdaptiveRecommendation({
              user_id: user.user_id,
              goal: recommendationGoal || undefined,
              level: user.level || 'beginner',
            })
            .catch(() => null),
        ]);
        setNextBestAction(
          nextActionData
            ? {
                ...nextActionData,
                insightMetrics: buildAdaptiveInsightMetrics(nextActionData),
              }
            : null,
        );
        setAdaptiveRecommendation(adaptiveRecommendationData);
        setAdaptiveExplanation(null);
        setRefinementActions([]);
      }

      if (recommendationGoal) {
        try {
          const personalized = await dashboardService.getPersonalizedResourceRecommendations(
            user.user_id,
            recommendationGoal,
            user.level || 'beginner',
            6,
            resourceRecommendationMode,
          );
          setPersonalizedResources(personalized.recommended_resources);
          setResourceRecommendationError(null);
        } catch (recommendationError) {
          setPersonalizedResources([]);
          setResourceRecommendationError(
            recommendationError instanceof Error
              ? recommendationError.message
              : 'Không thể tải gợi ý tài liệu cá nhân hóa.',
          );
        }
      } else {
        setPersonalizedResources([]);
        setResourceRecommendationError(null);
      }
    } catch (err) {
      console.error('Error fetching dashboard data:', err);
      setError(err instanceof Error ? err.message : 'Không thể tải dữ liệu tổng quan');
    } finally {
      setLoading(false);
    }
  }, [resourceRecommendationMode, user]);

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    void fetchDashboardData();
  }, [fetchDashboardData, navigate, user]);

  const handleViewResources = (query: string, recommendation?: AdaptiveRecommendation) => {
    if (recommendation) {
      void recommendationInteractionService.trackClick({
        recommendation_id: `dashboard-${recommendation.concept_id}-${Date.now()}`,
        concept_id: recommendation.concept_id,
        goal: recommendation.concept_name,
        level: confidenceLevel,
        metadata: {
          source_screen: 'dashboard',
          action: 'view_resources',
        },
      });
    }
    navigate(`/resources?q=${encodeURIComponent(query)}`);
  };

  const handleViewPersonalizedResource = (resource: RecommendedResourceItem) => {
    void recommendationInteractionService.trackClick({
      recommendation_id: `dashboard-resource-${String(resource.resource_id)}`,
      resource_id: resource.resource_id,
      goal: resourceRecommendationGoal || resource.topic || resource.title,
      level: confidenceLevel,
        metadata: {
          source_screen: 'dashboard',
          action: 'view_personalized_resource',
          recommendation_mode: resourceRecommendationMode,
        },
      });

    if (resource.url) {
      window.open(resource.url, '_blank', 'noopener,noreferrer');
      return;
    }

    navigate(`/resources?q=${encodeURIComponent(resource.title || resource.topic)}`);
  };

  const handlePersonalizedResourceFeedback = async (
    resource: RecommendedResourceItem,
    feedbackType: RecommendationFeedbackType,
  ) => {
    if (isSendingRecommendationFeedback) {
      return;
    }

    try {
      setIsSendingRecommendationFeedback(true);
      await recommendationInteractionService.submitFeedback({
        recommendation_id: `dashboard-resource-${String(resource.resource_id)}`,
        resource_id: resource.resource_id,
        feedback_type: feedbackType,
        comment: resource.reason,
        metadata: {
          source_screen: 'dashboard',
          goal: resourceRecommendationGoal || resource.topic || resource.title,
          level: confidenceLevel,
          recommendation_mode: resourceRecommendationMode,
        },
      });
    } catch (feedbackError) {
      console.error('Failed to submit personalized resource feedback:', feedbackError);
    } finally {
      setIsSendingRecommendationFeedback(false);
    }
  };

  const handleOpenLearningPath = (path: LearningPath) => {
    navigate(`/learning-path/${path.path_id}`, { state: { path } });
  };

  const handleOpenAdaptiveSuggestion = () => {
    if (!adaptiveRecommendation) {
      return;
    }

    const firstItem = adaptiveRecommendation.items[0];
    const firstItemRecord =
      firstItem && typeof firstItem === 'object' ? (firstItem as Record<string, unknown>) : null;

    if (
      adaptiveRecommendation.recommendation_type === 'resource' &&
      firstItemRecord &&
      typeof firstItemRecord.url === 'string' &&
      firstItemRecord.url
    ) {
      window.open(firstItemRecord.url, '_blank', 'noopener,noreferrer');
      return;
    }

    if (adaptiveRecommendation.recommendation_type === 'resource' && firstItemRecord) {
      const query =
        (typeof firstItemRecord.title === 'string' && firstItemRecord.title) ||
        (typeof firstItemRecord.topic === 'string' && firstItemRecord.topic) ||
        resourceRecommendationGoal;
      navigate(`/resources?q=${encodeURIComponent(query || 'learning')}`);
      return;
    }

    if (adaptiveRecommendation.recommendation_type === 'lesson' && learningPaths[0]) {
      handleOpenLearningPath(learningPaths[0]);
      return;
    }

    if (adaptiveRecommendation.recommendation_type === 'chunk' && firstItemRecord) {
      const query =
        (typeof firstItemRecord.resource_title === 'string' && firstItemRecord.resource_title) ||
        (typeof firstItemRecord.preview === 'string' && firstItemRecord.preview) ||
        resourceRecommendationGoal;
      navigate(`/resources?q=${encodeURIComponent(query || 'lesson review')}`);
      return;
    }

    handleAskAIForGoal(resourceRecommendationGoal || 'learning review', confidenceLevel);
  };

  const handleAskAIForGoal = (goal: string, level?: string) => {
    const goalParam = encodeURIComponent(goal || '');
    const levelParam = level ? `&level=${encodeURIComponent(level)}` : '';
    const subjectMatch = matchSubjectByGoalPrefix(subjects, goal);
    const subjectParam = subjectMatch ? `&subject=${encodeURIComponent(subjectMatch.id)}` : '';
    navigate(`/ai-tutor?goal=${goalParam}${levelParam}${subjectParam}`);
  };

  const calculateStatistics = () => {
    let totalLessons = 0;
    let completedLessons = 0;
    let inProgressLessons = 0;

    learningPaths.forEach((path) => {
      path.curriculum?.forEach((chapter) => {
        chapter.lessons?.forEach((lesson) => {
          totalLessons += 1;
          if (lesson.status === 'complete') {
            completedLessons += 1;
          } else if (lesson.status === 'in_progress') {
            inProgressLessons += 1;
          }
        });
      });
    });

    return {
      total: totalLessons,
      completed: completedLessons,
      inProgress: inProgressLessons,
      progress: totalLessons > 0 ? Math.round((completedLessons / totalLessons) * 100) : 0,
    };
  };

  const getSubjectDisplay = (path: LearningPath) =>
    getSubjectLabel(subjects, path.subject_id, path.goal || 'Khóa học');

  if (loading) {
    return (
      <DashboardLayout>
        <div className="page-shell desktop-1440-dashboard">
          <div className="white-panel flex min-h-[420px] items-center justify-center px-6 py-10">
            <div className="max-w-[420px] text-center">
              <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f6] shadow-[0_14px_28px_rgba(140,52,81,0.12)]">
                <div className="h-7 w-7 animate-spin rounded-full border-b-2 border-[#8c3451]" />
              </div>
              <p className="text-[22px] font-semibold tracking-[-0.03em] text-[#8c3451]">
                Đang tải dashboard học tập
              </p>
              <p className="mt-3 text-[14px] leading-7 text-[#645d58]">
                Hệ thống đang tổng hợp tiến độ, đề xuất tài nguyên và nhịp học gần nhất của bạn.
              </p>
            </div>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <div className="page-shell desktop-1440-dashboard">
          <div className="white-panel flex min-h-[420px] items-center justify-center px-6 py-10">
            <div className="max-w-[520px] text-center">
              <StatusPanel
                className="rounded-[24px] px-5 py-5 shadow-none"
                tone="error"
                centered
                title="Không thể tải dashboard"
                description={error}
              />
              <div className="mt-5 flex flex-wrap justify-center gap-3">
                <button
                  onClick={fetchDashboardData}
                  className="theme-button px-6 py-3"
                >
                  Thử tải lại
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/learning-path')}
                  className="theme-button-secondary px-6 py-3"
                >
                  Mở lộ trình học
                </button>
              </div>
            </div>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  const stats = calculateStatistics();
  const weeklyComparison = progressOverview?.weekly_comparison_percent || 0;
  const confidenceLevel = confidenceOverview?.level || 'beginner';
  const topRecommendation = recommendations[0];
  const topResourceRecommendation = personalizedResources[0];
  const adaptivePrimaryItem =
    adaptiveRecommendation?.items?.[0] &&
    typeof adaptiveRecommendation.items[0] === 'object' &&
    !Array.isArray(adaptiveRecommendation.items[0])
      ? (adaptiveRecommendation.items[0] as Record<string, unknown>)
      : null;
  const adaptiveSnapshot = adaptiveExplanation?.snapshot || null;
  const weakConcepts = buildWeakConcepts(adaptiveSnapshot, adaptiveExplanation, subjects);
  const latestRefinement = getLatestRefinementForPath(
    refinementActions,
    adaptiveExplanation?.path_id || null,
  );
  const latestRefinementOp = latestRefinement?.new_path_patch?.ops?.[0] || null;
  const sideCourses = learningPaths.slice(0, 3);
  const alternativeResourceRecommendations = personalizedResources.slice(1, 5);
  const topResourceReasons = topResourceRecommendation
    ? buildRecommendationReasons(topResourceRecommendation, subjects)
    : [];
  const adaptiveExplanationDetails = Array.from(
    new Set(
      [
        adaptiveExplanation?.adaptive_explanation,
        adaptiveExplanation?.reason,
        nextBestAction?.reason,
      ].filter((item): item is string => Boolean(item?.trim())),
    ),
  ).slice(0, 3);
  const lessonNotStarted = Math.max(stats.total - stats.completed - stats.inProgress, 0);
  const progressTone =
    stats.progress >= 70 ? 'Tiến độ tốt' : stats.progress > 0 ? 'Đang tiến bộ' : 'Sẵn sàng bắt đầu';
  const progressRingValue = stats.progress > 0 ? Math.max(stats.progress, 4) : 0;
  const weeklyMomentumLabel =
    weeklyComparison > 0
      ? `+${weeklyComparison}% tuần này`
      : weeklyComparison < 0
        ? `${weeklyComparison}% tuần này`
        : 'Tuần này ổn định';
  const myCourseProgressRows = sideCourses.map((path) => {
    const progress = calculatePathProgress(path);
    return {
      path,
      progress,
      statusTone: progress > 0 ? 'active' : 'idle',
      statusLabel: progress >= 100 ? 'Hoàn thành' : progress > 0 ? 'Đang học' : 'Chưa bắt đầu',
    };
  });
  const conceptProgressItems = progressOverview?.summary.concepts || [];
  const totalAttemptCount = conceptProgressItems.reduce(
    (sum, concept) => sum + Math.max(concept.total_attempts || 0, 0),
    0,
  );
  const fallbackStudyHours =
    stats.completed * ESTIMATED_HOURS_PER_COMPLETED_LESSON +
    stats.inProgress * ESTIMATED_HOURS_PER_IN_PROGRESS_LESSON;
  const estimatedStudyHours =
    totalAttemptCount > 0 ? totalAttemptCount * ESTIMATED_HOURS_PER_ATTEMPT : fallbackStudyHours;
  const cumulativeStudyHours = studySummary?.total_hours ?? estimatedStudyHours;
  const estimatedDailyStudyHours = conceptProgressItems.reduce<Record<string, number>>(
    (accumulator, concept) => {
      const updatedAt = new Date(concept.last_updated);
      if (Number.isNaN(updatedAt.getTime())) {
        return accumulator;
      }

      const dayKey = formatDayKey(updatedAt);
      const sessionHours = Math.max(
        ESTIMATED_HOURS_PER_ATTEMPT,
        Math.min(concept.total_attempts || 1, 4) * ESTIMATED_HOURS_PER_ATTEMPT,
      );
      accumulator[dayKey] = (accumulator[dayKey] || 0) + sessionHours;
      return accumulator;
    },
    {},
  );
  const dailyStudyHours = (studySummary?.last_7_days || []).length
    ? (studySummary?.last_7_days || []).reduce<Record<string, number>>((accumulator, item) => {
        accumulator[item.date] = item.hours;
        return accumulator;
      }, {})
    : estimatedDailyStudyHours;
  const today = new Date();
  const todayKey = formatDayKey(today);
  const studyCalendarSeed = Array.from({ length: 7 }, (_, index) => {
    const date = addDays(today, index - 6);
    const dayKey = formatDayKey(date);
    return {
      key: dayKey,
      label: getWeekdayLabel(date),
      dateLabel: `${String(date.getDate()).padStart(2, '0')}/${String(date.getMonth() + 1).padStart(2, '0')}`,
      hours: dailyStudyHours[dayKey] || 0,
      intensity: 0,
      isToday: dayKey === todayKey,
    };
  });
  const weeklyStudyHours = studyCalendarSeed.reduce((sum, item) => sum + item.hours, 0);
  const maxDailyStudyHours = Math.max(...studyCalendarSeed.map((item) => item.hours), 0);
  const calendarDays = studyCalendarSeed.map((item) => ({
    ...item,
    intensity:
      item.hours > 0 && maxDailyStudyHours > 0
        ? Math.max(Math.round((item.hours / maxDailyStudyHours) * 100), 12)
        : 0,
  }));
  const currentMonthLabel = `Thg ${today.getMonth() + 1}`;
  return (
    <DashboardLayout>
      <DesktopPageGrid className="dashboard-shell-grid desktop-1440-dashboard">
        <section className="min-w-0 xl:col-span-12">
          <PageHero
            className="mb-8"
            kicker="Trung tâm điều phối học tập"
            title="Giữ nhịp học rõ ràng, không phải đoán bước tiếp theo."
            titleClassName="hero-title max-w-[760px]"
            description=""
            metrics={[
              {
                label: 'Lộ trình',
                value: learningPaths.length,
                detail: 'Đang hoạt động',
              },
              {
                label: 'Trọng tâm',
                value: personalizedResources.length,
                detail: 'Sẵn sàng mở',
              },
              {
                label: 'Nhịp học',
                value: weeklyMomentumLabel,
                detail: '7 ngày gần đây',
              },
            ]}
          />

          <section className="mb-8 grid gap-6 xl:grid-cols-12">
            <div className="white-panel xl:col-span-12 p-6">
              <PanelHeader
                kicker="Bước tiếp theo"
                title={getAdaptiveActionTitle(nextBestAction?.next_best_action)}
                aside={<span className="demo-pill">{progressTone}</span>}
              />
              <div className="mt-5 flex flex-wrap items-center gap-3">
                {nextBestAction?.estimated_total_time ? (
                  <span className="rounded-full px-3 py-1 text-[11px] font-semibold semantic-pill-blue">
                    {nextBestAction.estimated_total_time} phút
                  </span>
                ) : null}
                {nextBestAction?.priority ? (
                  <span className="rounded-full px-3 py-1 text-[11px] font-semibold semantic-pill-yellow">
                    {getPriorityLabel(nextBestAction.priority)}
                  </span>
                ) : null}
              </div>
              <div className="mt-5 rounded-[22px] border border-[#f0e2e8] bg-[#fff8fb] px-5 py-5">
                <p className="line-clamp-2 text-[28px] font-semibold tracking-[-0.05em] text-[#141217]">
                  {weakConcepts[0]?.label || topRecommendation?.concept_name || 'Tiếp tục lesson hiện tại'}
                </p>
                <p className="mt-2 text-[13px] leading-5 text-[#6f6862]">
                  Tiến độ: {stats.progress}% • {weeklyMomentumLabel}
                </p>
                <button
                  type="button"
                  onClick={() => navigate('/learning-path')}
                  className="theme-button mt-5"
                >
                  Bắt đầu
                </button>
              </div>
            </div>
          </section>

          <section className="mb-8 grid gap-6 xl:grid-cols-12">
            <div className="dashboard-progress-panel xl:col-span-8">
              <PanelHeader
                kicker="Tổng quan tiến độ"
                description="Theo dõi nhanh trạng thái hoàn thành và nhịp học trong tuần."
                descriptionClassName="max-w-[34ch] text-[13px] leading-6 text-[#6f6862]"
                aside={<span className="demo-pill">{progressTone}</span>}
              />
              <div className="dashboard-progress-hero">
                <div
                  className="dashboard-progress-ring"
                  style={{
                    background: `conic-gradient(#8c3451 0 ${progressRingValue}%, rgba(140, 52, 81, 0.14) ${progressRingValue}% 100%)`,
                  }}
                >
                  <div className="dashboard-progress-ring-core">
                    <span className="text-[30px] font-semibold leading-none tracking-[-0.05em] text-[#17141b]">
                      {stats.progress}%
                    </span>
                    <span className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                      tổng thể
                    </span>
                  </div>
                </div>
                <PanelHeader
                  kicker="Nhịp hiện tại"
                  title={progressTone}
                  titleClassName="mt-3 text-[28px] font-medium leading-[1.04] tracking-[-0.04em] text-[#131017]"
                  description={
                    stats.total > 0
                      ? `Bạn đã hoàn thành ${stats.completed}/${stats.total} bài và còn ${lessonNotStarted} bài chưa bắt đầu.`
                      : 'Chưa có bài học nào được ghi nhận trong không gian học tập hiện tại.'
                  }
                  descriptionClassName="mt-3 text-[14px] leading-6 text-[#5f5954]"
                >
                  <span className="demo-pill">{weeklyMomentumLabel}</span>
                  <span className="demo-pill">{stats.inProgress} bài đang mở</span>
                </PanelHeader>
              </div>
              <div className="dashboard-stat-grid">
                <StatTile label="Hoàn thành" value={stats.completed} />
                <StatTile label="Đang học" value={stats.inProgress} />
                <StatTile label="Chưa bắt đầu" value={lessonNotStarted} />
                <StatTile
                  label="Tuần này"
                  value={weeklyComparison > 0 ? `+${weeklyComparison}` : weeklyComparison}
                />
              </div>
              <div className="mt-4 rounded-[22px] border border-[#f0e2e8] bg-[#fff8fb] px-4 py-4 text-[13px] leading-6 text-[#6a625d]">
                {stats.inProgress > 0
                  ? `Bạn đang có ${stats.inProgress} bài học mở. Hoàn thành nốt chúng sẽ cải thiện độ chính xác của gợi ý tiếp theo.`
                  : 'Bạn đang ở trạng thái khá sạch. Đây là thời điểm tốt để mở bài mới hoặc đào sâu phần còn yếu.'}
              </div>
            </div>

            <div className="soft-panel rounded-[32px] p-8 xl:col-span-4 xl:p-9">
              <div className="mb-8 flex items-center justify-between">
                <button
                  type="button"
                  aria-label="Mở tiến độ"
                  onClick={() => setIsProgressPanelOpen((value) => !value)}
                  className={`relative flex h-12 w-12 items-center justify-center rounded-full bg-white/90 text-[#8c3451] shadow-[0_10px_24px_rgba(140,52,81,0.08)] transition hover:-translate-y-0.5 ${
                    isProgressPanelOpen ? 'ring-2 ring-[#8c3451]/20' : ''
                  }`}
                >
                  <svg
                    viewBox="0 0 20 20"
                    className="h-5 w-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M10 3.5a3 3 0 0 0-3 3v1.2c0 .7-.2 1.4-.6 2L5.2 12a1 1 0 0 0 .9 1.5h7.8a1 1 0 0 0 .9-1.5l-1.2-2.3a4 4 0 0 1-.6-2V6.5a3 3 0 0 0-3-3Z" />
                    <path d="M8.4 15a1.8 1.8 0 0 0 3.2 0" />
                  </svg>
                  <span className="absolute -right-1 -top-1 inline-flex min-w-[22px] items-center justify-center rounded-full bg-[#8c3451] px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    {stats.progress}%
                  </span>
                </button>
                <button
                  type="button"
                  aria-label="Mở cài đặt"
                  onClick={() => navigate('/settings')}
                  className="flex h-12 w-12 items-center justify-center rounded-full bg-white/90 text-[#8c3451] shadow-[0_10px_24px_rgba(140,52,81,0.08)] transition hover:-translate-y-0.5"
                >
                  <svg
                    viewBox="0 0 20 20"
                    className="h-5 w-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <circle cx="10" cy="10" r="2.3" />
                    <path d="M16 10a1.6 1.6 0 0 0 .1.5l1 1.5-1.4 2.4-1.8-.2a1.6 1.6 0 0 0-.8.5l-.8 1.6H8.7l-.8-1.6a1.6 1.6 0 0 0-.8-.5l-1.8.2L3.9 12l1-1.5A1.6 1.6 0 0 0 5 10a1.6 1.6 0 0 0-.1-.5l-1-1.5 1.4-2.4 1.8.2a1.6 1.6 0 0 0 .8-.5l.8-1.6h2.6l.8 1.6a1.6 1.6 0 0 0 .8.5l1.8-.2L17.1 8l-1 1.5c-.1.2-.1.3-.1.5Z" />
                  </svg>
                </button>
              </div>

              {isProgressPanelOpen && (
                <div className="white-panel ui-fade-in mb-6 rounded-[26px] p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                        Tiến độ
                      </p>
                      <p className="mt-2 text-[30px] font-semibold tracking-[-0.05em] text-[#141217]">
                        {stats.progress}%
                      </p>
                      <p className="mt-2 text-[13px] leading-5 text-[#6f6862]">
                        {stats.completed}/{stats.total || 0} bài hoàn thành
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => navigate('/learning-path')}
                      className="theme-button-secondary rounded-full px-4 py-2 text-[12px]"
                    >
                      Xem lộ trình
                    </button>
                  </div>
                  <div className="mt-4 h-2 rounded-full bg-[#f4e7ed]">
                    <div
                      className="h-2 rounded-full bg-[#8c3451]"
                      style={{ width: `${Math.max(stats.progress, 4)}%` }}
                    />
                  </div>
                  {myCourseProgressRows.length > 0 ? (
                    <div className="mt-4 space-y-2">
                      {myCourseProgressRows.slice(0, 2).map(({ path, progress }) => (
                        <button
                          key={`bell-progress-${path.path_id}`}
                          onClick={() => handleOpenLearningPath(path)}
                          className="flex w-full items-center justify-between rounded-[14px] bg-[#fff8fb] px-3 py-3 text-left"
                        >
                          <span className="line-clamp-1 text-[13px] font-medium text-[#17141b]">
                            {getSubjectDisplay(path)}
                          </span>
                          <span className="text-[12px] font-semibold text-[#8c3451]">{progress}%</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}

              <div className="mb-8 text-center">
                <div className="mx-auto mb-5 flex h-28 w-28 items-center justify-center rounded-full bg-[#efbfd0] text-[42px] font-semibold text-[#8c3451] shadow-[inset_0_1px_0_rgba(255,255,255,0.45)]">
                  {(user?.name || 'U').slice(0, 1)}
                </div>
                <h2 className="text-[24px] font-medium tracking-[-0.03em] text-[#121019]">
                  {user?.name || 'Người học'}
                </h2>
              </div>

              <div className="white-panel rounded-[34px] p-7 xl:p-8">
                <div className="mb-5 flex items-center justify-between gap-4">
                  <div>
                    <p className="text-[15px] text-[#6f6862]">Hoạt động</p>
                    <p className="mt-2 text-[16px] text-[#6f6862]">
                      {formatHoursShort(cumulativeStudyHours)}
                    </p>
                  </div>
                  <button className="theme-button-secondary rounded-full px-5 py-2.5 text-[13px]">
                    {currentMonthLabel}
                  </button>
                </div>

                <div className="mt-5 flex items-center justify-between text-[13px] text-[#6f6862]">
                  <span>7 ngày học gần đây</span>
                  <span className="whitespace-nowrap">{formatHoursShort(weeklyStudyHours)}</span>
                </div>

                <div className="mt-6 flex h-[236px] items-end justify-between gap-3">
                  {calendarDays.map((day) => (
                    <div key={day.key} className="flex min-w-0 flex-1 flex-col items-center gap-2.5">
                      <div
                        className={`flex h-[176px] w-full items-end rounded-[24px] border p-1.5 ${
                          day.isToday
                            ? 'border-[#8c3451]/20 bg-[#fff6fa]'
                            : 'border-[#ece4ff] bg-[#f7f2ff]'
                        }`}
                      >
                        <div
                          className="w-full rounded-[18px] bg-gradient-to-b from-[#f3b9c8] via-[#cfc8ff] to-[#9de3b9]"
                          style={{ height: `${day.intensity}%` }}
                        />
                      </div>
                      <div className="text-center">
                        <p
                          className={`text-[12px] font-semibold ${day.isToday ? 'text-[#8c3451]' : 'text-[#524b46]'}`}
                        >
                          {day.label}
                        </p>
                        <p className="text-[12px] text-[#7b746f]">{day.dateLabel}</p>
                        <p className="whitespace-nowrap text-[12px] text-[#8c3451]">
                          {formatHoursForColumn(day.hours)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="hidden white-panel mb-8 overflow-hidden p-6">
            <PanelHeader
              kicker="Tín hiệu adaptive"
              title="Hệ thống đang tự điều chỉnh theo trạng thái học của bạn"
              aside={
                adaptiveSnapshot?.risk_level ? (
                  <span className="demo-pill">{getAdaptiveRiskLabel(adaptiveSnapshot.risk_level)}</span>
                ) : null
              }
            />

            {adaptiveInsightError ? (
              <StatusPanel
                className="mt-5 rounded-[18px] px-4 py-4 shadow-none"
                tone="info"
                title="Tín hiệu adaptive tạm thiếu dữ liệu"
                description={adaptiveInsightError}
                actions={
                  <button
                    type="button"
                    onClick={() => navigate('/learning-path')}
                    className="theme-button-secondary px-5 py-3 text-[13px]"
                  >
                    Mở lộ trình đang học
                  </button>
                }
              />
            ) : null}

            <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
              <div className="space-y-4">
                <div className="rounded-[24px] border border-[#f1dbe4] bg-[#fff8fb] p-5">
                  <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8f6075]">
                    Vì sao hệ thống đề xuất bước tiếp theo
                  </p>
                  <h3 className="mt-3 text-[26px] font-medium tracking-[-0.04em] text-[#23131c]">
                    {getAdaptiveActionTitle(nextBestAction?.next_best_action)}
                  </h3>
                  <p className="mt-3 text-[14px] leading-7 text-[#5f5954]">
                    {adaptiveExplanation?.explanation ||
                      adaptiveRecommendation?.reason ||
                      nextBestAction?.reason ||
                      'Hãy tiếp tục học để hệ thống có đủ tín hiệu cập nhật vòng thích nghi.'}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <span className="demo-pill">
                      {getAdaptiveDecisionLabel(nextBestAction?.next_best_action)}
                    </span>
                    {adaptiveSnapshot?.risk_level ? (
                      <span className="demo-pill">
                        {getAdaptiveRiskLabel(adaptiveSnapshot.risk_level)}
                      </span>
                    ) : null}
                    {adaptiveRecommendation?.recommendation_type ? (
                      <span className="demo-pill">
                        {getAdaptiveRecommendationTypeLabel(adaptiveRecommendation.recommendation_type)}
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-[24px] border border-[#f1dbe4] bg-white p-5">
                    <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8f6075]">
                      Bạn đang yếu ở concept nào
                    </p>
                    <div className="mt-4 space-y-3">
                      {weakConcepts.length > 0 ? (
                        weakConcepts.map((concept) => (
                          <div
                            key={concept.key}
                            className="rounded-[18px] border border-[#f3e4eb] bg-[#fffafc] px-4 py-3"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-[14px] font-semibold text-[#1d1419]">
                                {concept.label}
                              </p>
                              <span className="text-[12px] font-medium text-[#8c3451]">
                                {concept.mastery ?? concept.confidence ?? '--'}%
                              </span>
                            </div>
                            <p className="mt-2 text-[12px] leading-5 text-[#706963]">
                              Mức vững {concept.mastery ?? '--'}% · Tự tin {concept.confidence ?? '--'}%
                            </p>
                          </div>
                        ))
                      ) : (
                        <p className="text-[14px] leading-6 text-[#706963]">
                          Chưa có concept yếu nổi bật. Đây là lúc phù hợp để tiếp tục hoặc tăng độ khó nhẹ.
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-[#f1dbe4] bg-white p-5">
                    <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8f6075]">
                      Nên làm gì tiếp theo
                    </p>
                    <div className="mt-4 space-y-3">
                      <div className="rounded-[18px] bg-[#fff6fa] px-4 py-4">
                        <p className="text-[15px] font-semibold text-[#1d1419]">
                          {getAdaptiveDecisionLabel(nextBestAction?.next_best_action)}
                        </p>
                        <p className="mt-2 text-[13px] leading-6 text-[#6b625d]">
                          {getAdaptiveModeGuidance(nextBestAction?.next_best_action)}
                        </p>
                        {adaptiveExplanationDetails.length > 0 ? (
                          <div className="mt-3 space-y-2">
                            {adaptiveExplanationDetails.slice(0, 2).map((detail, index) => (
                              <p
                                key={`adaptive-detail-${index}`}
                                className="text-[12px] leading-5 text-[#8f6075]"
                              >
                                {detail}
                              </p>
                            ))}
                          </div>
                        ) : null}
                      </div>
                      <div className="rounded-[18px] border border-[#f3e4eb] bg-white px-4 py-4">
                        <p className="text-[13px] font-semibold text-[#8c3451]">
                          Lộ trình đã được điều chỉnh thế nào
                        </p>
                        <p className="mt-2 text-[13px] leading-6 text-[#6b625d]">
                          {latestRefinementOp?.effects?.[0]?.label ||
                            'Chưa có refinement mới được ghi lại cho path đang hoạt động.'}
                        </p>
                        {latestRefinementOp?.recommendations?.[0]?.label ? (
                          <p className="mt-2 text-[12px] leading-5 text-[#8f6075]">
                            Khuyến nghị: {latestRefinementOp.recommendations[0].label}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-[24px] border border-[#f1dbe4] bg-[linear-gradient(180deg,#fffafd_0%,#fff5f9_100%)] p-5">
                <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8f6075]">
                  Dòng thời gian adaptive
                </p>
                <div className="mt-4 space-y-3">
                  {refinementActions.length > 0 ? (
                    refinementActions.slice(0, 3).map((action) => {
                      const op = action.new_path_patch?.ops?.[0];
                      return (
                        <div
                          key={action.action_id}
                          className="rounded-[18px] border border-[#f3dfe7] bg-white px-4 py-4"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <p className="text-[14px] font-semibold text-[#1d1419]">
                              {action.summary?.headline || 'Điều chỉnh thích nghi'}
                            </p>
                            <span className="demo-pill">
                              {action.created_at
                                ? new Intl.DateTimeFormat('vi-VN', {
                                    day: '2-digit',
                                    month: '2-digit',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  }).format(new Date(action.created_at))
                                : 'vừa xong'}
                            </span>
                          </div>
                          <p className="mt-2 text-[13px] leading-6 text-[#5f5954]">
                            Nguyên nhân: {op?.reasons?.[0]?.trigger_reason || action.trigger_reason || 'điều chỉnh thích nghi'}
                          </p>
                          <p className="mt-1 text-[13px] leading-6 text-[#5f5954]">
                            Hệ quả: {op?.effects?.[0]?.label || 'Lộ trình được điều chỉnh cục bộ cho lesson hiện tại.'}
                          </p>
                          <p className="mt-1 text-[12px] leading-5 text-[#8f6075]">
                            Khuyến nghị tiếp theo: {op?.recommendations?.[0]?.label || getAdaptiveModeGuidance(nextBestAction?.next_best_action)}
                          </p>
                        </div>
                      );
                    })
                  ) : (
                    <p className="text-[14px] leading-6 text-[#6f6862]">
                      Chưa có refinement log mới. Khi quiz hoặc tiến độ tạo tín hiệu đủ mạnh, mọi điều chỉnh sẽ hiện ở đây.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </section>

          <div className="hidden mt-10">
            <SectionIntro
              className="mb-5 items-center"
              title="Gợi ý dành riêng cho bạn"
              titleClassName="section-title text-[30px] tracking-[-0.04em] text-[#4a1f31]"
              actions={
                <button
                  onClick={() => navigate('/learning-path')}
                  className="theme-button-secondary px-4 py-2 text-[13px]"
                >
                  Đổi nhịp học
                </button>
              }
              actionsClassName="lg:self-center"
            />

            <div className="dashboard-next-grid grid gap-4">
              <div className="hidden spotlight-panel interactive-panel dashboard-main-card dashboard-action-card p-6">
                <PanelHeader
                  kicker="Hành động tiếp theo"
                  description="Chỉ 1 bước cần làm tiếp theo để không bị loãng hành trình học."
                  descriptionClassName="max-w-[34ch] text-[13px] leading-6 text-[#6f6862]"
                  aside={
                    <>
                      {nextBestAction?.estimated_total_time ? (
                        <span className="demo-pill">{nextBestAction.estimated_total_time} phút</span>
                      ) : null}
                      {nextBestAction?.priority ? (
                        <span
                          className={`demo-pill ${
                            nextBestAction.priority === 'high'
                              ? 'border-[#efcfdb] bg-[#fff1f6] text-[#a94872]'
                              : 'border-[#efd9e3] bg-[#fff6fa] text-[#8f6075]'
                          }`}
                        >
                          {getPriorityLabel(nextBestAction.priority)}
                        </span>
                      ) : null}
                    </>
                  }
                />
                {nextBestAction ? (
                  <>
                    <div className="dashboard-action-hero">
                      <div className="min-w-0">
                        <h3 className="dashboard-hero-title">
                          {getAdaptiveActionTitle(nextBestAction.next_best_action)}
                        </h3>
                        <p className="mt-4 max-w-[42ch] text-[15px] leading-7 text-[#5f5954]">
                          {nextBestAction.reason}
                        </p>
                      </div>
                      <div className="dashboard-action-glance">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <p className="dashboard-glance-label">Điểm nhấn buổi học</p>
                            <p className="dashboard-glance-copy">
                              {nextBestAction.target_concepts.length > 1
                                ? 'Các khái niệm nên giữ trong tầm nhìn ở phiên học này.'
                                : 'Khái niệm cần chốt ngay trong bước học kế tiếp.'}
                            </p>
                          </div>
                          <p className="dashboard-glance-value shrink-0">
                            {Math.max(nextBestAction.target_concepts.length, 1)}
                          </p>
                        </div>
                        <div className="mt-4 flex flex-wrap gap-2">
                          {nextBestAction.target_concepts
                            .map((concept) => ({
                              key: concept,
                              label: formatConceptDisplay(concept, subjects),
                            }))
                            .filter(
                              (concept): concept is { key: string; label: string } => Boolean(concept.label),
                            )
                            .slice(0, 2)
                            .map((concept) => (
                              <span key={`adaptive-glance-${concept.key}`} className="demo-pill">
                                {concept.label}
                              </span>
                            ))}
                        </div>
                      </div>
                    </div>
                    {adaptivePrimaryItem ? (
                      <div className="dashboard-inline-card mt-5">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="dashboard-glance-label">Gợi ý đang chờ</p>
                            <p className="dashboard-line-clamp-2 mt-2 text-[15px] font-semibold text-[#17141b]">
                              {getAdaptiveItemTitle(adaptivePrimaryItem)}
                            </p>
                            {adaptiveRecommendation?.reason ? (
                              <p className="dashboard-line-clamp-3 mt-2 text-[13px] leading-6 text-[#706963]">
                                {adaptiveRecommendation.reason}
                              </p>
                            ) : null}
                          </div>
                          <span className="demo-pill">
                            {getRecommendationModeLabel(
                              nextBestAction.recommended_mode || resourceRecommendationMode,
                            )}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    <div className="mt-5 flex flex-wrap gap-2">
                      <span className="demo-pill">Mức tự tin: {confidenceLevel}</span>
                      {adaptiveRecommendation?.recommendation_type ? (
                        <span className="demo-pill">
                          {getAdaptiveRecommendationTypeLabel(
                            adaptiveRecommendation.recommendation_type,
                          )}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-6 flex flex-wrap gap-3">
                      <button
                        onClick={handleOpenAdaptiveSuggestion}
                        className="theme-button min-w-[170px]"
                      >
                        Mở gợi ý
                      </button>
                      <button
                        onClick={() =>
                          handleAskAIForGoal(
                            formatConceptDisplay(nextBestAction.target_concepts[0], subjects) ||
                              nextBestAction.target_concepts[0] ||
                              resourceRecommendationGoal ||
                              'adaptive learning',
                            confidenceLevel,
                          )
                        }
                        className="theme-button-secondary"
                      >
                        Hỏi AI nhanh
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="mt-4 text-[14px] leading-6 text-[#5f5954]">
                    Chưa có adaptive action mới. Hãy tiếp tục học hoặc làm quiz để hệ thống cập nhật vòng lặp cá nhân hóa.
                  </p>
                )}
              </div>
              <div className="white-panel interactive-panel dashboard-main-card dashboard-recommendation-card dashboard-recommendation-board p-6">
                <PanelHeader
                  kicker="Gợi ý tài liệu cá nhân hóa"
                  description={getRecommendationModeCaption(resourceRecommendationMode)}
                  descriptionClassName="max-w-[42ch] text-[13px] leading-6 text-[#6f6862]"
                  aside={
                    resourceRecommendationGoal ? (
                      <span className="demo-pill">{resourceRecommendationGoal}</span>
                    ) : null
                  }
                />
                {nextBestAction ? (
                  <div className="dashboard-next-banner mt-5">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="dashboard-banner-badge">Hành động tiếp theo</span>
                        {nextBestAction.priority ? (
                          <span
                            className={`demo-pill ${
                              nextBestAction.priority === 'high'
                                ? 'border-[#efcfdb] bg-[#fff1f6] text-[#a94872]'
                                : 'border-[#efd9e3] bg-[#fff6fa] text-[#8f6075]'
                            }`}
                          >
                            {getPriorityLabel(nextBestAction.priority)}
                          </span>
                        ) : null}
                        {nextBestAction.estimated_total_time ? (
                          <span className="demo-pill">{nextBestAction.estimated_total_time} phút</span>
                        ) : null}
                      </div>
                      <h3 className="mt-3 text-[30px] font-medium leading-[1.02] tracking-[-0.05em] text-[#23131c]">
                        {getAdaptiveActionTitle(nextBestAction.next_best_action)}
                      </h3>
                      <p className="mt-3 max-w-[52ch] text-[14px] leading-6 text-[#5f5954]">
                        {getAdaptiveInsightSummary(nextBestAction)}
                      </p>
                      {nextBestAction.insightMetrics ? (
                        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:max-w-[640px]">
                          {[
                            {
                              key: 'mastery',
                              label: 'Mức đạt mục tiêu',
                              value: nextBestAction.insightMetrics.targetMastery,
                              suffix: '%',
                              tone: 'from-[#ffe3ee] to-[#fff8fb]',
                              ring: '#c7658f',
                              track: '#f3d6e1',
                              accent: '#8f355a',
                              helper: 'Độ vững của nhóm khái niệm đang nhắm tới.',
                            },
                            {
                              key: 'accuracy',
                              label: 'Độ chính xác',
                              value: nextBestAction.insightMetrics.quizAccuracy,
                              suffix: '%',
                              tone: 'from-[#ffe8f0] to-[#fff8fb]',
                              ring: '#d2779b',
                              track: '#f6dce6',
                              accent: '#9f456a',
                              helper: 'Tỷ lệ trả lời đúng ở các lượt quiz gần nhất.',
                            },
                          ]
                            .filter((metric) => metric.value !== null)
                            .map((metric) => {
                              const numericValue = Number(metric.value);
                              const progressValue = clampPercent(numericValue);

                              return (
                                <div
                                  key={metric.key}
                                  className={`rounded-[24px] border border-[#f0d9e3] bg-gradient-to-br ${metric.tone} p-4 shadow-[0_14px_28px_rgba(177,103,138,0.08)]`}
                                >
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="min-w-0">
                                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8f6075]">
                                        {metric.label}
                                      </p>
                                      <p className="mt-2 text-[26px] font-semibold leading-none tracking-[-0.05em] text-[#25151e]">
                                        {numericValue}
                                        {metric.suffix}
                                      </p>
                                    </div>
                                    <div
                                      className="relative h-14 w-14 shrink-0 rounded-full"
                                      style={{
                                        background: `conic-gradient(${metric.ring} ${progressValue}%, ${metric.track} ${progressValue}% 100%)`,
                                      }}
                                    >
                                      <div className="absolute inset-[7px] rounded-full bg-white/90" />
                                      <div
                                        className="absolute inset-0 flex items-center justify-center text-[11px] font-semibold"
                                        style={{ color: metric.accent }}
                                      >
                                        {progressValue}%
                                      </div>
                                    </div>
                                  </div>
                                  <div className="mt-4 h-2 rounded-full" style={{ backgroundColor: metric.track }}>
                                    <div
                                      className="h-full rounded-full"
                                      style={{
                                        width: `${progressValue}%`,
                                        backgroundColor: metric.ring,
                                      }}
                                    />
                                  </div>
                                  <p className="mt-3 text-[12px] leading-5 text-[#6d5762]">
                                    {metric.helper}
                                  </p>
                                </div>
                              );
                            })}
                        </div>
                      ) : null}
                      <div className="mt-4 flex flex-wrap gap-2">
                        {nextBestAction.target_concepts
                          .map((concept) => ({
                            key: concept,
                            label: formatConceptDisplay(concept, subjects),
                          }))
                          .filter(
                            (concept): concept is { key: string; label: string } => Boolean(concept.label),
                          )
                          .slice(0, 3)
                          .map((concept) => (
                            <span key={`adaptive-banner-${concept.key}`} className="demo-pill">
                              {concept.label}
                            </span>
                          ))}
                        <span className="demo-pill">Mức tự tin: {confidenceLevel}</span>
                      </div>
                    </div>
                    <div className="flex flex-col gap-3">
                      <button
                        onClick={handleOpenAdaptiveSuggestion}
                        className="theme-button min-w-[190px]"
                      >
                        Thực hiện ngay
                      </button>
                      <button
                        onClick={() =>
                          handleAskAIForGoal(
                            formatConceptDisplay(nextBestAction.target_concepts[0], subjects) ||
                              nextBestAction.target_concepts[0] ||
                              resourceRecommendationGoal ||
                              'adaptive learning',
                            confidenceLevel,
                          )
                        }
                        className="theme-button-secondary"
                      >
                        Hỏi AI nhanh
                      </button>
                    </div>
                  </div>
                ) : null}
                <div className="segmented-control mt-5 w-full">
                  {RESOURCE_RECOMMENDATION_MODES.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setResourceRecommendationMode(item.value)}
                      className={`${
                        resourceRecommendationMode === item.value
                          ? 'bg-[linear-gradient(135deg,#a94872_0%,#d485a5_100%)] text-white shadow-[0_12px_24px_rgba(169,72,114,0.18)]'
                          : 'bg-[#fff7fa] text-[#a94872]'
                       }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                {resourceRecommendationError ? (
                  <StatusPanel
                    className="mt-5 rounded-[18px] px-4 py-4 shadow-none"
                    tone="info"
                    title="Tạm thời chưa lấy được gợi ý tài nguyên"
                    description={resourceRecommendationError}
                    actions={
                      <button
                        type="button"
                        onClick={() => navigate('/resources')}
                        className="theme-button-secondary px-5 py-3 text-[13px]"
                      >
                        Mở thư viện tài nguyên
                      </button>
                    }
                  />
                ) : null}
                <div className="dashboard-resource-board">
                  <div className="min-w-0">
                    {topResourceRecommendation ? (
                      <>
                        <div className="dashboard-resource-highlight">
                          <PanelHeader
                            kicker="Tài liệu nổi bật"
                            title={topResourceRecommendation.title}
                            titleClassName="dashboard-resource-title dashboard-line-clamp-3 mt-3 text-[30px] leading-[1.05] tracking-[-0.05em] text-[#17141b]"
                            aside={
                              <>
                                <span className="demo-pill">
                                  {Math.round(topResourceRecommendation.relevance_score * 100)}% phù hợp
                                </span>
                                {topResourceRecommendation.estimated_time ? (
                                  <span className="demo-pill">
                                    {topResourceRecommendation.estimated_time} phút
                                  </span>
                                ) : null}
                                <span className="demo-pill">
                                  {getLevelLabel(topResourceRecommendation.level)}
                                </span>
                              </>
                            }
                          />
                          <p className="dashboard-line-clamp-3 mt-4 text-[14px] leading-6 text-[#5f5954]">
                            {topResourceRecommendation.reason}
                          </p>
                          {topResourceReasons.length > 0 ? (
                            <div className="mt-4 rounded-[20px] border border-[#f0dbe4] bg-white/75 px-4 py-4">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8f6075]">
                                Vì sao tài liệu này được gợi ý
                              </p>
                              <div className="mt-3 space-y-2">
                                {topResourceReasons.slice(0, 3).map((reason, index) => (
                                  <p
                                    key={`resource-explanation-${index}`}
                                    className="text-[13px] leading-6 text-[#5f5954]"
                                  >
                                    {reason}
                                  </p>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          <div className="mt-4 grid gap-3 sm:grid-cols-3">
                            <div className="rounded-[18px] border border-[#f0dbe4] bg-white/70 px-4 py-3">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8f6075]">
                                Nguồn học
                              </p>
                              <p className="mt-2 text-[15px] font-semibold text-[#22151d]">
                                {getResourceSourceLabel(topResourceRecommendation.source)}
                              </p>
                            </div>
                            <div className="rounded-[18px] border border-[#f0dbe4] bg-white/70 px-4 py-3">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8f6075]">
                                Cấp độ
                              </p>
                              <p className="mt-2 text-[15px] font-semibold text-[#22151d]">
                                {getLevelLabel(topResourceRecommendation.level)}
                              </p>
                            </div>
                            <div className="rounded-[18px] border border-[#f0dbe4] bg-white/70 px-4 py-3">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8f6075]">
                                Lợi ích kỳ vọng
                              </p>
                              <p className="mt-2 text-[15px] font-semibold text-[#22151d]">
                                {getLearningGainLabel(topResourceRecommendation.expected_learning_gain) ||
                                  getResourceQualityLabel(topResourceRecommendation.quality_score) ||
                                  'Phù hợp để học tiếp ngay'}
                              </p>
                            </div>
                          </div>
                          <div className="mt-4 flex flex-wrap gap-2">
                            {topResourceRecommendation.primary_concepts
                              .map((concept) => ({
                                key: concept,
                                label: formatConceptDisplay(concept, subjects),
                              }))
                              .filter(
                                (concept): concept is { key: string; label: string } =>
                                  Boolean(concept.label),
                              )
                              .slice(0, 3)
                              .map((concept) => (
                                <span
                                  key={`${topResourceRecommendation.resource_id}-${concept.key}`}
                                  className="demo-pill"
                                >
                                  {concept.label}
                                </span>
                              ))}
                          </div>
                        </div>
                        <div className="mt-5 flex flex-wrap gap-3">
                          <button
                            onClick={() => handleViewPersonalizedResource(topResourceRecommendation)}
                            className="theme-button min-w-[170px]"
                          >
                            Xem tài nguyên
                          </button>
                          <button
                            onClick={() =>
                              handleAskAIForGoal(
                                resourceRecommendationGoal || topResourceRecommendation.topic,
                                confidenceLevel,
                              )
                            }
                            className="theme-button-secondary"
                          >
                            Hỏi AI về tài liệu này
                          </button>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            disabled={isSendingRecommendationFeedback}
                            onClick={() =>
                              void handlePersonalizedResourceFeedback(topResourceRecommendation, 'helpful')
                            }
                            className="demo-pill disabled:opacity-60"
                          >
                            Hữu ích
                          </button>
                          <button
                            type="button"
                            disabled={isSendingRecommendationFeedback}
                            onClick={() =>
                              void handlePersonalizedResourceFeedback(topResourceRecommendation, 'hide')
                            }
                            className="demo-pill disabled:opacity-60"
                          >
                            Ẩn gợi ý này
                          </button>
                        </div>
                      </>
                    ) : topRecommendation ? (
                      <>
                        <div className="dashboard-resource-highlight">
                          <PanelHeader
                            kicker="Khái niệm nên học tiếp"
                            title={topRecommendation.concept_name}
                            titleClassName="dashboard-resource-title mt-3 text-[30px] leading-[1.05] tracking-[-0.05em] text-[#17141b]"
                            description={
                              topRecommendation.reasons?.[0] ||
                              'Tiếp tục với khái niệm được đề xuất tiếp theo dựa trên tiến độ gần đây của bạn.'
                            }
                            descriptionClassName="mt-4 text-[14px] leading-6 text-[#5f5954]"
                          />
                        </div>
                        <div className="mt-6 flex flex-wrap gap-3">
                          <button
                            onClick={() =>
                              handleViewResources(topRecommendation.concept_name, topRecommendation)
                            }
                            className="theme-button"
                          >
                            Xem tài nguyên
                          </button>
                          <button
                            onClick={() =>
                              handleAskAIForGoal(topRecommendation.concept_name, confidenceLevel)
                            }
                            className="theme-button-secondary"
                          >
                            Hỏi AI
                          </button>
                        </div>
                      </>
                    ) : (
                      <StatusPanel
                        className="rounded-[24px] px-5 py-8 shadow-none"
                        tone="info"
                        centered
                        title="Chưa có gợi ý nổi bật"
                        description="Tiếp tục học thêm một lesson, làm quiz hoặc mở tài nguyên để hệ thống có đủ tín hiệu cá nhân hóa sâu hơn."
                        actions={
                          <button
                            type="button"
                            onClick={() => navigate('/resources')}
                            className="theme-button-secondary px-5 py-3 text-[13px]"
                          >
                            Mở thư viện tài nguyên
                          </button>
                        }
                      />
                    )}
                  </div>

                </div>

                {alternativeResourceRecommendations.length > 0 ? (
                  <>
                    <PanelHeader
                      kicker="Lựa chọn khác"
                      className="mt-6 items-center"
                      aside={
                        <p className="text-[12px] text-[#7b7069]">
                          Đổi nhịp nếu tài liệu chính chưa đúng ý.
                        </p>
                      }
                    />
                    <div className="dashboard-alt-resource-grid mt-3">
                      {alternativeResourceRecommendations.map((resource) => (
                        <button
                          key={String(resource.resource_id)}
                          type="button"
                          onClick={() => handleViewPersonalizedResource(resource)}
                          className="dashboard-alt-resource-card"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <p className="dashboard-line-clamp-2 min-w-0 text-[15px] font-semibold leading-6 text-[#17141b]">
                              {resource.title}
                            </p>
                            <span className="demo-pill shrink-0">
                              {Math.round(resource.relevance_score * 100)}%
                            </span>
                          </div>
                          <p className="dashboard-line-clamp-3 mt-2 text-[12px] leading-5 text-[#706963]">
                            {resource.reason}
                          </p>
                          {buildRecommendationReasons(resource, subjects)[0] ? (
                            <p className="mt-2 text-[12px] leading-5 text-[#8f6075]">
                              Vì sao gợi ý: {buildRecommendationReasons(resource, subjects)[0]}
                            </p>
                          ) : null}
                          <div className="mt-3 flex flex-wrap gap-2">
                            <span className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-[#8c3451]">
                              {getLevelLabel(resource.level)}
                            </span>
                            <span className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-[#8c3451]">
                              {getResourceSourceLabel(resource.source)}
                            </span>
                            {resource.primary_concepts
                              .map((concept) => ({
                                key: concept,
                                label: formatConceptDisplay(concept, subjects),
                              }))
                              .filter(
                                (concept): concept is { key: string; label: string } =>
                                  Boolean(concept.label),
                              )
                              .slice(0, 2)
                              .map((concept) => (
                                <span
                                  key={`${resource.resource_id}-${concept.key}`}
                                  className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-[#8c3451]"
                                >
                                  {concept.label}
                                </span>
                              ))}
                          </div>
                          <div className="mt-4 flex items-center justify-between gap-3 border-t border-[#f1dce5] pt-3 text-[12px] text-[#7c6a73]">
                            <span>
                              {getLearningGainLabel(resource.expected_learning_gain) ||
                                getResourceQualityLabel(resource.quality_score) ||
                                'Gợi ý phụ để đổi nhịp'}
                            </span>
                            <span className="font-medium text-[#8c3451]">Mở tài liệu</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        </section>

          <div className="hidden">
            <SectionIntro
              className="mb-4 items-center"
              title="Khóa học của tôi"
              titleClassName="section-title"
              actions={
                <button
                  onClick={() => navigate('/learning-path')}
                  className="theme-button-secondary px-4 py-2 text-[12px]"
                >
                  Quản lý
                </button>
              }
              actionsClassName="lg:self-center"
            />

            <div className="dashboard-course-progress-list">
              {myCourseProgressRows.map(({ path, progress, statusTone, statusLabel }) => (
                <button
                  key={path.path_id}
                  onClick={() => handleOpenLearningPath(path)}
                  className="dashboard-course-progress-row"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-3">
                        <span
                          className={`dashboard-course-progress-dot ${
                            statusTone === 'active' ? 'bg-[#54d17d]' : 'bg-[#ddd7dc]'
                          }`}
                        />
                        <p className="dashboard-line-clamp-1 text-[15px] font-semibold text-[#31222b]">
                          {getSubjectDisplay(path)}
                        </p>
                      </div>
                      <p className="mt-2 pl-5 text-[13px] text-[#6d6460]">
                        {path.goal}
                      </p>
                    </div>
                    <span className="text-[15px] font-semibold text-[#8c3451]">{progress}%</span>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3 pl-5">
                    <p className="text-[12px] capitalize text-[#8a8180]">{path.level}</p>
                    <p className="text-[12px] font-medium text-[#8c3451]">{statusLabel}</p>
                  </div>
                  <div className="dashboard-course-progress-track mt-3">
                    <div
                      className="dashboard-course-progress-fill"
                      style={{ width: `${Math.max(progress, progress > 0 ? 6 : 0)}%` }}
                    />
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="hidden dashboard-progress-panel">
            <PanelHeader
              kicker="Tổng quan tiến độ"
              description="Theo dõi nhanh trạng thái hoàn thành và nhịp học trong tuần."
              descriptionClassName="max-w-[34ch] text-[13px] leading-6 text-[#6f6862]"
              aside={<span className="demo-pill">{progressTone}</span>}
            />
            <div className="dashboard-progress-hero">
              <div
                className="dashboard-progress-ring"
                style={{
                  background: `conic-gradient(#8c3451 0 ${progressRingValue}%, rgba(140, 52, 81, 0.14) ${progressRingValue}% 100%)`,
                }}
              >
                <div className="dashboard-progress-ring-core">
                  <span className="text-[30px] font-semibold leading-none tracking-[-0.05em] text-[#17141b]">
                    {stats.progress}%
                  </span>
                  <span className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                    tổng thể
                  </span>
                </div>
              </div>
              <PanelHeader
                kicker="Nhịp hiện tại"
                title={progressTone}
                titleClassName="mt-3 text-[28px] font-medium leading-[1.04] tracking-[-0.04em] text-[#131017]"
                description={
                  stats.total > 0
                    ? `Bạn đã hoàn thành ${stats.completed}/${stats.total} bài và còn ${lessonNotStarted} bài chưa bắt đầu.`
                    : 'Chưa có bài học nào được ghi nhận trong không gian học tập hiện tại.'
                }
                descriptionClassName="mt-3 text-[14px] leading-6 text-[#5f5954]"
              >
                <span className="demo-pill">{weeklyMomentumLabel}</span>
                <span className="demo-pill">{stats.inProgress} bài đang mở</span>
              </PanelHeader>
            </div>
            <div className="dashboard-stat-grid">
              <StatTile label="Hoàn thành" value={stats.completed} />
              <StatTile label="Đang học" value={stats.inProgress} />
              <StatTile label="Chưa bắt đầu" value={lessonNotStarted} />
              <StatTile
                label="Tuần này"
                value={weeklyComparison > 0 ? `+${weeklyComparison}` : weeklyComparison}
              />
            </div>
            <div className="mt-4 rounded-[22px] border border-[#f0e2e8] bg-[#fff8fb] px-4 py-4 text-[13px] leading-6 text-[#6a625d]">
              {stats.inProgress > 0
                ? `Bạn đang có ${stats.inProgress} bài học mở. Hoàn thành nốt chúng sẽ cải thiện độ chính xác của gợi ý tiếp theo.`
                : 'Bạn đang ở trạng thái khá sạch. Đây là thời điểm tốt để mở bài mới hoặc đào sâu phần còn yếu.'}
            </div>
          </div>
      </DesktopPageGrid>
    </DashboardLayout>
  );
}

export default function Dashboard() {
  const { user } = useAuth();

  if (user?.role === 'admin') {
    return <AdminDashboard />;
  }

  return <LearnerDashboard />;
}
