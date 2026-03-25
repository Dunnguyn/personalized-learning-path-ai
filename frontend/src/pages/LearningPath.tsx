import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import type { LearningLevel, LearningPath, LearningPathSubjectId } from '../types/learningPath';
import { SUBJECTS } from '../utils/subjects';

const CARD_THEMES = ['pastel-pink', 'pastel-yellow', 'pastel-purple', 'pastel-mint'] as const;

export default function LearningPath() {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showCreatePath, setShowCreatePath] = useState(false);
  const [generatingPath, setGeneratingPath] = useState(false);
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
      setError(null);
      setNotice(null);

      const result = await learningPathService.generateLearningPath({
        subject_id: pathForm.subjectId as LearningPathSubjectId,
        goal,
        level: pathForm.level,
      });

      setLearningPaths((previous) => [result, ...previous]);
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

  const activePath = useMemo(() => {
    return learningPaths.find((path) => path.path_id === hoveredPathId) ?? learningPaths[0] ?? null;
  }, [hoveredPathId, learningPaths]);

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

  return (
    <DashboardLayout>
      <div className="page-shell pb-6">
        <p className="page-kicker">Lộ trình học tập</p>
        <h1 className="page-title">Lộ trình học tập</h1>

        {error && (
          <div className="white-panel mb-6 border border-red-200 px-4 py-3 text-[14px] text-red-700">{error}</div>
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

        <div className="mb-10 flex flex-wrap gap-4">
          <button type="button" onClick={() => setShowCreatePath((value) => !value)} className="theme-button">
            + Tạo lộ trình mới
          </button>
          <button
            type="button"
            onClick={() => void fetchLearningPaths()}
            disabled={loading}
            className="theme-button-secondary disabled:opacity-50"
          >
            {loading ? 'Đang tải...' : 'Làm mới'}
          </button>
        </div>

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
            <h2 className="page-section-title mb-6 text-[26px]">Tạo lộ trình học tập mới</h2>
            <form onSubmit={handleGeneratePath} className="grid gap-5 md:grid-cols-2">
              <div>
                <label className="mb-2 block text-[14px] font-medium text-[#514942]">Môn học</label>
                <select
                  value={pathForm.subjectId}
                  onChange={(event) => setPathForm((previous) => ({ ...previous, subjectId: event.target.value }))}
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
                  onChange={(event) => setPathForm((previous) => ({ ...previous, goalDetail: event.target.value }))}
                  placeholder="VD: backend, OOP, cấu trúc dữ liệu..."
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

              <div className="flex gap-3 md:col-span-2">
                <button type="submit" disabled={generatingPath} className="theme-button disabled:opacity-60">
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
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div>
                <div className="soft-panel p-[30px]">
                  <h2 className="mb-6 flex items-center gap-2 text-[18px] font-medium text-[#8c3451]">
                    <span className="h-[24px] w-[3px] rounded-full bg-[#8c3451]" />
                    Sơ đồ lộ trình học tập
                  </h2>

                  {learningPaths.length === 0 ? (
                    <div className="white-panel p-5 text-center text-[13px] text-[#5b544d]">
                      Chưa có lộ trình. Hãy tạo lộ trình mới để hiển thị tại đây.
                    </div>
                  ) : (
                    <div className="grid gap-4 md:grid-cols-2">
                      {learningPaths.map((path, index) => (
                        <div
                          key={path.path_id}
                          role="button"
                          tabIndex={0}
                          onClick={() => navigate(`/learning-path/${path.path_id}`, { state: { path } })}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              navigate(`/learning-path/${path.path_id}`, { state: { path } });
                            }
                          }}
                          onMouseEnter={() => setHoveredPathId(path.path_id)}
                          onFocus={() => setHoveredPathId(path.path_id)}
                          className={`pastel-card min-h-[116px] cursor-pointer p-[18px] text-left text-[#5f3040] transition-all duration-200 hover:-translate-y-0.5 ${
                            CARD_THEMES[index % CARD_THEMES.length]
                          }`}
                        >
                          <div className="mb-3 flex items-start justify-between gap-3">
                            <p className="text-[13px] font-medium">{path.goal || 'Tên môn học - Mục tiêu'}</p>
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
                          <p className="text-[11px] opacity-80">
                            Cấp độ: <span className="font-medium">{path.level}</span> • Cập nhật:{' '}
                            <span className="font-medium">
                              {new Date(path.generated_at).toLocaleDateString('vi-VN')}
                            </span>
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <div className="soft-panel sticky top-[24px] p-[30px]">
                  <h3 className="mb-4 text-[14px] font-medium text-[#8c3451]">Thông tin chi tiết môn học</h3>

                  {activePath?.curriculum && activePath.curriculum.length > 0 ? (
                    <div className="space-y-4">
                      <div className="mb-4 border-b border-[#8c3451]/10 pb-3">
                        <p className="text-[14px] font-semibold text-[#8c3451]">{activePath.goal}</p>
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
                                <p className="mt-1 text-[11px] text-[#66615b]">{lessons.length} bài học</p>
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
                          ? 'Di chuột vào lộ trình để xem chi tiết'
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
            <h3 className="text-[28px] font-semibold tracking-[-0.04em] text-[#141217]">Bạn có chắc muốn xóa?</h3>
            <p className="mt-4 text-[15px] leading-7 text-[#5f5853]">
              Lộ trình <span className="font-semibold text-[#8c3451]">{pendingDeletePath.goal}</span> sẽ bị xóa cùng
              các chương, bài học và câu hỏi được sinh riêng cho lộ trình này.
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
