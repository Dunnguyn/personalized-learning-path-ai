import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { dashboardService } from '../services/dashboardService';
import { learningPathService } from '../services/learningPathService';
import type { AdaptiveRecommendation, ConfidenceOverview, ProgressOverview } from '../types/dashboard';
import type { LearningPath, LearningPathSubjectId, StudySummary } from '../types/learningPath';
import { SUBJECTS } from '../utils/subjects';

type SubjectFilter = 'all' | LearningPathSubjectId;
type UtilityPanel = 'notifications' | 'workspace' | null;
type ActivityView = 'lessons' | 'paths' | 'concepts';

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

const renderSubjectIcon = (subjectId: SubjectFilter) => {
  switch (subjectId) {
    case 'python':
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 5.5h12" />
          <path d="M4 10h8" />
          <path d="M4 14.5h12" />
          <path d="M13 8l3 2-3 2" />
        </svg>
      );
    case 'cpp':
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8 5.5L4.5 10 8 14.5" />
          <path d="M12 5.5l3.5 4.5-3.5 4.5" />
          <path d="M10 8v4" />
          <path d="M8 10h4" />
        </svg>
      );
    case 'csharp':
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 4.5v11" />
          <path d="M10 4.5v11" />
          <path d="M3.5 8h11" />
          <path d="M3.5 12h11" />
        </svg>
      );
    case 'java':
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 8.5h7a1.5 1.5 0 0 1 0 3H12" />
          <path d="M6 8.5v4a2 2 0 0 0 2 2h4" />
          <path d="M8.5 5.5c.5-.6.4-1.2 0-1.8" />
          <path d="M11 5.5c.5-.6.4-1.2 0-1.8" />
        </svg>
      );
    case 'all':
    default:
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="10" cy="10" r="6.5" />
          <circle cx="10" cy="10" r="3.5" />
          <circle cx="10" cy="10" r="1" fill="currentColor" stroke="none" />
        </svg>
      );
  }
};

const renderUtilityIcon = (kind: 'bell' | 'settings' | 'community') => {
  switch (kind) {
    case 'bell':
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 3.5a3 3 0 0 0-3 3v1.2c0 .7-.2 1.4-.6 2L5.2 12a1 1 0 0 0 .9 1.5h7.8a1 1 0 0 0 .9-1.5l-1.2-2.3a4 4 0 0 1-.6-2V6.5a3 3 0 0 0-3-3Z" />
          <path d="M8.4 15a1.8 1.8 0 0 0 3.2 0" />
        </svg>
      );
    case 'settings':
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="10" cy="10" r="2.3" />
          <path d="M16 10a1.6 1.6 0 0 0 .1.5l1 1.5-1.4 2.4-1.8-.2a1.6 1.6 0 0 0-.8.5l-.8 1.6H8.7l-.8-1.6a1.6 1.6 0 0 0-.8-.5l-1.8.2L3.9 12l1-1.5A1.6 1.6 0 0 0 5 10a1.6 1.6 0 0 0-.1-.5l-1-1.5 1.4-2.4 1.8.2a1.6 1.6 0 0 0 .8-.5l.8-1.6h2.6l.8 1.6a1.6 1.6 0 0 0 .8.5l1.8-.2L17.1 8l-1 1.5c-.1.2-.1.3-.1.5Z" />
        </svg>
      );
    case 'community':
    default:
      return (
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
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
  minimumVisibleValue = 18
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

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progressOverview, setProgressOverview] = useState<ProgressOverview | null>(null);
  const [confidenceOverview, setConfidenceOverview] = useState<ConfidenceOverview | null>(null);
  const [recommendations, setRecommendations] = useState<AdaptiveRecommendation[]>([]);
  const [learningPaths, setLearningPaths] = useState<LearningPath[]>([]);
  const [studySummary, setStudySummary] = useState<StudySummary | null>(null);
  const [selectedSubjectId, setSelectedSubjectId] = useState<SubjectFilter>('all');
  const [activeUtilityPanel, setActiveUtilityPanel] = useState<UtilityPanel>(null);
  const [activityView, setActivityView] = useState<ActivityView>('paths');

  const fetchDashboardData = useCallback(async () => {
    if (!user) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const [progressData, confidenceData, recommendationsData, pathHistory, studyTimeData] = await Promise.all([
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

      if (pathHistory && pathHistory.length > 0) {
        const pathsWithDetails = await Promise.all(
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
          })
        );

        setLearningPaths(pathsWithDetails);
      } else {
        setLearningPaths([]);
      }
    } catch (err) {
      console.error('Error fetching dashboard data:', err);
      setError(err instanceof Error ? err.message : 'Không thể tải dữ liệu tổng quan');
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    void fetchDashboardData();
  }, [fetchDashboardData, navigate, user]);

  const handleViewResources = (query: string) => {
    navigate(`/resources?q=${encodeURIComponent(query)}`);
  };

  const handleOpenLearningPath = (path: LearningPath) => {
    navigate(`/learning-path/${path.path_id}`, { state: { path } });
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
  const workspaceTitle = learningPaths.length > 0 ? `${learningPaths.length} lộ trình local` : 'Không gian local';
  const workspaceSubtitle =
    learningPaths.length > 0
      ? `${stats.inProgress} bài đang học • ${stats.completed} bài hoàn thành`
      : 'Chưa có cộng đồng online, nhưng bạn vẫn có thể thao tác nhanh ngay trên máy này.';
  const localInsights = [
    {
      id: 'paths',
      title: learningPaths.length > 0 ? `${learningPaths.length} lộ trình đang sẵn sàng` : 'Bạn chưa có lộ trình nào',
      description:
        learningPaths.length > 0
          ? `Hiện có ${stats.inProgress} bài đang học và ${stats.completed} bài đã hoàn thành trong workspace local.`
          : 'Tạo learning path đầu tiên để hệ thống bắt đầu theo dõi tiến độ thực tế của bạn.',
      actionLabel: learningPaths.length > 0 ? 'Mở lộ trình' : 'Tạo lộ trình',
      action: () => navigate('/learning-path'),
    },
    {
      id: 'resources',
      title: topRecommendation ? `Gợi ý tiếp theo: ${topRecommendation.concept_name}` : 'Kho tài nguyên đang chờ bạn',
      description: topRecommendation
        ? topRecommendation.reasons?.[0] || 'Bạn có thể mở tài nguyên liên quan để tiếp tục học ngay.'
        : 'Thêm hoặc duyệt tài nguyên hiện có để làm giàu môi trường học local.',
      actionLabel: topRecommendation ? 'Xem tài nguyên' : 'Mở tài nguyên',
      action: () => handleViewResources(topRecommendation?.concept_name || ''),
    },
    {
      id: 'settings',
      title: 'Hồ sơ học tập có thể tinh chỉnh',
      description: 'Cập nhật cấp độ và mục tiêu để dashboard, AI tutor và learning path cá nhân hóa sát hơn.',
      actionLabel: 'Mở cài đặt',
      action: () => navigate('/settings'),
    },
  ];
  const conceptProgressItems = progressOverview?.summary.concepts || [];
  const totalAttemptCount = conceptProgressItems.reduce((sum, concept) => sum + Math.max(concept.total_attempts || 0, 0), 0);
  const fallbackStudyHours = stats.completed * ESTIMATED_HOURS_PER_COMPLETED_LESSON + stats.inProgress * ESTIMATED_HOURS_PER_IN_PROGRESS_LESSON;
  const estimatedStudyHours = totalAttemptCount > 0 ? totalAttemptCount * ESTIMATED_HOURS_PER_ATTEMPT : fallbackStudyHours;
  const cumulativeStudyHours = studySummary?.total_hours ?? estimatedStudyHours;
  const estimatedDailyStudyHours = conceptProgressItems.reduce<Record<string, number>>((accumulator, concept) => {
    const updatedAt = new Date(concept.last_updated);
    if (Number.isNaN(updatedAt.getTime())) {
      return accumulator;
    }

    const dayKey = formatDayKey(updatedAt);
    const sessionHours = Math.max(ESTIMATED_HOURS_PER_ATTEMPT, Math.min(concept.total_attempts || 1, 4) * ESTIMATED_HOURS_PER_ATTEMPT);
    accumulator[dayKey] = (accumulator[dayKey] || 0) + sessionHours;
    return accumulator;
  }, {});
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
    intensity: item.hours > 0 && maxDailyStudyHours > 0 ? Math.max(Math.round((item.hours / maxDailyStudyHours) * 100), 18) : 10,
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
      const overallProgress = Math.round(progressOverview?.overall_progress_percent || stats.progress);
      const weeklyDelta = Math.abs(Math.round(weeklyComparison));

      return {
        headline: `${overallProgress}%`,
        suffix: 'tiến độ',
        badge: weeklyComparison > 0 ? `+${weeklyComparison}% tuần này` : 'Theo dõi local',
        bars: scaleActivityBars([
          { label: 'Bắt đầu', caption: `${startedConcepts} khái niệm`, rawValue: startedConcepts },
          { label: 'Hoàn tất', caption: `${completedConcepts} khái niệm`, rawValue: completedConcepts },
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
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-[#8c3451]">
                {renderSubjectIcon('all')}
              </span>
              Tất cả
            </button>

            {SUBJECTS.slice(0, 4).map((subject) => (
              <button
                key={subject.id}
                type="button"
                onClick={() => setSelectedSubjectId(subject.id as LearningPathSubjectId)}
                className={selectedSubjectId === subject.id ? 'chip-dark' : 'chip'}
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-[#8c3451]">
                  {renderSubjectIcon(subject.id as LearningPathSubjectId)}
                </span>
                {subject.label}
              </button>
            ))}
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
                      <p className="text-[15px] font-medium text-[#24201d]">{getSubjectDisplay(path)}</p>
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

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="white-panel p-6">
                <p className="mb-2 text-[14px] font-medium text-[#5b544d]">Gợi ý thích ứng</p>
                {topRecommendation ? (
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
                        onClick={() => handleViewResources(topRecommendation.concept_name)}
                        className="theme-button"
                      >
                        Xem tài nguyên
                      </button>
                      <button
                        onClick={() => handleAskAIForGoal(topRecommendation.concept_name, confidenceLevel)}
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
                      <div className="h-3 rounded-full bg-[#8c3451]" style={{ width: `${stats.progress}%` }} />
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3">
                    <div className="metric-card text-center">
                      <p className="text-[12px] text-[#77706a]">Hoàn thành</p>
                      <p className="mt-2 text-[26px] font-semibold text-[#121019]">{stats.completed}</p>
                    </div>
                    <div className="metric-card text-center">
                      <p className="text-[12px] text-[#77706a]">Đang học</p>
                      <p className="mt-2 text-[26px] font-semibold text-[#121019]">{stats.inProgress}</p>
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
                  setActiveUtilityPanel((current) => (current === 'notifications' ? null : 'notifications'))
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
                    <div key={item.id} className="rounded-[20px] border border-[#f0e4ea] bg-[#fff8fb] p-3">
                      <p className="text-[13px] font-semibold text-[#17141b]">{item.title}</p>
                      <p className="mt-1 text-[12px] leading-5 text-[#706963]">{item.description}</p>
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

            <div
              role="button"
              tabIndex={0}
              onClick={() => setActiveUtilityPanel((current) => (current === 'workspace' ? null : 'workspace'))}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setActiveUtilityPanel((current) => (current === 'workspace' ? null : 'workspace'));
                }
              }}
              className="white-panel mb-5 flex items-center justify-between px-5 py-4 text-left transition hover:-translate-y-0.5"
            >
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-full border border-[#8c3451]/10 bg-white text-[#8c3451]">
                  {renderUtilityIcon('community')}
                </span>
                <div>
                  <p className="text-[12px] text-[#7b746f]">Workspace local</p>
                  <p className="text-[18px] font-semibold text-[#121019]">{workspaceTitle}</p>
                  <p className="mt-1 text-[12px] leading-5 text-[#746d67]">{workspaceSubtitle}</p>
                </div>
                <div className="hidden">
                  <p className="text-[12px] text-[#7b746f]">Cộng đồng</p>
                  <p className="text-[18px] font-semibold text-[#121019]">274 bạn học</p>
                </div>
              </div>
              <span className="text-[22px] text-[#8c3451]">›</span>
            </div>

            {activeUtilityPanel === 'workspace' && (
              <div className="white-panel ui-fade-in mb-5 p-4">
                <p className="text-[13px] font-medium text-[#8c3451]">Chế độ local đang hoạt động</p>
                <p className="mt-2 text-[12px] leading-5 text-[#706963]">
                  Tính năng cộng đồng online chưa được phát triển, nên khu vực này đang đóng vai trò như trung tâm thao tác nhanh cho workspace cá nhân.
                </p>
                <div className="mt-4 grid gap-2">
                  <button
                    type="button"
                    onClick={() => navigate('/learning-path')}
                    className="rounded-full border border-[#ead9e1] bg-[#fff8fb] px-4 py-3 text-[13px] font-semibold text-[#8c3451]"
                  >
                    Quản lý lộ trình
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/resources')}
                    className="rounded-full border border-[#ead9e1] bg-[#fff8fb] px-4 py-3 text-[13px] font-semibold text-[#8c3451]"
                  >
                    Mở tài nguyên
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/settings')}
                    className="rounded-full border border-[#ead9e1] bg-[#fff8fb] px-4 py-3 text-[13px] font-semibold text-[#8c3451]"
                  >
                    Tinh chỉnh hồ sơ học tập
                  </button>
                </div>
              </div>
            )}

            <div className="white-panel p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[14px] text-[#6f6862]">Hoạt động</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#121019]">
                    {cumulativeStudyHours.toFixed(1)}{' '}
                    <span className="text-[15px] font-medium text-[#6f6862]">gio</span>
                    <span className="hidden ml-2 rounded-full bg-[#f8edf3] px-3 py-2 text-[13px] font-medium text-[#8c3451]">
                      Kết quả tốt!
                    </span>
                    <span className="ml-2 rounded-full bg-[#f8edf3] px-3 py-2 text-[13px] font-medium text-[#8c3451]">
                      Tich luy local
                    </span>
                  </p>
                </div>
                <button className="theme-button-secondary px-4 py-2 text-[12px]">{currentMonthLabel}</button>
              </div>

              <div className="hidden mt-4 flex flex-wrap gap-2">
                {([
                  { id: 'paths', label: 'Lộ trình' },
                  { id: 'lessons', label: 'Bài học' },
                  { id: 'concepts', label: 'Khái niệm' },
                ] as Array<{ id: ActivityView; label: string }>).map((item) => (
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
                <span>7 ngay hoc gan day</span>
                <span>{weeklyStudyHours.toFixed(1)}h gan day</span>
              </div>

              <div className="mt-5 flex h-[190px] items-end justify-between gap-2">
                {calendarDays.map((day) => (
                  <div key={day.key} className="flex min-w-0 flex-1 flex-col items-center gap-2">
                    <div
                      className={`flex h-[146px] w-full items-end rounded-[22px] border p-1.5 ${
                        day.isToday ? 'border-[#8c3451]/20 bg-[#fff6fa]' : 'border-[#ece4ff] bg-[#f7f2ff]'
                      }`}
                    >
                      <div
                        className="w-full rounded-[18px] bg-gradient-to-b from-[#f3b9c8] via-[#cfc8ff] to-[#9de3b9]"
                        style={{ height: `${day.intensity}%` }}
                      />
                    </div>
                    <div className="text-center">
                      <p className={`text-[11px] font-semibold ${day.isToday ? 'text-[#8c3451]' : 'text-[#524b46]'}`}>{day.label}</p>
                      <p className="text-[11px] text-[#7b746f]">{day.dateLabel}</p>
                      <p className="text-[11px] text-[#8c3451]">{day.hours > 0 ? `${day.hours.toFixed(1)}h` : '0h'}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="hidden mt-6 flex h-[180px] items-end justify-between gap-2">
                {activityConfig.bars.map((bar) => (
                  <div key={`${activityView}-${bar.label}`} className="flex min-w-0 flex-1 flex-col items-center gap-2">
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
                      <p className="text-[14px] font-medium text-[#24201d]">{getSubjectDisplay(path)}</p>
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
