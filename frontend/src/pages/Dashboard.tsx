import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AdminDashboard from './AdminDashboard';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { adaptiveService } from '../services/adaptiveService';
import { dashboardService } from '../services/dashboardService';
import { learningPathService } from '../services/learningPathService';
import { recommendationInteractionService } from '../services/recommendationInteractionService';
import type {
  AdaptiveNextAction,
  AdaptiveRecommendationPayload,
} from '../types/adaptive';
import type {
  AdaptiveRecommendation,
  ConfidenceOverview,
  ProgressOverview,
  RecommendedResourceItem,
} from '../types/dashboard';
import type { LearningPath, LearningPathSubjectId, StudySummary } from '../types/learningPath';
import type { RecommendationFeedbackType } from '../types/recommendation';
import { SUBJECTS } from '../utils/subjects';

type SubjectFilter = 'all' | LearningPathSubjectId;
type UtilityPanel = 'notifications' | null;
type ActivityView = 'lessons' | 'paths' | 'concepts';
type ResourceRecommendationMode =
  | 'continue_learning'
  | 'reinforce_weaknesses'
  | 'learn_new'
  | 'quick_review';

interface ActivityBar {
  label: string;
  caption: string;
  value: number;
}

interface StudyCalendarDay {
  key: string;
  label: string;
  dateLabel: string;
  hours: number;
  intensity: number;
  isToday: boolean;
}

const RESOURCE_RECOMMENDATION_MODES: Array<{
  value: ResourceRecommendationMode;
  label: string;
}> = [
  { value: 'continue_learning', label: 'Continue learning' },
  { value: 'reinforce_weaknesses', label: 'Weak areas' },
  { value: 'learn_new', label: 'New lesson' },
  { value: 'quick_review', label: 'Quick review' },
];

const formatReasonTag = (tag: string) =>
  tag
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

const getAdaptiveActionTitle = (action?: string) => {
  switch (action) {
    case 'study_worked_example':
      return 'Xem ví dụ có hướng dẫn';
    case 'quick_review_session':
      return 'Ôn nhanh 10 phút';
    case 'return_to_prerequisite':
      return 'Quay lại prerequisite';
    case 'review_summary':
      return 'Đọc bản tóm tắt';
    case 'retry_with_easier_resource':
      return 'Học lại với tài liệu dễ hơn';
    case 'move_to_next_lesson':
      return 'Sang bài học tiếp theo';
    case 'resume_unfinished':
      return 'Tiếp tục tài liệu dang dở';
    case 'switch_format_to_video':
      return 'Chuyển sang video';
    case 'switch_format_to_text':
      return 'Chuyển sang tài liệu chữ';
    default:
      return 'Bước học tiếp theo';
  }
};

const renderSubjectIcon = (subjectId: SubjectFilter) => {
  switch (subjectId) {
    case 'python':
      return (
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect
            x="3"
            y="4"
            width="18"
            height="16"
            rx="4"
            fill="currentColor"
            opacity="0.08"
            stroke="none"
          />
          <path d="M8.2 8.5h4.6a1.8 1.8 0 0 1 1.8 1.8v1.3H9.8A1.8 1.8 0 0 0 8 13.4V15a1.8 1.8 0 0 0 1.8 1.8h4.6" />
          <path d="M15.8 15.5h-4.6a1.8 1.8 0 0 1-1.8-1.8v-1.3h4.8a1.8 1.8 0 0 0 1.8-1.8V9a1.8 1.8 0 0 0-1.8-1.8H9.6" />
          <circle cx="10.3" cy="9.95" r="0.7" fill="currentColor" stroke="none" />
          <circle cx="13.7" cy="14.05" r="0.7" fill="currentColor" stroke="none" />
        </svg>
      );
    case 'cpp':
      return (
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect
            x="3"
            y="4"
            width="18"
            height="16"
            rx="4"
            fill="currentColor"
            opacity="0.08"
            stroke="none"
          />
          <path d="M8.8 9.2 6.2 12l2.6 2.8" />
          <path d="M15.2 9.2 17.8 12l-2.6 2.8" />
          <path d="M10.8 8.7 13.2 15.3" />
          <path d="M12 10.2v3.6" />
          <path d="M10.2 12h3.6" />
        </svg>
      );
    case 'csharp':
      return (
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect
            x="3"
            y="4"
            width="18"
            height="16"
            rx="4"
            fill="currentColor"
            opacity="0.08"
            stroke="none"
          />
          <path d="M9.8 8.3c-1.9 0-3.3 1.5-3.3 3.7s1.4 3.7 3.3 3.7c1 0 1.9-.4 2.5-1.1" />
          <path d="M14.8 8.6v6.8" />
          <path d="M12.9 10.5h3.8" />
          <path d="M12.9 13.5h3.8" />
        </svg>
      );
    case 'java':
      return (
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect
            x="3"
            y="4"
            width="18"
            height="16"
            rx="4"
            fill="currentColor"
            opacity="0.08"
            stroke="none"
          />
          <path d="M9.2 15.6h5.6a2.4 2.4 0 0 0 0-4.8h-4.6" />
          <path d="M8.6 10.8v3.2a2.8 2.8 0 0 0 2.8 2.8h3" />
          <path d="M10.2 7.8c.8-.7.8-1.3.1-2" />
          <path d="M13 7.8c.8-.7.8-1.3.1-2" />
          <path d="M15.6 7.8c.8-.7.8-1.3.1-2" />
        </svg>
      );
    case 'all':
    default:
      return (
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect
            x="3"
            y="4"
            width="18"
            height="16"
            rx="4"
            fill="currentColor"
            opacity="0.08"
            stroke="none"
          />
          <circle cx="12" cy="12" r="5.4" />
          <circle cx="12" cy="12" r="2.8" />
          <circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      );
  }
};

const getSubjectIconTheme = (subjectId: SubjectFilter, isActive: boolean) => {
  if (isActive) {
    return {
      wrapperClass:
        'bg-white/95 shadow-[inset_0_1px_0_rgba(255,255,255,0.85),0_10px_18px_rgba(61,18,33,0.14)]',
      iconClass: 'text-[#8c3451]',
    };
  }

  switch (subjectId) {
    case 'python':
      return {
        wrapperClass:
          'bg-[linear-gradient(145deg,#e8f6ff_0%,#f4fbff_100%)] ring-1 ring-[#cfe8fb] shadow-[inset_0_1px_0_rgba(255,255,255,0.95),0_8px_16px_rgba(80,131,168,0.10)]',
        iconClass: 'text-[#2f6f93]',
      };
    case 'cpp':
      return {
        wrapperClass:
          'bg-[linear-gradient(145deg,#efeaff_0%,#faf8ff_100%)] ring-1 ring-[#ded2ff] shadow-[inset_0_1px_0_rgba(255,255,255,0.95),0_8px_16px_rgba(113,90,173,0.10)]',
        iconClass: 'text-[#5b4a9d]',
      };
    case 'csharp':
      return {
        wrapperClass:
          'bg-[linear-gradient(145deg,#f3ecff_0%,#fbf8ff_100%)] ring-1 ring-[#e4d8ff] shadow-[inset_0_1px_0_rgba(255,255,255,0.95),0_8px_16px_rgba(129,95,174,0.10)]',
        iconClass: 'text-[#744ea1]',
      };
    case 'java':
      return {
        wrapperClass:
          'bg-[linear-gradient(145deg,#fff0e7_0%,#fff8f4_100%)] ring-1 ring-[#f8dcc7] shadow-[inset_0_1px_0_rgba(255,255,255,0.95),0_8px_16px_rgba(177,111,68,0.10)]',
        iconClass: 'text-[#9e5834]',
      };
    case 'all':
    default:
      return {
        wrapperClass:
          'bg-[linear-gradient(145deg,#fbeef4_0%,#fff8fc_100%)] ring-1 ring-[#efd7e3] shadow-[inset_0_1px_0_rgba(255,255,255,0.95),0_8px_16px_rgba(137,78,99,0.10)]',
        iconClass: 'text-[#8c3451]',
      };
  }
};

const renderUtilityIcon = (kind: 'bell' | 'settings' | 'community') => {
  switch (kind) {
    case 'bell':
      return (
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
      );
    case 'settings':
      return (
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
      );
    case 'community':
    default:
      return (
        <svg
          viewBox="0 0 20 20"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M6.5 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" />
          <path d="M13.5 10.5a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5Z" />
          <path d="M3.8 14.5a3.2 3.2 0 0 1 5.4-2.3" />
          <path d="M10.7 14.5a2.8 2.8 0 0 1 5-1.7" />
        </svg>
      );
  }
};

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

const scaleActivityBars = (
  items: Array<{ label: string; caption: string; rawValue: number }>,
  minimumVisibleValue = 18,
): ActivityBar[] => {
  const maxValue = Math.max(...items.map((item) => item.rawValue), 1);

  return items.map((item) => ({
    label: item.label,
    caption: item.caption,
    value:
      item.rawValue > 0
        ? Math.max(Math.round((item.rawValue / maxValue) * 100), minimumVisibleValue)
        : 12,
  }));
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
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progressOverview, setProgressOverview] = useState<ProgressOverview | null>(null);
  const [confidenceOverview, setConfidenceOverview] = useState<ConfidenceOverview | null>(null);
  const [recommendations, setRecommendations] = useState<AdaptiveRecommendation[]>([]);
  const [nextBestAction, setNextBestAction] = useState<AdaptiveNextAction | null>(null);
  const [adaptiveRecommendation, setAdaptiveRecommendation] =
    useState<AdaptiveRecommendationPayload | null>(null);
  const [personalizedResources, setPersonalizedResources] = useState<RecommendedResourceItem[]>([]);
  const [resourceRecommendationGoal, setResourceRecommendationGoal] = useState('');
  const [resourceRecommendationMode, setResourceRecommendationMode] =
    useState<ResourceRecommendationMode>('continue_learning');
  const [learningPaths, setLearningPaths] = useState<LearningPath[]>([]);
  const [studySummary, setStudySummary] = useState<StudySummary | null>(null);
  const [selectedSubjectId, setSelectedSubjectId] = useState<SubjectFilter>('all');
  const [activeUtilityPanel, setActiveUtilityPanel] = useState<UtilityPanel>(null);
  const [activityView, setActivityView] = useState<ActivityView>('paths');
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
      setNextBestAction(nextActionData);
      setAdaptiveRecommendation(adaptiveRecommendationData);

      if (recommendationGoal) {
        const personalized = await dashboardService.getPersonalizedResourceRecommendations(
          user.user_id,
          recommendationGoal,
          user.level || 'beginner',
          6,
          resourceRecommendationMode,
        );
        setPersonalizedResources(personalized.recommended_resources);
      } else {
        setPersonalizedResources([]);
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
        recommendation_mode: resource.recommendation_mode || resourceRecommendationMode,
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
          recommendation_mode: resource.recommendation_mode || resourceRecommendationMode,
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
    const subjectMatch = SUBJECTS.find((subject) => goal?.startsWith(subject.goal));
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
    SUBJECTS.find((subject) => subject.id === path.subject_id)?.label || path.goal || 'Khóa học';

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex min-h-[400px] items-center justify-center">
          <div className="text-center">
            <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8c3451]" />
            <p className="text-[#8c3451]">Đang tải dữ liệu...</p>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <div className="flex min-h-[400px] items-center justify-center">
          <div className="text-center">
            <p className="mb-4 text-red-600">{error}</p>
            <button
              onClick={fetchDashboardData}
              className="rounded-full bg-[#8c3451] px-6 py-3 text-white transition-colors hover:bg-[#7a2d46]"
            >
              Thử lại
            </button>
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
  const filteredLearningPaths =
    selectedSubjectId === 'all'
      ? learningPaths
      : learningPaths.filter((path) => path.subject_id === selectedSubjectId);
  const featuredPaths = filteredLearningPaths.slice(0, 4);
  const sideCourses = filteredLearningPaths.slice(0, 3);
  const cardStyles = ['pastel-pink', 'pastel-yellow', 'pastel-purple', 'pastel-mint'];
  const lessonNotStarted = Math.max(stats.total - stats.completed - stats.inProgress, 0);
  const progressTone =
    stats.progress >= 70 ? 'Tiến độ tốt' : stats.progress > 0 ? 'Đang tiến bộ' : 'Sẵn sàng bắt đầu';
  const localInsights = [
    {
      id: 'paths',
      title:
        learningPaths.length > 0
          ? `${learningPaths.length} lộ trình đang sẵn sàng`
          : 'Bạn chưa có lộ trình nào',
      description:
        learningPaths.length > 0
          ? `Hiện có ${stats.inProgress} bài đang học và ${stats.completed} bài đã hoàn thành trong workspace local.`
          : 'Tạo learning path đầu tiên để hệ thống bắt đầu theo dõi tiến độ thực tế của bạn.',
      actionLabel: learningPaths.length > 0 ? 'Mở lộ trình' : 'Tạo lộ trình',
      action: () => navigate('/learning-path'),
    },
      {
        id: 'resources',
        title: topResourceRecommendation
          ? `Tài liệu tiếp theo: ${topResourceRecommendation.title}`
          : topRecommendation
            ? `Gợi ý tiếp theo: ${topRecommendation.concept_name}`
          : 'Kho tài nguyên đang chờ bạn',
        description: topResourceRecommendation
          ? topResourceRecommendation.reason ||
            'Bạn có thể mở tài liệu liên quan để tiếp tục học ngay.'
          : topRecommendation
            ? topRecommendation.reasons?.[0] ||
              'Bạn có thể mở tài nguyên liên quan để tiếp tục học ngay.'
          : 'Thêm hoặc duyệt tài nguyên hiện có để làm giàu môi trường học local.',
        actionLabel: topResourceRecommendation || topRecommendation ? 'Xem tài nguyên' : 'Mở tài nguyên',
        action: () => {
          if (topResourceRecommendation) {
            handleViewPersonalizedResource(topResourceRecommendation);
            return;
          }
          handleViewResources(topRecommendation?.concept_name || '', topRecommendation);
        },
      },
    {
      id: 'settings',
      title: 'Hồ sơ học tập có thể tinh chỉnh',
      description:
        'Cập nhật cấp độ và mục tiêu để dashboard, AI tutor và learning path cá nhân hóa sát hơn.',
      actionLabel: 'Mở cài đặt',
      action: () => navigate('/settings'),
    },
  ];
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
    ? studySummary!.last_7_days.reduce<Record<string, number>>((accumulator, item) => {
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
  const calendarDays: StudyCalendarDay[] = studyCalendarSeed.map((item) => ({
    ...item,
    intensity:
      item.hours > 0 && maxDailyStudyHours > 0
        ? Math.max(Math.round((item.hours / maxDailyStudyHours) * 100), 12)
        : 0,
  }));
  const currentMonthLabel = `Thg ${today.getMonth() + 1}`;
  const activityConfig = (() => {
    if (activityView === 'lessons') {
      return {
        headline: `${stats.completed}/${stats.total}`,
        suffix: 'bài',
        badge: progressTone,
        bars: scaleActivityBars([
          { label: 'Chưa bắt đầu', caption: `${lessonNotStarted} bài`, rawValue: lessonNotStarted },
          { label: 'Đang học', caption: `${stats.inProgress} bài`, rawValue: stats.inProgress },
          { label: 'Hoàn thành', caption: `${stats.completed} bài`, rawValue: stats.completed },
        ]),
      };
    }

    if (activityView === 'concepts') {
      const startedConcepts = progressOverview?.summary.total_concepts_started || 0;
      const completedConcepts = progressOverview?.summary.total_concepts_completed || 0;
      const overallProgress = Math.round(
        progressOverview?.overall_progress_percent || stats.progress,
      );
      const weeklyDelta = Math.abs(Math.round(weeklyComparison));

      return {
        headline: `${overallProgress}%`,
        suffix: 'tiến độ',
        badge: weeklyComparison > 0 ? `+${weeklyComparison}% tuần này` : 'Theo dõi local',
        bars: scaleActivityBars([
          { label: 'Bắt đầu', caption: `${startedConcepts} khái niệm`, rawValue: startedConcepts },
          {
            label: 'Hoàn tất',
            caption: `${completedConcepts} khái niệm`,
            rawValue: completedConcepts,
          },
          { label: 'Tiến độ', caption: `${overallProgress}%`, rawValue: overallProgress },
          { label: 'Tuần này', caption: `${weeklyDelta}%`, rawValue: weeklyDelta },
        ]),
      };
    }

    const pathBars =
      learningPaths.length > 0
        ? learningPaths.slice(0, 6).map((path, index) => ({
            label: `LP ${index + 1}`,
            caption: `${calculatePathProgress(path)}%`,
            rawValue: calculatePathProgress(path),
          }))
        : [{ label: 'LP 1', caption: '0%', rawValue: 0 }];

    return {
      headline: `${learningPaths.length}`,
      suffix: 'lộ trình',
      badge: 'Dữ liệu local',
      bars: scaleActivityBars(pathBars),
    };
  })();

  return (
    <DashboardLayout>
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-w-0">
          <div className="mb-10">
            <p className="page-kicker">Học tập cá nhân hóa</p>
            <h1 className="hero-title max-w-[700px]">Đầu tư cho hành trình học tập</h1>
          </div>

          <div className="mb-8 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setSelectedSubjectId('all')}
              className={selectedSubjectId === 'all' ? 'chip-dark' : 'chip'}
            >
              <span
                className={`flex h-10 w-10 items-center justify-center rounded-full ${
                  getSubjectIconTheme('all', selectedSubjectId === 'all').wrapperClass
                } ${getSubjectIconTheme('all', selectedSubjectId === 'all').iconClass}`}
              >
                {renderSubjectIcon('all')}
              </span>
              Tất cả
            </button>

            {SUBJECTS.slice(0, 4).map((subject) =>
              (() => {
                const subjectId = subject.id as LearningPathSubjectId;
                const isActive = selectedSubjectId === subject.id;
                const iconTheme = getSubjectIconTheme(subjectId, isActive);

                return (
                  <button
                    key={subject.id}
                    type="button"
                    onClick={() => setSelectedSubjectId(subjectId)}
                    className={isActive ? 'chip-dark' : 'chip'}
                  >
                    <span
                      className={`flex h-10 w-10 items-center justify-center rounded-full ${iconTheme.wrapperClass} ${iconTheme.iconClass}`}
                    >
                      {renderSubjectIcon(subjectId)}
                    </span>
                    {subject.label}
                  </button>
                );
              })(),
            )}
          </div>

          <div className="mb-5 flex items-center justify-between">
            <h2 className="section-title">Nổi bật</h2>
            <button
              onClick={() => navigate('/learning-path')}
              className="theme-button-secondary px-4 py-2 text-[13px]"
            >
              Xem tất cả
            </button>
          </div>

          {filteredLearningPaths.length === 0 ? (
            <div className="white-panel p-10 text-center">
              <p className="text-[16px] text-[#5e5854]">
                {selectedSubjectId === 'all'
                  ? 'Chưa có learning path nào. Hãy tạo lộ trình đầu tiên của bạn.'
                  : 'Chưa có learning path cho môn này. Hãy tạo lộ trình mới hoặc chọn môn khác.'}
              </p>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {featuredPaths.map((path, index) => (
                <div
                  key={path.path_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleOpenLearningPath(path)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      handleOpenLearningPath(path);
                    }
                  }}
                  className={`pastel-card ${cardStyles[index % cardStyles.length]} min-h-[252px] text-left`}
                >
                  <div className="mb-10 flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[15px] font-medium text-[#24201d]">
                        {getSubjectDisplay(path)}
                      </p>
                      <p className="mt-1 text-[13px] capitalize text-[#534c47]">{path.level}</p>
                    </div>
                    <span className="rounded-full bg-white/85 px-4 py-2 text-[14px] font-semibold text-[#8c3451]">
                      {calculatePathProgress(path)}%
                    </span>
                  </div>

                  <h3 className="max-w-[460px] text-[28px] font-medium leading-[1.2] tracking-[-0.03em] text-[#141217]">
                    {path.goal}
                  </h3>

                  <div className="mt-8 flex justify-end">
                    <div className="flex flex-col items-end gap-2">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          handleAskAIForGoal(path.goal, path.level);
                        }}
                        className="inline-flex items-center gap-2 rounded-full bg-[#8c3451] px-5 py-3 text-[14px] font-semibold text-white shadow-[0_14px_30px_rgba(140,52,81,0.24)] transition hover:-translate-y-0.5 hover:bg-[#7a2d46] focus:outline-none focus:ring-4 focus:ring-[#f6dbe5]"
                      >
                        Hỏi trợ lý AI
                      </button>
                      <p className="pr-2 text-[12px] font-medium text-[#6f5260]">
                        Nhận giải thích nhanh cho lộ trình này
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-10">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="section-title">Hành động tiếp theo</h2>
              <button
                onClick={() => navigate('/learning-path')}
                className="theme-button-secondary px-4 py-2 text-[13px]"
              >
                Quản lý lộ trình
              </button>
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              <div className="white-panel p-6">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[14px] font-medium text-[#5b544d]">Next best action</p>
                  {nextBestAction?.priority ? (
                    <span
                      className={`rounded-full px-3 py-1 text-[11px] font-semibold ${
                        nextBestAction.priority === 'high'
                          ? 'bg-[#fff1f4] text-[#8c3451]'
                          : 'bg-white text-[#6f5260]'
                      }`}
                    >
                      {nextBestAction.priority.toUpperCase()}
                    </span>
                  ) : null}
                </div>
                {nextBestAction ? (
                  <>
                    <h3 className="mt-4 text-[24px] font-medium leading-[1.2] tracking-[-0.03em] text-[#131017]">
                      {getAdaptiveActionTitle(nextBestAction.next_best_action)}
                    </h3>
                    <p className="mt-3 text-[14px] leading-6 text-[#5f5954]">
                      {nextBestAction.reason}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {nextBestAction.target_concepts.slice(0, 3).map((concept) => (
                        <span
                          key={`adaptive-concept-${concept}`}
                          className="rounded-full bg-[#f8edf3] px-3 py-1 text-[11px] font-semibold text-[#8c3451]"
                        >
                          {concept}
                        </span>
                      ))}
                      {nextBestAction.estimated_total_time ? (
                        <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                          {nextBestAction.estimated_total_time} phút
                        </span>
                      ) : null}
                      {adaptiveRecommendation?.recommendation_mode ? (
                        <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                          {formatReasonTag(adaptiveRecommendation.recommendation_mode)}
                        </span>
                      ) : null}
                    </div>
                    {adaptivePrimaryItem ? (
                      <div className="mt-5 rounded-[18px] border border-[#f0e4ea] bg-[#fff8fb] px-4 py-4">
                        <p className="text-[13px] font-semibold text-[#17141b]">
                          {typeof adaptivePrimaryItem.title === 'string'
                            ? adaptivePrimaryItem.title
                            : typeof adaptivePrimaryItem.resource_title === 'string'
                              ? adaptivePrimaryItem.resource_title
                              : typeof adaptivePrimaryItem.lesson_id === 'string'
                                ? `Lesson ${adaptivePrimaryItem.lesson_id}`
                                : 'Adaptive suggestion'}
                        </p>
                        {adaptiveRecommendation?.reason ? (
                          <p className="mt-2 text-[12px] leading-5 text-[#706963]">
                            {adaptiveRecommendation.reason}
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="mt-6 flex gap-3">
                      <button onClick={handleOpenAdaptiveSuggestion} className="theme-button">
                        Mở gợi ý
                      </button>
                      <button
                        onClick={() =>
                          handleAskAIForGoal(
                            nextBestAction.target_concepts[0] || resourceRecommendationGoal || 'study review',
                            confidenceLevel,
                          )
                        }
                        className="theme-button-secondary"
                      >
                        Hỏi AI
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="mt-4 text-[14px] leading-6 text-[#5f5954]">
                    Chưa có adaptive action mới. Hãy tiếp tục học hoặc làm quiz để hệ thống cập nhật vòng lặp cá nhân hóa.
                  </p>
                )}
              </div>
              <div className="white-panel p-6">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[14px] font-medium text-[#5b544d]">Gợi ý tài liệu cá nhân hóa</p>
                  {resourceRecommendationGoal ? (
                    <span className="rounded-full bg-[#fff1f6] px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                      {resourceRecommendationGoal}
                    </span>
                  ) : null}
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {RESOURCE_RECOMMENDATION_MODES.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setResourceRecommendationMode(item.value)}
                      className={`rounded-full px-3 py-2 text-[12px] font-semibold transition ${
                        resourceRecommendationMode === item.value
                          ? 'bg-[#8c3451] text-white'
                          : 'border border-[#ebdbe2] bg-white text-[#8c3451]'
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                {topResourceRecommendation ? (
                  <>
                    <h3 className="text-[26px] font-medium leading-[1.2] tracking-[-0.03em] text-[#131017]">
                      {topResourceRecommendation.title}
                    </h3>
                    <p className="mt-3 text-[14px] leading-6 text-[#5f5954]">
                      {topResourceRecommendation.reason}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {topResourceRecommendation.reason_tags.slice(0, 4).map((tag) => (
                        <span
                          key={`${topResourceRecommendation.resource_id}-${tag}`}
                          className="rounded-full bg-[#f8edf3] px-3 py-1 text-[11px] font-semibold text-[#8c3451]"
                        >
                          {formatReasonTag(tag)}
                        </span>
                      ))}
                      {topResourceRecommendation.estimated_time ? (
                        <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                          {topResourceRecommendation.estimated_time} phút
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-6 flex gap-3">
                      <button
                        onClick={() => handleViewPersonalizedResource(topResourceRecommendation)}
                        className="theme-button"
                      >
                        Xem tài nguyên
                      </button>
                      <button
                        onClick={() =>
                          handleAskAIForGoal(resourceRecommendationGoal || topResourceRecommendation.topic, confidenceLevel)
                        }
                        className="theme-button-secondary"
                      >
                        Hỏi AI
                      </button>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        disabled={isSendingRecommendationFeedback}
                        onClick={() =>
                          void handlePersonalizedResourceFeedback(topResourceRecommendation, 'helpful')
                        }
                        className="rounded-full border border-[#ebdbe2] px-3 py-2 text-[12px] font-medium text-[#8c3451] transition hover:bg-[#fff7fb] disabled:opacity-60"
                      >
                        Hữu ích
                      </button>
                      <button
                        type="button"
                        disabled={isSendingRecommendationFeedback}
                        onClick={() =>
                          void handlePersonalizedResourceFeedback(topResourceRecommendation, 'hide')
                        }
                        className="rounded-full border border-[#ebdbe2] px-3 py-2 text-[12px] font-medium text-[#8c3451] transition hover:bg-[#fff7fb] disabled:opacity-60"
                      >
                        Ẩn gợi ý này
                      </button>
                    </div>
                    {personalizedResources.length > 1 ? (
                      <div className="mt-5 space-y-3">
                        {personalizedResources.slice(1, 4).map((resource) => (
                          <button
                            key={String(resource.resource_id)}
                            type="button"
                            onClick={() => handleViewPersonalizedResource(resource)}
                            className="w-full rounded-[18px] border border-[#f0e4ea] bg-[#fff8fb] px-4 py-4 text-left transition hover:border-[#d8b8c6]"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-[14px] font-semibold text-[#17141b]">
                                {resource.title}
                              </p>
                              <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                                {Math.round(resource.relevance_score * 100)}%
                              </span>
                            </div>
                            <p className="mt-2 text-[12px] leading-5 text-[#706963]">
                              {resource.reason}
                            </p>
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </>
                ) : topRecommendation ? (
                  <>
                    <h3 className="text-[26px] font-medium leading-[1.2] tracking-[-0.03em] text-[#131017]">
                      {topRecommendation.concept_name}
                    </h3>
                    <p className="mt-3 text-[14px] leading-6 text-[#5f5954]">
                      {topRecommendation.reasons?.[0] ||
                        'Tiếp tục với khái niệm được đề xuất tiếp theo dựa trên tiến độ gần đây của bạn.'}
                    </p>
                    <div className="mt-6 flex gap-3">
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
                  <p className="text-[14px] leading-6 text-[#5f5954]">
                    Chưa có gợi ý nổi bật. Hãy tiếp tục học để hệ thống cá nhân hóa sâu hơn.
                  </p>
                )}
              </div>

              <div className="white-panel p-6">
                <p className="mb-4 text-[14px] font-medium text-[#5b544d]">Tổng quan tiến độ</p>
                <div className="space-y-4">
                  <div>
                    <div className="mb-2 flex items-center justify-between text-[14px] text-[#3d3733]">
                      <span>Tiến độ tổng</span>
                      <span className="font-semibold">{stats.progress}%</span>
                    </div>
                    <div className="h-3 rounded-full bg-[#f6e4ec]">
                      <div
                        className="h-3 rounded-full bg-[#8c3451]"
                        style={{ width: `${stats.progress}%` }}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3">
                    <div className="metric-card text-center">
                      <p className="text-[12px] text-[#77706a]">Hoàn thành</p>
                      <p className="mt-2 text-[26px] font-semibold text-[#121019]">
                        {stats.completed}
                      </p>
                    </div>
                    <div className="metric-card text-center">
                      <p className="text-[12px] text-[#77706a]">Đang học</p>
                      <p className="mt-2 text-[26px] font-semibold text-[#121019]">
                        {stats.inProgress}
                      </p>
                    </div>
                    <div className="metric-card text-center">
                      <p className="text-[12px] text-[#77706a]">Tuần này</p>
                      <p className="mt-2 text-[26px] font-semibold text-[#121019]">
                        {weeklyComparison > 0 ? `+${weeklyComparison}` : weeklyComparison}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </section>

        <aside className="space-y-5 xl:sticky xl:top-4 xl:self-start">
          <div className="soft-panel p-7">
            <div className="mb-6 flex items-center justify-between">
              <button
                type="button"
                aria-label="Mở thông báo local"
                onClick={() =>
                  setActiveUtilityPanel((current) =>
                    current === 'notifications' ? null : 'notifications',
                  )
                }
                className={`flex h-11 w-11 items-center justify-center rounded-full bg-white/85 text-[#8c3451] transition ${
                  activeUtilityPanel === 'notifications' ? 'ring-2 ring-[#8c3451]/20' : ''
                }`}
              >
                {renderUtilityIcon('bell')}
              </button>
              <button
                type="button"
                aria-label="Mở cài đặt"
                onClick={() => navigate('/settings')}
                className="flex h-11 w-11 items-center justify-center rounded-full bg-white/85 text-[#8c3451] transition hover:-translate-y-0.5"
              >
                {renderUtilityIcon('settings')}
              </button>
            </div>

            <div className="mb-6 text-center">
              <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-[#f3cad7] text-[28px] font-semibold text-[#8c3451]">
                {(user?.name || 'A').slice(0, 1)}
              </div>
              <h2 className="text-[22px] font-medium tracking-[-0.03em] text-[#121019]">
                {user?.name || 'Người học'}
              </h2>
            </div>

            {activeUtilityPanel === 'notifications' && (
              <div className="white-panel ui-fade-in mb-5 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <p className="text-[13px] font-medium text-[#8c3451]">Thông báo local</p>
                    <p className="mt-1 text-[12px] text-[#746d67]">
                      Các gợi ý này được tạo từ dữ liệu đang có trên máy của bạn.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveUtilityPanel(null)}
                    className="rounded-full border border-[#ead9e1] px-3 py-1 text-[12px] font-medium text-[#8c3451]"
                  >
                    Đóng
                  </button>
                </div>

                <div className="space-y-3">
                  {localInsights.map((item) => (
                    <div
                      key={item.id}
                      className="rounded-[20px] border border-[#f0e4ea] bg-[#fff8fb] p-3"
                    >
                      <p className="text-[13px] font-semibold text-[#17141b]">{item.title}</p>
                      <p className="mt-1 text-[12px] leading-5 text-[#706963]">
                        {item.description}
                      </p>
                      <button
                        type="button"
                        onClick={item.action}
                        className="mt-3 rounded-full bg-[#8c3451] px-3 py-2 text-[12px] font-semibold text-white"
                      >
                        {item.actionLabel}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="white-panel p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[14px] text-[#6f6862]">Hoạt động</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#121019]">
                    {formatHoursShort(cumulativeStudyHours)}
                    <span className="hidden ml-2 rounded-full bg-[#f8edf3] px-3 py-2 text-[13px] font-medium text-[#8c3451]">
                      Kết quả tốt!
                    </span>
                  </p>
                </div>
                <button className="theme-button-secondary px-4 py-2 text-[12px]">
                  {currentMonthLabel}
                </button>
              </div>

              <div className="hidden mt-4 flex flex-wrap gap-2">
                {(
                  [
                    { id: 'paths', label: 'Lộ trình' },
                    { id: 'lessons', label: 'Bài học' },
                    { id: 'concepts', label: 'Khái niệm' },
                  ] as Array<{ id: ActivityView; label: string }>
                ).map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActivityView(item.id)}
                    className={`rounded-full px-3 py-2 text-[12px] font-medium transition ${
                      activityView === item.id
                        ? 'bg-[#8c3451] text-white shadow-[0_10px_24px_rgba(140,52,81,0.18)]'
                        : 'border border-[#ead9e1] bg-white text-[#6f6862]'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              <div className="mt-4 flex items-center justify-between text-[12px] text-[#6f6862]">
                <span>7 ngày học gần đây</span>
                <span className="whitespace-nowrap">{formatHoursShort(weeklyStudyHours)}</span>
              </div>

              <div className="mt-5 flex h-[190px] items-end justify-between gap-2">
                {calendarDays.map((day) => (
                  <div key={day.key} className="flex min-w-0 flex-1 flex-col items-center gap-2">
                    <div
                      className={`flex h-[146px] w-full items-end rounded-[22px] border p-1.5 ${
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
                        className={`text-[11px] font-semibold ${day.isToday ? 'text-[#8c3451]' : 'text-[#524b46]'}`}
                      >
                        {day.label}
                      </p>
                      <p className="text-[11px] text-[#7b746f]">{day.dateLabel}</p>
                      <p className="whitespace-nowrap text-[11px] text-[#8c3451]">
                        {formatHoursForColumn(day.hours)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="hidden mt-6 flex h-[180px] items-end justify-between gap-2">
                {activityConfig.bars.map((bar) => (
                  <div
                    key={`${activityView}-${bar.label}`}
                    className="flex min-w-0 flex-1 flex-col items-center gap-2"
                  >
                    <div className="flex h-[140px] w-full items-end rounded-[18px] bg-[#ece4ff] p-1">
                      <div
                        className="w-full rounded-[14px] bg-gradient-to-b from-[#f3b9c8] via-[#cfc8ff] to-[#9de3b9]"
                        style={{ height: `${bar.value}%` }}
                      />
                    </div>
                    <div className="text-center">
                      <p className="truncate text-[11px] font-medium text-[#524b46]">{bar.label}</p>
                      <p className="text-[11px] text-[#8c3451]">{bar.caption}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="section-title">Khóa học của tôi</h2>
              <button
                onClick={() => navigate('/learning-path')}
                className="theme-button-secondary px-4 py-2 text-[12px]"
              >
                Mở
              </button>
            </div>

            <div className="space-y-4">
              {sideCourses.map((path, index) => (
                <button
                  key={path.path_id}
                  onClick={() => handleOpenLearningPath(path)}
                  className={`pastel-card ${cardStyles[index % cardStyles.length]} w-full text-left`}
                >
                  <div className="mb-10 flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[14px] font-medium text-[#24201d]">
                        {getSubjectDisplay(path)}
                      </p>
                      <p className="mt-1 text-[13px] capitalize text-[#4d4640]">{path.level}</p>
                    </div>
                    <span className="rounded-full bg-white/85 px-4 py-2 text-[14px] font-semibold text-[#8c3451]">
                      {calculatePathProgress(path)}%
                    </span>
                  </div>
                  <h3 className="text-[20px] font-medium leading-[1.25] tracking-[-0.03em] text-[#141217]">
                    {path.goal}
                  </h3>
                </button>
              ))}
            </div>
          </div>
        </aside>
      </div>
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
