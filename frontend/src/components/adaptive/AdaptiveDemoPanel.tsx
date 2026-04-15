import { useCallback, useEffect, useMemo, useState } from 'react';
import { adaptiveService } from '../../services/adaptiveService';
import { learningPathService } from '../../services/learningPathService';
import type { LearningPath } from '../../types/learningPath';

type DemoAction =
  | 'none'
  | 'state'
  | 'recompute'
  | 'next-step'
  | 'explanation'
  | 'adaptive-quiz'
  | 'question-debug';

interface AdaptiveDemoPanelProps {
  userId: string;
  paths: LearningPath[];
  mode?: 'learner' | 'admin';
  title?: string;
  description?: string;
  refreshLabel?: string;
  onRefreshPaths?: () => Promise<void> | void;
  pathsError?: string | null;
}

interface AdaptiveDemoLessonOption {
  lesson_id: string;
  title: string;
  status: string;
  chapter_title: string;
}

const stringifyJson = (value: unknown) => JSON.stringify(value, null, 2);

const collectPathLessons = (path: LearningPath | null): AdaptiveDemoLessonOption[] =>
  (path?.chapters || []).flatMap((chapter) =>
    (chapter.lessons || []).map((lesson) => ({
      lesson_id: lesson.lesson_id,
      title: lesson.title,
      status: lesson.status,
      chapter_title: chapter.title,
    })),
  );

export default function AdaptiveDemoPanel({
  userId,
  paths,
  mode = 'learner',
  title,
  description,
  refreshLabel = 'Tải lại path',
  onRefreshPaths,
  pathsError,
}: AdaptiveDemoPanelProps) {
  const allowQuestionDebug = mode === 'admin';
  const [demoLoading, setDemoLoading] = useState(false);
  const [refreshingPaths, setRefreshingPaths] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [selectedPathId, setSelectedPathId] = useState('');
  const [selectedLessonId, setSelectedLessonId] = useState('');
  const [targetCount, setTargetCount] = useState(6);
  const [allowLlm, setAllowLlm] = useState(true);
  const [selectedAction, setSelectedAction] = useState<DemoAction>('none');
  const [demoResult, setDemoResult] = useState<string>('{}');

  const selectedPath = useMemo(
    () => paths.find((path) => path.path_id === selectedPathId) || null,
    [paths, selectedPathId],
  );
  const selectedLessons = useMemo(() => collectPathLessons(selectedPath), [selectedPath]);
  const effectiveUserId = selectedPath?.user_id || userId || '';

  useEffect(() => {
    if (!paths.length) {
      setSelectedPathId('');
      return;
    }

    if (!paths.some((path) => path.path_id === selectedPathId)) {
      setSelectedPathId(paths[0]?.path_id || '');
    }
  }, [paths, selectedPathId]);

  useEffect(() => {
    if (!selectedLessons.length) {
      setSelectedLessonId('');
      return;
    }

    if (!selectedLessons.some((lesson) => lesson.lesson_id === selectedLessonId)) {
      const preferredLesson =
        selectedLessons.find((lesson) => lesson.status === 'in_progress') || selectedLessons[0];
      setSelectedLessonId(preferredLesson?.lesson_id || '');
    }
  }, [selectedLessonId, selectedLessons]);

  const handleRefreshPaths = useCallback(async () => {
    if (!onRefreshPaths) {
      return;
    }

    try {
      setRefreshingPaths(true);
      setRequestError(null);
      await onRefreshPaths();
    } catch (refreshError) {
      setRequestError(
        refreshError instanceof Error ? refreshError.message : 'Không thể làm mới danh sách learning path.',
      );
    } finally {
      setRefreshingPaths(false);
    }
  }, [onRefreshPaths]);

  const runAdaptiveDemo = useCallback(
    async (action: DemoAction) => {
      if (action === 'none') {
        return;
      }

      if (!effectiveUserId || !selectedPathId || !selectedLessonId) {
        setRequestError('Cần chọn learning path và lesson để chạy adaptive demo.');
        return;
      }

      try {
        setDemoLoading(true);
        setRequestError(null);
        setSelectedAction(action);

        let response: unknown = null;

        if (action === 'state') {
          response = await adaptiveService.getLearnerStateSnapshot({
            user_id: effectiveUserId,
            path_id: selectedPathId,
            lesson_id: selectedLessonId,
          });
        } else if (action === 'recompute') {
          response = await adaptiveService.recomputeLearnerState({
            user_id: effectiveUserId,
            path_id: selectedPathId,
            lesson_id: selectedLessonId,
          });
        } else if (action === 'next-step') {
          response = await adaptiveService.getAdaptiveNextStep({
            user_id: effectiveUserId,
            path_id: selectedPathId,
            lesson_id: selectedLessonId,
          });
        } else if (action === 'explanation') {
          response = await adaptiveService.getAdaptiveExplanation({
            user_id: effectiveUserId,
            path_id: selectedPathId,
            lesson_id: selectedLessonId,
          });
        } else if (action === 'adaptive-quiz') {
          response = await learningPathService.getNextAdaptiveQuiz(selectedLessonId, {
            path_id: selectedPathId,
            target_count: targetCount,
          });
        } else if (action === 'question-debug' && allowQuestionDebug) {
          response = await learningPathService.debugLessonQuestionGeneration(selectedLessonId, {
            target_count: targetCount,
            allow_llm: allowLlm,
            question_types: ['multiple_choice', 'short_answer'],
            difficulty: 'beginner',
            bloom_levels: ['remember', 'understand'],
            metadata: {
              path_id: selectedPathId,
              target_concepts: [],
              source: mode === 'admin' ? 'admin_demo' : 'learner_demo',
            },
          });
        }

        setDemoResult(stringifyJson(response ?? {}));
      } catch (runError) {
        console.error('Failed to run adaptive demo:', runError);
        setRequestError(runError instanceof Error ? runError.message : 'Không thể chạy adaptive demo.');
      } finally {
        setDemoLoading(false);
      }
    },
    [allowLlm, allowQuestionDebug, effectiveUserId, mode, selectedLessonId, selectedPathId, targetCount],
  );

  const panelTitle =
    title || (mode === 'admin' ? 'Playground cho adaptive loop' : 'Adaptive playground cho người học');
  const panelDescription =
    description ||
    (mode === 'admin'
      ? 'Chọn một learning path và lesson để gọi trực tiếp các API state, recompute, next-step, explanation, adaptive-quiz và debug question generation.'
      : 'Bạn có thể tự kiểm tra learner state, adaptive next step, explanation và adaptive quiz cho lesson đang học mà không cần vào trang admin.');
  const emptyMessage =
    mode === 'admin'
      ? 'Chưa có learning path nào để demo. Hãy tạo learning path trước hoặc dùng tài khoản có dữ liệu.'
      : 'Bạn chưa có learning path để chạy demo adaptive. Hãy tạo learning path rồi quay lại panel này.';

  return (
    <section className="mt-6 white-panel overflow-hidden p-6 md:p-7">
      <div className="flex flex-col gap-4 border-b border-black/5 pb-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-[#8c3451]/55">
            {mode === 'admin' ? 'Adaptive Demo' : 'Adaptive Sandbox'}
          </p>
          <h2 className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-[#18141a]">
            {panelTitle}
          </h2>
          <p className="mt-2 max-w-[760px] text-[14px] leading-6 text-[#5f5954]">{panelDescription}</p>
        </div>

        {onRefreshPaths ? (
          <button
            type="button"
            onClick={() => void handleRefreshPaths()}
            disabled={demoLoading || refreshingPaths}
            className="theme-button-secondary whitespace-nowrap disabled:opacity-60"
          >
            {refreshingPaths ? 'Đang tải lại...' : refreshLabel}
          </button>
        ) : null}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="rounded-[24px] border border-black/5 bg-[#fcf7f9] p-5">
          <div className="space-y-4">
            <div>
              <label className="mb-2 block text-[12px] font-semibold uppercase tracking-[0.14em] text-[#8c3451]/60">
                User ID
              </label>
              <input
                value={effectiveUserId}
                readOnly
                className="w-full rounded-[16px] border border-black/10 bg-white px-4 py-3 text-[14px] text-[#17141a] outline-none"
              />
            </div>

            <div>
              <label className="mb-2 block text-[12px] font-semibold uppercase tracking-[0.14em] text-[#8c3451]/60">
                Learning Path
              </label>
              <select
                value={selectedPathId}
                onChange={(event) => setSelectedPathId(event.target.value)}
                className="w-full rounded-[16px] border border-black/10 bg-white px-4 py-3 text-[14px] text-[#17141a] outline-none"
              >
                <option value="">Chọn learning path</option>
                {paths.map((path) => (
                  <option key={path.path_id} value={path.path_id}>
                    {path.goal || path.path_id} · {path.path_id}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-2 block text-[12px] font-semibold uppercase tracking-[0.14em] text-[#8c3451]/60">
                Lesson
              </label>
              <select
                value={selectedLessonId}
                onChange={(event) => setSelectedLessonId(event.target.value)}
                className="w-full rounded-[16px] border border-black/10 bg-white px-4 py-3 text-[14px] text-[#17141a] outline-none"
              >
                <option value="">Chọn lesson</option>
                {selectedLessons.map((lesson) => (
                  <option key={lesson.lesson_id} value={lesson.lesson_id}>
                    {lesson.chapter_title} · {lesson.title} · {lesson.status}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-[12px] font-semibold uppercase tracking-[0.14em] text-[#8c3451]/60">
                  Target Count
                </label>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={targetCount}
                  onChange={(event) => setTargetCount(Number(event.target.value || 1))}
                  className="w-full rounded-[16px] border border-black/10 bg-white px-4 py-3 text-[14px] text-[#17141a] outline-none"
                />
              </div>

              {allowQuestionDebug ? (
                <div className="flex items-end">
                  <label className="flex w-full items-center justify-between rounded-[16px] border border-black/10 bg-white px-4 py-3 text-[14px] text-[#17141a]">
                    <span>Allow LLM debug</span>
                    <input
                      type="checkbox"
                      checked={allowLlm}
                      onChange={(event) => setAllowLlm(event.target.checked)}
                      className="h-4 w-4"
                    />
                  </label>
                </div>
              ) : (
                <div className="rounded-[16px] border border-dashed border-black/10 bg-white/60 px-4 py-3 text-[12px] leading-5 text-[#6d6660]">
                  User mode chỉ mở các action học tập thực tế. Debug question generation vẫn giữ ở admin.
                </div>
              )}
            </div>
          </div>

          <div className="mt-5 grid gap-3">
            <button
              type="button"
              onClick={() => void runAdaptiveDemo('state')}
              disabled={demoLoading}
              className="theme-button-secondary justify-center disabled:opacity-60"
            >
              Get State
            </button>
            <button
              type="button"
              onClick={() => void runAdaptiveDemo('recompute')}
              disabled={demoLoading}
              className="theme-button-secondary justify-center disabled:opacity-60"
            >
              Recompute State
            </button>
            <button
              type="button"
              onClick={() => void runAdaptiveDemo('next-step')}
              disabled={demoLoading}
              className="theme-button justify-center disabled:opacity-60"
            >
              Run Next Step
            </button>
            <button
              type="button"
              onClick={() => void runAdaptiveDemo('explanation')}
              disabled={demoLoading}
              className="theme-button-secondary justify-center disabled:opacity-60"
            >
              Get Explanation
            </button>
            <button
              type="button"
              onClick={() => void runAdaptiveDemo('adaptive-quiz')}
              disabled={demoLoading}
              className="theme-button-secondary justify-center disabled:opacity-60"
            >
              Adaptive Quiz Next
            </button>
            {allowQuestionDebug ? (
              <button
                type="button"
                onClick={() => void runAdaptiveDemo('question-debug')}
                disabled={demoLoading}
                className="theme-button-secondary justify-center disabled:opacity-60"
              >
                Question Debug
              </button>
            ) : null}
          </div>
        </div>

        <div className="rounded-[24px] border border-black/5 bg-[#161218] p-5 text-white shadow-[0_16px_40px_rgba(25,14,20,0.18)]">
          <div className="flex flex-col gap-3 border-b border-white/10 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-white/45">Response</p>
              <p className="mt-1 text-[16px] font-semibold text-white">
                {selectedAction === 'none' ? 'Chưa chạy request' : `Kết quả: ${selectedAction}`}
              </p>
            </div>
            {demoLoading ? (
              <span className="inline-flex rounded-full bg-white/10 px-3 py-1 text-[12px] font-semibold text-white/80">
                Đang chạy...
              </span>
            ) : null}
          </div>

          {pathsError ? (
            <div className="mt-4 rounded-[18px] border border-amber-300/25 bg-amber-300/10 px-4 py-3 text-[13px] leading-6 text-amber-100">
              {pathsError}
            </div>
          ) : null}

          {requestError ? (
            <div className="mt-4 rounded-[18px] border border-rose-400/25 bg-rose-400/10 px-4 py-3 text-[13px] leading-6 text-rose-100">
              {requestError}
            </div>
          ) : null}

          {!paths.length ? (
            <div className="mt-4 rounded-[18px] border border-amber-300/20 bg-white/5 px-4 py-3 text-[13px] leading-6 text-white/70">
              {emptyMessage}
            </div>
          ) : null}

          <pre className="mt-4 max-h-[760px] overflow-auto rounded-[20px] bg-[#0f0c11] px-4 py-4 text-[12px] leading-6 text-[#f6dce6]">
            <code>{demoResult}</code>
          </pre>
        </div>
      </div>
    </section>
  );
}
