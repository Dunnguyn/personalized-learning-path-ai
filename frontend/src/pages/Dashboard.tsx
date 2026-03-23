import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { dashboardService } from '../services/dashboardService';
import { learningPathService } from '../services/learningPathService';
import type { AdaptiveRecommendation, ConfidenceOverview, ProgressOverview } from '../types/dashboard';
import type { LearningPath } from '../services/learningPathService';
import { SUBJECTS } from '../utils/subjects';

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [progressOverview, setProgressOverview] = useState<ProgressOverview | null>(null);
  const [confidenceOverview, setConfidenceOverview] = useState<ConfidenceOverview | null>(null);
  const [recommendations, setRecommendations] = useState<AdaptiveRecommendation[]>([]);
  const [learningPaths, setLearningPaths] = useState<LearningPath[]>([]);

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    fetchDashboardData();
  }, [user, navigate]);

  const fetchDashboardData = async () => {
    if (!user) return;

    try {
      setLoading(true);
      setError(null);

      const [progressData, confidenceData, recommendationsData, pathHistory] = await Promise.all([
        dashboardService.getProgressOverview(user.user_id),
        dashboardService.getConfidenceOverview(user.user_id),
        dashboardService.getAdaptiveRecommendations(user.user_id),
        learningPathService.getLearningPathHistory(),
      ]);

      setProgressOverview(progressData);
      setConfidenceOverview(confidenceData);
      setRecommendations(recommendationsData);

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
  };

  const handleViewResources = (query: string) => {
    navigate(`/resources?q=${encodeURIComponent(query)}`);
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
  const confidenceScore = confidenceOverview?.confidence || 0;
  const confidenceLevel = confidenceOverview?.level || 'beginner';
  const topRecommendation = recommendations[0];
  const featuredPaths = learningPaths.slice(0, 4);
  const sideCourses = learningPaths.slice(0, 3);
  const cardStyles = ['pastel-pink', 'pastel-yellow', 'pastel-purple', 'pastel-mint'];

  const getSubjectDisplay = (path: LearningPath) =>
    SUBJECTS.find((subject) => subject.id === path.subject_id)?.label || path.goal || 'Khóa học';

  return (
    <DashboardLayout>
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-w-0">
          <div className="mb-10">
            <p className="mb-3 text-[14px] font-medium uppercase tracking-[0.2em] text-[#7e776f]">
              Học tập cá nhân hóa
            </p>
            <h1 className="hero-title max-w-[700px]">Đầu tư cho hành trình học tập</h1>
          </div>

          <div className="mb-8 flex flex-wrap gap-3">
            <button className="chip-dark">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-[#8c3451]">
                ◎
              </span>
              Tất cả
            </button>
            {SUBJECTS.slice(0, 4).map((subject) => (
              <button key={subject.id} className="chip">
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-[#8c3451]">
                  ◧
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

          {learningPaths.length === 0 ? (
            <div className="white-panel p-10 text-center">
              <p className="text-[16px] text-[#5e5854]">
                Chưa có learning path nào. Hãy tạo lộ trình đầu tiên của bạn.
              </p>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {featuredPaths.map((path, index) => (
                <button
                  key={path.path_id}
                  onClick={() => navigate(`/learning-path/${path.path_id}`, { state: { path } })}
                  className={`pastel-card ${cardStyles[index % cardStyles.length]} min-h-[252px] text-left`}
                >
                  <div className="mb-10 flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[15px] font-medium text-[#24201d]">{getSubjectDisplay(path)}</p>
                      <p className="mt-1 text-[13px] capitalize text-[#534c47]">{path.level}</p>
                    </div>
                    <span className="rounded-full bg-white/85 px-4 py-2 text-[14px] font-semibold text-[#8c3451]">
                      {Math.max(4.6, 5 - index * 0.1).toFixed(1)}
                    </span>
                  </div>
                  <h3 className="max-w-[460px] text-[28px] font-medium leading-[1.2] tracking-[-0.03em] text-[#141217]">
                    {path.goal}
                  </h3>
                  <div className="mt-8 flex items-center justify-between">
                    <p className="text-[14px] text-[#2d2824]/80">
                      {stats.total > 0 ? `${stats.total} bài học đang được theo dõi` : 'Bắt đầu lộ trình đầu tiên'}
                    </p>
                    <div className="flex -space-x-2">
                      {[0, 1, 2].map((avatar) => (
                        <span
                          key={avatar}
                          className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-white bg-[#8c3451] text-[12px] text-white"
                        >
                          {avatar + 1}
                        </span>
                      ))}
                    </div>
                  </div>
                </button>
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
              <button className="flex h-11 w-11 items-center justify-center rounded-full bg-white/85 text-[20px]">
                🔔
              </button>
              <button className="flex h-11 w-11 items-center justify-center rounded-full bg-white/85 text-[20px]">
                ⚙
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

            <div className="white-panel mb-5 flex items-center justify-between px-5 py-4">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-full border border-[#8c3451]/10 bg-white text-[20px] text-[#8c3451]">
                  ◎
                </span>
                <div>
                  <p className="text-[12px] text-[#7b746f]">Cộng đồng</p>
                  <p className="text-[18px] font-semibold text-[#121019]">274 bạn học</p>
                </div>
              </div>
              <span className="text-[22px] text-[#8c3451]">›</span>
            </div>

            <div className="white-panel p-5">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <p className="text-[14px] text-[#6f6862]">Hoạt động</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#121019]">
                    {confidenceScore ? `${confidenceScore}h` : '3.5h'}{' '}
                    <span className="ml-2 rounded-full bg-[#f8edf3] px-3 py-2 text-[13px] font-medium text-[#8c3451]">
                      Kết quả tốt!
                    </span>
                  </p>
                </div>
                <button className="theme-button-secondary px-4 py-2 text-[12px]">Năm</button>
              </div>
              <div className="mt-6 flex h-[150px] items-end justify-between gap-2">
                {[54, 42, 33, 61, 27, 22, 74].map((height, index) => (
                  <div key={index} className="flex-1 rounded-[18px] bg-[#ece4ff] p-1">
                    <div
                      className="w-full rounded-[14px] bg-gradient-to-b from-[#f3b9c8] via-[#cfc8ff] to-[#9de3b9]"
                      style={{ height: `${height + 20}px` }}
                    />
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
                  onClick={() => navigate(`/learning-path/${path.path_id}`, { state: { path } })}
                  className={`pastel-card ${cardStyles[index % cardStyles.length]} w-full text-left`}
                >
                  <div className="mb-10 flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[14px] font-medium text-[#24201d]">{getSubjectDisplay(path)}</p>
                      <p className="mt-1 text-[13px] capitalize text-[#4d4640]">{path.level}</p>
                    </div>
                    <span className="rounded-full bg-white/85 px-4 py-2 text-[14px] font-semibold text-[#8c3451]">
                      {Math.max(4.6, 4.9 - index * 0.1).toFixed(1)}
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
