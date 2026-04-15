import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { activityIcon, learningJourneyIcon } from '../assets';
import DashboardLayout from '../components/layout/DashboardLayout';
import PageHero from '../components/ui/PageHero';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import type { LearningLevel, LearningPath, LearningPathSubjectId } from '../types/learningPath';
import { SUBJECTS } from '../utils/subjects';

const CARD_THEMES = ['pastel-pink', 'pastel-yellow', 'pastel-purple', 'pastel-mint'] as const;
const GENERATION_STAGES = [
  'Đang phân tích mục tiêu học tập',
  'Đang dựng cấu trúc chương và bài học',
  'Đang sắp xếp thứ tự ưu tiên',
  'Đang hoàn tất lộ trình cá nhân hóa',
] as const;

const LEVEL_LABELS: Record<LearningLevel, string> = {
  beginner: 'Bước đầu',
  intermediate: 'Trung bình',
  advanced: 'Nâng cao',
};

const getLevelLabel = (level?: string) =>
  level && level in LEVEL_LABELS
    ? LEVEL_LABELS[level as LearningLevel]
    : level || 'Chưa xác định';

const getChapterStatus = (lessons: Array<{ status?: string }>) => {
  if (!lessons.length) {
    return 'Chưa bắt đầu';
  }
  if (lessons.every((lesson) => lesson.status === 'complete')) {
    return 'Hoàn thành';
  }
  if (lessons.some((lesson) => lesson.status === 'in_progress')) {
    return 'Đang học';
  }
  return 'Chưa bắt đầu';
};

export default function LearningPath() {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showCreatePath, setShowCreatePath] = useState(false);
  const [generatingPath, setGeneratingPath] = useState(false);
  const [generationProgress, setGenerationProgress] = useState(0);
  const [generationStage, setGenerationStage] = useState<string>(GENERATION_STAGES[0]);
  const [learningPaths, setLearningPaths] = useState<LearningPath[]>([]);
  const [hoveredPathId, setHoveredPathId] = useState<string | null>(null);
  const [pendingDeletePath, setPendingDeletePath] = useState<LearningPath | null>(null);
  const [deletingPathId, setDeletingPathId] = useState<string | null>(null);
  const [pathForm, setPathForm] = useState({
    subjectId: SUBJECTS[0]?.id ?? '',
    goalDetail: '',
    level: 'beginner' as LearningLevel,
  });

  useEffect(() => {
    const state = location.state as { notice?: string } | null;
    if (!state?.notice) {
      return;
    }

    setNotice(state.notice);
    navigate(location.pathname, { replace: true, state: {} });
  }, [location.pathname, location.state, navigate]);

  useEffect(() => {
    if (!notice) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setNotice(null);
    }, 4500);

    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  useEffect(() => {
    if (!generatingPath) {
      setGenerationProgress(0);
      setGenerationStage(GENERATION_STAGES[0]);
      return;
    }

    setGenerationProgress(10);
    setGenerationStage(GENERATION_STAGES[0]);

    let currentProgress = 10;
    let stageIndex = 0;

    const intervalId = window.setInterval(() => {
      currentProgress = Math.min(currentProgress + Math.max(2, Math.round((96 - currentProgress) / 6)), 96);
      stageIndex = Math.min(
        GENERATION_STAGES.length - 1,
        Math.floor((currentProgress - 10) / 24),
      );
      setGenerationProgress(currentProgress);
      setGenerationStage(GENERATION_STAGES[stageIndex]);
    }, 700);

    return () => window.clearInterval(intervalId);
  }, [generatingPath]);

  const buildGoal = (subjectId: string, goalDetail: string) => {
    const subject = SUBJECTS.find((item) => item.id === subjectId);
    const baseGoal = subject?.goal?.trim() ?? '';
    const detail = goalDetail.trim();

    if (!baseGoal && !detail) {
      return '';
    }
    if (!baseGoal) {
      return detail;
    }
    if (!detail) {
      return baseGoal;
    }
    return `${baseGoal} - ${detail}`;
  };

  const fetchLearningPaths = useCallback(async () => {
    if (!user) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const history = await learningPathService.getLearningPathHistory();
      if (!history.length) {
        setLearningPaths([]);
        setHoveredPathId(null);
        return;
      }

      const pathsWithDetails = await Promise.all(
        history.map(async (path) => {
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

      setLearningPaths(pathsWithDetails);
      setHoveredPathId((current) => current ?? pathsWithDetails[0]?.path_id ?? null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tải lộ trình học';
      setError(message);
      console.error('Error fetching learning path:', err);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }
    void fetchLearningPaths();
  }, [fetchLearningPaths, navigate, user]);

  const handleGeneratePath = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!user) {
      return;
    }

    const goal = buildGoal(pathForm.subjectId, pathForm.goalDetail);
    if (!goal) {
      setError('Vui lòng chọn môn học hoặc nhập mục tiêu chi tiết.');
      return;
    }

    try {
      setGeneratingPath(true);
      setGenerationProgress(10);
      setGenerationStage(GENERATION_STAGES[0]);
      setError(null);
      setNotice(null);

      const result = await learningPathService.generateLearningPath({
        subject_id: pathForm.subjectId as LearningPathSubjectId,
        goal,
        level: pathForm.level,
      });

      setLearningPaths((previous) => [result, ...previous]);
      setGenerationProgress(100);
      setGenerationStage('Hoàn tất lộ trình học tập');
      setHoveredPathId(result.path_id);
      setShowCreatePath(false);
      setPathForm({
        subjectId: SUBJECTS[0]?.id ?? '',
        goalDetail: '',
        level: 'beginner',
      });
      setNotice(
        result.curriculum_source === 'fallback'
          ? result.curriculum_notice ||
              'AI chưa sẵn sàng cho lần tạo này. Hệ thống đã dùng lộ trình dự phòng để bạn tiếp tục học.'
          : 'Đã tạo lộ trình học mới thành công.',
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tạo lộ trình học';
      setError(message);
      console.error('Error generating path:', err);
    } finally {
      setGeneratingPath(false);
    }
  };

  const handleConfirmDeletePath = async () => {
    if (!pendingDeletePath) {
      return;
    }

    try {
      setDeletingPathId(pendingDeletePath.path_id);
      setError(null);
      setNotice(null);

      await learningPathService.deleteLearningPath(pendingDeletePath.path_id);

      setLearningPaths((previous) => {
        const next = previous.filter((path) => path.path_id !== pendingDeletePath.path_id);
        setHoveredPathId((current) => {
          if (current !== pendingDeletePath.path_id) {
            return current;
          }
          return next[0]?.path_id ?? null;
        });
        return next;
      });

      setPendingDeletePath(null);
      setNotice('Đã xóa lộ trình học và dữ liệu được sinh riêng cho lộ trình này.');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể xóa lộ trình học';
      setError(message);
    } finally {
      setDeletingPathId(null);
    }
  };

  const activePath = useMemo(
    () => learningPaths.find((path) => path.path_id === hoveredPathId) ?? learningPaths[0] ?? null,
    [hoveredPathId, learningPaths],
  );

  const stats = useMemo(() => {
    let total = 0;
    let completed = 0;
    let inProgress = 0;

    learningPaths.forEach((path) => {
      (path.curriculum || []).forEach((chapter) => {
        (chapter.lessons || []).forEach((lesson) => {
          total += 1;
          if (lesson.status === 'complete') {
            completed += 1;
          } else if (lesson.status === 'in_progress') {
            inProgress += 1;
          }
        });
      });
    });

    return {
      total,
      completed,
      inProgress,
      progress: total > 0 ? Math.round((completed / total) * 100) : 0,
    };
  }, [learningPaths]);

  return (
    <DashboardLayout>
      <div className="page-shell desktop-1440-learning-path pb-6">
        <PageHero
          className="mb-6 learning-path-hero-minimal"
          descriptionClassName="hidden"
          kicker="Learning tracks"
          title="Quản lý lộ trình học theo mục tiêu thay vì tự ghép từng bước rời rạc."
          description="Trang này gom toàn bộ track đang hoạt động, tiến độ hiện tại và chi tiết chương để bạn chuyển nhịp nhanh hơn, đặc biệt khi đang học song song nhiều môn."
          actions={
            <>
              <button
                type="button"
                onClick={() => setShowCreatePath((value) => !value)}
                className="theme-button"
              >
                {showCreatePath ? 'Thu gọn biểu mẫu' : 'Tạo lộ trình mới'}
              </button>
              <button
                type="button"
                onClick={() => void fetchLearningPaths()}
                disabled={loading}
                className="theme-button-secondary disabled:opacity-50"
              >
                {loading ? 'Đang tải...' : 'Làm mới'}
              </button>
            </>
          }
          metrics={[
            {
              label: 'Số lộ trình',
              value: learningPaths.length,
              detail:
                learningPaths.length > 0
                  ? 'Chọn một track để xem nhanh cấu trúc chương và trạng thái học.'
                  : 'Chưa có track nào. Tạo track đầu tiên để bắt đầu.',
            },
            {
              label: 'Tiến độ chung',
              value: `${stats.progress}%`,
              detail:
                stats.total > 0
                  ? `${stats.completed}/${stats.total} bài đã hoàn thành trên toàn bộ workspace.`
                  : 'Chưa có bài học nào được ghi nhận.',
            },
            {
              label: 'Đang học',
              value: stats.inProgress,
              detail: 'Các bài đang mở nên được hoàn tất trước để khuyến nghị tiếp theo chính xác hơn.',
            },
          ]}
        >
          <div className="hero-visual-grid md:grid-cols-2">
            <article className="hero-visual-card">
              <span className="hero-visual-icon">
                <img src={learningJourneyIcon} alt="" className="h-7 w-7 object-contain" />
              </span>
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Track map
                </p>
                <p className="mt-2 text-[16px] font-semibold text-[#17141a]">
                  Chuyển nhanh giữa các kế hoạch học đang hoạt động mà không mất ngữ cảnh.
                </p>
              </div>
            </article>
            <article className="hero-visual-card">
              <span className="hero-visual-icon">
                <img src={activityIcon} alt="" className="h-7 w-7 object-contain" />
              </span>
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Nhịp tiến độ
                </p>
                <p className="mt-2 text-[16px] font-semibold text-[#17141a]">
                  Nhìn nhanh trạng thái bài học và tiến độ tổng để quyết định bước tiếp theo.
                </p>
              </div>
            </article>
          </div>
        </PageHero>

        {error && (
          <div className="white-panel mb-6 border border-red-200 px-4 py-3 text-[14px] text-red-700">
            {error}
          </div>
        )}

        {notice && (
          <div className="white-panel mb-6 flex items-start justify-between gap-4 border border-[#ead7df] bg-[#fff7fb] px-4 py-3 text-[14px] text-[#8c3451]">
            <p>{notice}</p>
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="shrink-0 rounded-full border border-[#8c3451]/10 bg-white/70 px-3 py-1 text-[12px] font-medium text-[#8c3451] transition hover:bg-white"
            >
              Đóng
            </button>
          </div>
        )}

        {loading && (
          <div className="flex min-h-[400px] items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8c3451]" />
              <p className="text-[#8c3451]">Đang tải lộ trình học tập...</p>
            </div>
          </div>
        )}

        {showCreatePath && !loading && (
          <div className="soft-panel mb-10 p-8">
            <div className="mb-6 flex flex-col gap-2">
              <h2 className="page-section-title text-[26px]">Tạo lộ trình học tập mới</h2>
              <p className="max-w-[72ch] text-[14px] leading-6 text-[#6a625d]">
                Chọn môn học, thêm mục tiêu cụ thể nếu cần và để hệ thống dựng ra khung chương bài
                phù hợp với trình độ hiện tại.
              </p>
            </div>
            <form onSubmit={handleGeneratePath} className="grid gap-5 md:grid-cols-2">
              <div>
                <label className="mb-2 block text-[14px] font-medium text-[#514942]">Môn học</label>
                <select
                  value={pathForm.subjectId}
                  onChange={(event) =>
                    setPathForm((previous) => ({ ...previous, subjectId: event.target.value }))
                  }
                  className="theme-input rounded-[18px]"
                  required
                >
                  {SUBJECTS.map((subject) => (
                    <option key={subject.id} value={subject.id}>
                      {subject.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-2 block text-[14px] font-medium text-[#514942]">
                  Mục tiêu chi tiết (tùy chọn)
                </label>
                <input
                  type="text"
                  value={pathForm.goalDetail}
                  onChange={(event) =>
                    setPathForm((previous) => ({ ...previous, goalDetail: event.target.value }))
                  }
                  placeholder="Ví dụ: backend, OOP, cấu trúc dữ liệu..."
                  className="theme-input rounded-[18px]"
                />
              </div>

              <div>
                <label className="mb-2 block text-[14px] font-medium text-[#514942]">Cấp độ</label>
                <select
                  value={pathForm.level}
                  onChange={(event) =>
                    setPathForm((previous) => ({
                      ...previous,
                      level: event.target.value as LearningLevel,
                    }))
                  }
                  className="theme-input rounded-[18px]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
              </div>

              {generatingPath && (
                <div className="md:col-span-2">
                  <div className="rounded-[22px] border border-[#ead7df] bg-white/80 px-5 py-4 shadow-[0_18px_40px_rgba(140,52,81,0.08)]">
                    <div className="mb-2 flex items-center justify-between gap-4 text-[13px] font-medium text-[#8c3451]">
                      <span>{generationStage}</span>
                      <span>{generationProgress}%</span>
                    </div>
                    <div className="h-3 rounded-full bg-[#f6e7ee] p-[2px]">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-[#9b3a5a] via-[#c7688b] to-[#e6a8bb] transition-[width] duration-500 ease-out"
                        style={{ width: `${generationProgress}%` }}
                      />
                    </div>
                    <p className="mt-3 text-[13px] text-[#6a625d]">
                      Hệ thống đang tạo lộ trình học tập. Yêu cầu này sẽ chờ tới khi hoàn tất.
                    </p>
                  </div>
                </div>
              )}

              <div className="flex gap-3 md:col-span-2">
                <button
                  type="submit"
                  disabled={generatingPath}
                  className="theme-button disabled:opacity-60"
                >
                  {generatingPath ? 'Đang tạo...' : 'Tạo lộ trình'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreatePath(false);
                    setError(null);
                  }}
                  className="theme-button-secondary"
                >
                  Hủy
                </button>
              </div>
            </form>
          </div>
        )}

        {!loading && (
          <>
            <div className="desktop-1440-learning-path-grid grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div>
                <div className="soft-panel p-[30px]">
                  <h2 className="mb-6 flex items-center gap-2 text-[18px] font-medium text-[#8c3451]">
                    <span className="h-[24px] w-[3px] rounded-full bg-[#8c3451]" />
                    Sơ đồ lộ trình học tập
                  </h2>

                  {learningPaths.length === 0 ? (
                    <div className="white-panel p-5 text-center text-[13px] text-[#5b544d]">
                      Chưa có lộ trình nào. Hãy tạo lộ trình mới để hiển thị tại đây.
                    </div>
                  ) : (
                    <div className="grid gap-4 md:grid-cols-2">
                      {learningPaths.map((path, index) => (
                        <article
                          key={path.path_id}
                          role="button"
                          tabIndex={0}
                          onClick={() =>
                            navigate(`/learning-path/${path.path_id}`, { state: { path } })
                          }
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              navigate(`/learning-path/${path.path_id}`, { state: { path } });
                            }
                          }}
                          onMouseEnter={() => setHoveredPathId(path.path_id)}
                          onFocus={() => setHoveredPathId(path.path_id)}
                          className={`pastel-card min-h-[132px] cursor-pointer p-[18px] text-left text-[#5f3040] transition-all duration-200 hover:-translate-y-0.5 ${
                            CARD_THEMES[index % CARD_THEMES.length]
                          }`}
                        >
                          <div className="mb-3 flex items-start justify-between gap-3">
                            <p className="text-[14px] font-semibold leading-6">
                              {path.goal || 'Tên môn học - Mục tiêu'}
                            </p>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setPendingDeletePath(path);
                              }}
                              disabled={deletingPathId === path.path_id}
                              className="rounded-full border border-[#8c3451]/15 bg-white/80 px-3 py-1 text-[11px] font-medium text-[#8c3451] transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {deletingPathId === path.path_id ? 'Đang xóa...' : 'Xóa'}
                            </button>
                          </div>

                          <div className="flex flex-wrap gap-2">
                            <span className="rounded-full bg-white/75 px-3 py-1 text-[11px] font-medium text-[#8c3451]">
                              {getLevelLabel(path.level)}
                            </span>
                            <span className="rounded-full bg-white/75 px-3 py-1 text-[11px] font-medium text-[#8c3451]">
                              Cập nhật {new Date(path.generated_at).toLocaleDateString('vi-VN')}
                            </span>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <div className="soft-panel sticky top-[24px] p-[30px]">
                  <h3 className="mb-4 text-[14px] font-medium text-[#8c3451]">
                    Thông tin chi tiết môn học
                  </h3>

                  {activePath?.curriculum && activePath.curriculum.length > 0 ? (
                    <div className="space-y-4">
                      <div className="mb-4 border-b border-[#8c3451]/10 pb-3">
                        <p className="text-[14px] font-semibold text-[#8c3451]">
                          {activePath.goal}
                        </p>
                        <p className="mt-2 text-[13px] leading-6 text-[#6d6660]">
                          {activePath.curriculum.length} chương đang sẵn sàng để học theo thứ tự.
                        </p>
                      </div>

                      {activePath.curriculum.map((chapter, index) => {
                        const lessons = chapter.lessons || [];
                        const status = getChapterStatus(lessons);

                        return (
                          <div key={`${chapter.chapter_id}-${index}`} className="metric-card p-4">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <p className="text-[13px] font-semibold text-[#8c3451]">
                                  {chapter.title || `Chương ${index + 1}`}
                                </p>
                                <p className="mt-1 text-[11px] text-[#66615b]">
                                  {lessons.length} bài học
                                </p>
                              </div>
                              <span className="rounded-full border border-[#8c3451]/10 bg-white px-2 py-1 text-[10px] text-[#8c3451]">
                                {status}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="py-12 text-center">
                      <p className="text-[14px] text-[#6d6660]">
                        {learningPaths.length > 0
                          ? 'Rê chuột vào lộ trình để xem chi tiết'
                          : 'Chưa có thông tin chương học.'}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
              <div className="metric-card bg-[#fff7fb] p-6 text-center">
                <p className="mb-2 text-[12px] font-medium text-[#66615b]">Tổng bài học</p>
                <p className="text-[28px] font-bold text-[#8c3451]">{stats.total}</p>
              </div>
              <div className="metric-card bg-[#fff7fb] p-6 text-center">
                <p className="mb-2 text-[12px] font-medium text-[#66615b]">Đã hoàn thành</p>
                <p className="text-[28px] font-bold text-[#8c3451]">{stats.completed}</p>
              </div>
              <div className="metric-card bg-[#fff7fb] p-6 text-center">
                <p className="mb-2 text-[12px] font-medium text-[#66615b]">Đang học</p>
                <p className="text-[28px] font-bold text-[#8c3451]">{stats.inProgress}</p>
              </div>
              <div className="metric-card bg-[#fff7fb] p-6 text-center">
                <p className="mb-2 text-[12px] font-medium text-[#66615b]">Tiến độ</p>
                <p className="text-[28px] font-bold text-[#8c3451]">{stats.progress}%</p>
              </div>
            </div>
          </>
        )}
      </div>

      {pendingDeletePath && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-[#2a1522]/20 px-4 py-6 backdrop-blur-sm"
          onClick={() => {
            if (!deletingPathId) {
              setPendingDeletePath(null);
            }
          }}
        >
          <div
            className="white-panel ui-pop-in w-full max-w-[480px] rounded-[28px] p-7 shadow-[0_28px_80px_rgba(140,52,81,0.16)]"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="page-kicker mb-2">Xóa lộ trình</p>
            <h3 className="text-[28px] font-semibold tracking-[-0.04em] text-[#141217]">
              Bạn có chắc muốn xóa?
            </h3>
            <p className="mt-4 text-[15px] leading-7 text-[#5f5853]">
              Lộ trình <span className="font-semibold text-[#8c3451]">{pendingDeletePath.goal}</span>{' '}
              sẽ bị xóa cùng các chương, bài học và câu hỏi được sinh riêng cho lộ trình này.
            </p>

            <div className="mt-8 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => setPendingDeletePath(null)}
                disabled={Boolean(deletingPathId)}
                className="theme-button-secondary"
              >
                Giữ lại
              </button>
              <button
                type="button"
                onClick={() => void handleConfirmDeletePath()}
                disabled={Boolean(deletingPathId)}
                className="theme-button disabled:opacity-60"
              >
                {deletingPathId ? 'Đang xóa...' : 'Xóa lộ trình'}
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
