import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import type {
  LearningPath,
  LessonQuizAttemptResponse,
  LessonQuizQuestion,
  LessonQuizSubmitResponse,
} from '../services/learningPathService';

interface PathState {
  path?: LearningPath;
}

type LessonItem = NonNullable<LearningPath['curriculum']>[number]['lessons'][number];
type OptionKey = 'A' | 'B' | 'C' | 'D';
type QuestionResult = NonNullable<NonNullable<LessonItem['assessment']>['question_results']>[number];

interface LessonQuizState {
  attemptId: string;
  attemptNumber: number;
  questions: LessonQuizQuestion[];
  results: LessonQuizSubmitResponse['results'];
  passThresholdCount: number;
  correctCount: number;
  score: number;
  confidenceScore: number;
  isPassed: boolean;
}

type LessonBusyPhase = 'idle' | 'creating' | 'submitting' | 'restarting';

const levelLabel = (level?: string) => {
  switch (level) {
    case 'beginner':
      return 'Bước đầu';
    case 'intermediate':
      return 'Trung bình';
    case 'advanced':
      return 'Nâng cao';
    default:
      return level || 'N/A';
  }
};

export default function LearningPathDetail() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { pathId } = useParams();
  const location = useLocation();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [path, setPath] = useState<LearningPath | null>(null);
  const [lessonAnswers, setLessonAnswers] = useState<Record<string, string[]>>({});
  const [expandedAssessments, setExpandedAssessments] = useState<Record<string, boolean>>({});
  const [lessonQuizState, setLessonQuizState] = useState<Record<string, LessonQuizState>>({});
  const [lessonBusyState, setLessonBusyState] = useState<Record<string, LessonBusyPhase>>({});

  const statePath = (location.state as PathState | null)?.path;

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    if (!pathId) {
      setError('Không tìm thấy lộ trình');
      setLoading(false);
      return;
    }

    if (statePath) {
      setPath(statePath);
      setLoading(false);
      return;
    }

    const loadPath = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await learningPathService.getLearningPathById(pathId);
        if (response?.path) {
          setPath(response.path as LearningPath);
        } else {
          setError('Không tìm thấy lộ trình');
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Không thể tải lộ trình';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadPath();
  }, [user, navigate, pathId, statePath]);

  const steps = useMemo(() => path?.recommended_path || [], [path]);
  const chapters = useMemo(() => path?.curriculum || [], [path]);
  const curriculumNotice = useMemo(() => {
    if (!path) {
      return null;
    }
    if (path.curriculum_source === 'fallback') {
      return (
        path.curriculum_notice ||
        'AI hiện chưa phản hồi ổn định. Hệ thống đã dùng lộ trình dự phòng để bạn vẫn có thể bắt đầu học.'
      );
    }
    return null;
  }, [path]);

  useEffect(() => {
    if (!path?.curriculum) {
      return;
    }

    setLessonAnswers((prev) => {
      const next = { ...prev };
      for (const chapter of path.curriculum || []) {
        for (const lesson of chapter.lessons || []) {
          const required = lesson.assessment?.required_questions || 10;
          const existing = next[lesson.lesson_id] || [];
          const normalized = Array.from({ length: required }, (_, idx) => existing[idx] || '');
          next[lesson.lesson_id] = normalized;
        }
      }
      return next;
    });
  }, [path?.curriculum]);

  const handleBack = () => navigate('/learning-path');

  const handleViewResources = (conceptId: number) => {
    navigate(`/resources?concept=${conceptId}`);
  };

  const handleAskAI = (conceptId: number) => {
    navigate(`/ai-tutor?concept=${conceptId}`);
  };

  const handleSearchResource = (title: string) => {
    const query = encodeURIComponent(title);
    navigate(`/resources?q=${query}`);
  };

  const handleLessonStatusUpdate = async (
    lessonId: string,
    status: 'not_started' | 'in_progress' | 'complete'
  ) => {
    if (!path?.path_id) {
      return;
    }

    try {
      const response = await learningPathService.updateLessonProgress({
        path_id: path.path_id,
        lesson_id: lessonId,
        status,
      });
      setError(null);

      setPath((prev) => {
        if (!prev?.curriculum) {
          return prev;
        }

        const updatedCurriculum = prev.curriculum.map((chapter) => ({
          ...chapter,
          lessons: chapter.lessons.map((lesson) => {
            if (lesson.lesson_id !== lessonId) {
              return lesson;
            }

            const required = lesson.assessment?.required_questions || 10;
            const attempted = response.assessment_result?.attempted_questions ?? lesson.assessment?.attempted_questions ?? 0;
            const correct = response.assessment_result?.correct_answers ?? lesson.assessment?.correct_answers ?? 0;
            const minRequired = response.assessment_result?.min_correct_required ?? lesson.assessment?.min_correct_required ?? 7;
            const passed = response.assessment_result?.passed ?? lesson.assessment?.passed ?? false;
            const scorePercent = response.assessment_result?.score_percent ?? lesson.assessment?.score_percent ?? 0;
            const questionResults = response.assessment_result?.question_results ?? lesson.assessment?.question_results ?? [];
            const existingQuestions = lesson.assessment?.questions || [];

            return {
              ...lesson,
              status: response.status,
              assessment: {
                required_questions: required,
                attempted_questions: attempted,
                completed: response.status === 'complete',
                correct_answers: correct,
                min_correct_required: minRequired,
                passed,
                score_percent: scorePercent,
                question_results: questionResults,
                questions: existingQuestions,
              },
            };
          }),
        }));

        return {
          ...prev,
          curriculum: updatedCurriculum,
        };
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể cập nhật tiến độ bài học';
      setError(message);
    }
  };

  const handleAnswerChange = (lessonId: string, index: number, value: OptionKey) => {
    setLessonAnswers((prev) => {
      const current = prev[lessonId] || [];
      const nextAnswers = [...current];
      nextAnswers[index] = value;
      return {
        ...prev,
        [lessonId]: nextAnswers,
      };
    });
  };

  const setLessonBusyPhase = (lessonId: string, phase: LessonBusyPhase) => {
    setLessonBusyState((prev) => ({
      ...prev,
      [lessonId]: phase,
    }));
  };

  const getLessonBusyPhase = (lessonId: string): LessonBusyPhase => lessonBusyState[lessonId] || 'idle';

  const getBusyMessage = (phase: LessonBusyPhase) => {
    switch (phase) {
      case 'creating':
        return 'Hệ thống đang tạo bộ câu hỏi cho bài học này...';
      case 'submitting':
        return 'Đang chấm điểm và hiển thị kết quả...';
      case 'restarting':
        return 'Đang tạo một lượt bài mới từ question bank...';
      default:
        return '';
    }
  };

  const getRequiredQuestionCount = (lesson: LessonItem) =>
    lessonQuizState[lesson.lesson_id]?.questions.length || lesson.assessment?.required_questions || 10;

  const getAnsweredCount = (lesson: LessonItem) => {
    const required = getRequiredQuestionCount(lesson);
    const answers = lessonAnswers[lesson.lesson_id] || [];
    return answers.slice(0, required).filter((answer) => answer.trim()).length;
  };

  const getAnsweredProgress = (lesson: LessonItem) => {
    const required = getRequiredQuestionCount(lesson);
    return Math.round((getAnsweredCount(lesson) / Math.max(required, 1)) * 100);
  };

  const getConfidenceTone = (confidenceScore: number) => {
    if (confidenceScore >= 0.8) {
      return {
        bar: 'bg-green-500',
        badge: 'bg-green-100 text-green-700 border-green-200',
      };
    }
    if (confidenceScore >= 0.6) {
      return {
        bar: 'bg-amber-400',
        badge: 'bg-amber-100 text-amber-700 border-amber-200',
      };
    }
    return {
      bar: 'bg-red-400',
      badge: 'bg-red-100 text-red-700 border-red-200',
    };
  };

  const updateLessonAssessmentSnapshot = (
    lessonId: string,
    quizState: Partial<LessonQuizState>,
    statusOverride?: 'not_started' | 'in_progress' | 'complete'
  ) => {
    setPath((prev) => {
      if (!prev?.curriculum) {
        return prev;
      }

      return {
        ...prev,
        curriculum: prev.curriculum.map((chapter) => ({
          ...chapter,
          lessons: chapter.lessons.map((lesson) => {
            if (lesson.lesson_id !== lessonId) {
              return lesson;
            }

            const currentQuiz = lessonQuizState[lessonId];
            const mergedQuestions = quizState.questions ?? currentQuiz?.questions ?? [];
            const mergedResults = quizState.results ?? currentQuiz?.results ?? [];
            const requiredQuestions = mergedQuestions.length || lesson.assessment?.required_questions || 10;
            const passThreshold = quizState.passThresholdCount
              ?? currentQuiz?.passThresholdCount
              ?? lesson.assessment?.min_correct_required
              ?? 8;
            const correctCount = quizState.correctCount
              ?? currentQuiz?.correctCount
              ?? lesson.assessment?.correct_answers
              ?? 0;
            const scorePercent = quizState.score
              ?? currentQuiz?.score
              ?? lesson.assessment?.score_percent
              ?? 0;
            const passed = quizState.isPassed
              ?? currentQuiz?.isPassed
              ?? lesson.assessment?.passed
              ?? false;

            return {
              ...lesson,
              status: statusOverride ?? lesson.status,
              assessment: {
                required_questions: requiredQuestions,
                attempted_questions: mergedResults.length > 0 ? requiredQuestions : 0,
                completed: statusOverride === 'complete' || passed,
                correct_answers: correctCount,
                min_correct_required: passThreshold,
                passed,
                score_percent: scorePercent,
                question_results: mergedResults.map((result) => ({
                  question_id: result.question_id,
                  selected_answer: result.selected_answer,
                  is_correct: result.is_correct,
                  correct_option: result.correct_option,
                  correct_answer: result.answer,
                  explanation: result.answer,
                })),
                questions: mergedQuestions.map((question) => ({
                  question_id: question.question_id,
                  question: question.question_text,
                  answer: '',
                  explanation: '',
                  difficulty: 'medium' as const,
                  concept: question.concept,
                  options: question.options,
                  correct_option: 'A' as const,
                })),
              },
            };
          }),
        })),
      };
    });
  };

  const createQuizAttempt = async (lesson: LessonItem, phase: LessonBusyPhase = 'creating') => {
    setLessonBusyPhase(lesson.lesson_id, phase);
    try {
      const attempt: LessonQuizAttemptResponse = await learningPathService.createLessonQuizAttempt(lesson.lesson_id);
      const nextQuizState: LessonQuizState = {
        attemptId: attempt.attempt_id,
        attemptNumber: attempt.attempt_number,
        questions: attempt.questions,
        results: [],
        passThresholdCount: attempt.pass_threshold_count,
        correctCount: 0,
        score: 0,
        confidenceScore: 0,
        isPassed: false,
      };

      setLessonQuizState((prev) => ({
        ...prev,
        [lesson.lesson_id]: nextQuizState,
      }));
      setLessonAnswers((prev) => ({
        ...prev,
        [lesson.lesson_id]: Array.from({ length: attempt.questions.length }, () => ''),
      }));
      updateLessonAssessmentSnapshot(lesson.lesson_id, nextQuizState, lesson.status === 'complete' ? 'complete' : 'in_progress');
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Khong the tao de bai tap';
      setError(message);
    } finally {
      setLessonBusyPhase(lesson.lesson_id, 'idle');
    }
  };

  const handleCompleteWithAssessment = async (lesson: LessonItem) => {
    const quizState = lessonQuizState[lesson.lesson_id];
    const required = quizState?.questions.length || lesson.assessment?.required_questions || 10;
    const answers = lessonAnswers[lesson.lesson_id] || [];
    const answered = answers.filter((item) => item.trim());

    if (answered.length < required) {
      setError(`Cần trả lời đủ ${required} câu trước khi hoàn thành bài học.`);
      return;
    }
    await handleSubmitAssessment(lesson, true);
  };

  const handleSubmitAssessment = async (lesson: LessonItem, markCompleteOnPass = false) => {
    const quizState = lessonQuizState[lesson.lesson_id];
    if (!quizState?.attemptId) {
      setError('Can tao de bai tap truoc khi nop bai.');
      return;
    }

    const answers = lessonAnswers[lesson.lesson_id] || [];
    const answerMap = quizState.questions.reduce<Record<string, string>>((acc, question, index) => {
      const selected = answers[index] || '';
      if (selected) {
        acc[question.question_id] = selected;
      }
      return acc;
    }, {});

    if (Object.keys(answerMap).length < quizState.questions.length) {
      setError(`Can tra loi du ${quizState.questions.length} cau truoc khi nop bai.`);
      return;
    }

    setLessonBusyPhase(lesson.lesson_id, 'submitting');
    try {
      const result = await learningPathService.submitLessonQuiz(quizState.attemptId, answerMap);
      const nextQuizState: LessonQuizState = {
        ...quizState,
        attemptNumber: result.attempt_number,
        results: result.results,
        passThresholdCount: result.pass_threshold_count,
        correctCount: result.correct_count,
        score: result.score,
        confidenceScore: result.confidence_score,
        isPassed: result.is_passed,
      };

      setLessonQuizState((prev) => ({
        ...prev,
        [lesson.lesson_id]: nextQuizState,
      }));

      const nextStatus = result.is_passed && markCompleteOnPass ? 'complete' : 'in_progress';
      updateLessonAssessmentSnapshot(lesson.lesson_id, nextQuizState, nextStatus);

      if (result.is_passed && path?.path_id) {
        await learningPathService.updateLessonProgress({
          path_id: path.path_id,
          lesson_id: lesson.lesson_id,
          status: 'complete',
        });
      }

      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Khong the nop bai tap';
      setError(message);
    } finally {
      setLessonBusyPhase(lesson.lesson_id, 'idle');
    }
  };

  const handleRestartAssessment = async (lesson: LessonItem) => {
    await createQuizAttempt(lesson, 'restarting');
  };

  const toggleAssessment = async (lesson: LessonItem) => {
    const isExpanded = !!expandedAssessments[lesson.lesson_id];
    if (isExpanded) {
      setExpandedAssessments((prev) => ({
        ...prev,
        [lesson.lesson_id]: false,
      }));
      return;
    }

    setExpandedAssessments((prev) => ({
      ...prev,
      [lesson.lesson_id]: true,
    }));

    const quizState = lessonQuizState[lesson.lesson_id];
    if (!quizState?.attemptId) {
      await createQuizAttempt(lesson);
    }
  };

  const getLessonStatusLabel = (status?: string) => {
    switch (status) {
      case 'complete':
        return 'Hoàn thành';
      case 'in_progress':
        return 'Đang học';
      default:
        return 'Chưa bắt đầu';
    }
  };

  const getLessonStatusClass = (status?: string) => {
    switch (status) {
      case 'complete':
        return 'bg-green-100 text-green-700 border-green-200';
      case 'in_progress':
        return 'bg-blue-100 text-blue-700 border-blue-200';
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200';
    }
  };

  return (
    <DashboardLayout>
      <div className="max-w-[1190px] mx-auto">
        <div className="flex items-center justify-between mt-[25px] mb-6">
          <h1 className="text-[25px] font-semibold text-secondary">Lộ trình chi tiết</h1>
          <button
            onClick={handleBack}
            className="bg-white border border-[#8f1025] text-[#8f1025] text-[13px] font-medium px-4 py-2 rounded-[10px] hover:bg-gray-50 transition-colors"
          >
            Quay lại
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center min-h-[300px]">
            <div className="text-center">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#8f1025] mx-auto mb-3"></div>
              <p className="text-[#8f1025]">Đang tải lộ trình...</p>
            </div>
          </div>
        ) : error ? (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-[12px]">
            {error}
          </div>
        ) : (
          <>
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-6 mb-8">
              <h2 className="text-[18px] font-semibold text-[#8f1025] mb-2">{path?.goal}</h2>
              <div className="text-[13px] text-[#555] flex flex-wrap gap-4">
                <span>Trình độ: {levelLabel(path?.level)}</span>
                {path?.generated_at && (
                  <span>Ngày tạo: {new Date(path.generated_at).toLocaleString()}</span>
                )}
                <span>Tổng bước: {steps.length}</span>
                {path?.curriculum_source && (
                  <span>Nguồn sinh: {path.curriculum_source === 'ai' ? 'AI' : 'Dự phòng'}</span>
                )}
              </div>
            </div>

            {curriculumNotice && (
              <div className="mb-6 rounded-[16px] border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
                <div className="font-semibold">AI chưa sẵn sàng cho lần tạo lộ trình này</div>
                <div className="mt-1">{curriculumNotice}</div>
              </div>
            )}

            {chapters.length > 0 ? (
              <div className="space-y-6">
                {chapters.map((chapter, chapterIndex) => (
                  <div
                    key={`${chapterIndex}-${chapter.title}`}
                    className="bg-white border border-[#ce6a86] rounded-[18px] p-6"
                  >
                    <div className="text-[14px] font-semibold text-[#8f1025] mb-4">
                      {chapterIndex + 1}. {chapter.title}
                    </div>
                    <div className="space-y-3">
                      {chapter.lessons.map((lesson, lessonIndex) => (
                        <div
                          key={`${chapterIndex}-${lessonIndex}`}
                          className="border border-[#f0c8d7] rounded-[14px] p-4"
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div>
                              <div className="text-[12px] text-[#8f1025] font-semibold mb-1">
                                Bài {lessonIndex + 1}
                              </div>
                              <h3 className="text-[15px] font-semibold text-[#333]">
                                {lesson.title}
                              </h3>
                              {lesson.summary && (
                                <p className="text-[12px] text-[#666] mt-1">{lesson.summary}</p>
                              )}
                            </div>
                            <div className="flex flex-col items-end gap-2">
                              <span
                                className={`text-[11px] px-2 py-1 rounded-full border ${getLessonStatusClass(lesson.status)}`}
                              >
                                {getLessonStatusLabel(lesson.status)}
                              </span>
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  onClick={() => handleLessonStatusUpdate(lesson.lesson_id, 'in_progress')}
                                  disabled={getLessonBusyPhase(lesson.lesson_id) !== 'idle'}
                                  className="text-[11px] px-2 py-1 rounded-[8px] border border-[#8f1025] text-[#8f1025] hover:bg-[#f7dfed] disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                  Đang học
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleCompleteWithAssessment(lesson)}
                                  disabled={getLessonBusyPhase(lesson.lesson_id) !== 'idle'}
                                  className="text-[11px] px-2 py-1 rounded-[8px] bg-[#8f1025] text-white hover:bg-[#7a0e20] disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                  {getLessonBusyPhase(lesson.lesson_id) === 'submitting'
                                    ? 'Đang chấm...'
                                    : `Hoàn thành (${getRequiredQuestionCount(lesson)} câu)`}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => toggleAssessment(lesson)}
                                  disabled={getLessonBusyPhase(lesson.lesson_id) === 'submitting'}
                                  className="text-[11px] px-2 py-1 rounded-[8px] border border-[#ce6a86] text-[#8f1025] hover:bg-[#fdf3f7] disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                  {getLessonBusyPhase(lesson.lesson_id) === 'creating'
                                    ? 'Đang tạo đề'
                                    : getLessonBusyPhase(lesson.lesson_id) === 'restarting'
                                      ? 'Đang tạo đề mới'
                                      : expandedAssessments[lesson.lesson_id]
                                        ? 'Ẩn bài tập'
                                        : 'Làm bài tập'}
                                </button>
                              </div>
                            </div>
                          </div>

                          {lesson.assessment && (
                            <div className="mt-3 rounded-[12px] border border-[#f0c8d7] bg-[#fff8fb] p-3">
                              <p className="text-[12px] font-semibold text-[#8f1025]">
                                Bài tập bắt buộc: {lesson.assessment.attempted_questions || 0}/{lesson.assessment.required_questions || 10} câu
                              </p>
                              <p className="text-[11px] text-[#666] mt-1">
                                Cần hoàn thành đủ {lesson.assessment.required_questions || 10} câu và đạt tối thiểu {lesson.assessment.min_correct_required || 7} câu đúng để chuyển trạng thái sang Hoàn thành.
                              </p>
                              <p className="text-[11px] text-[#4a4a4a] mt-1">
                                Kết quả hiện tại: {lesson.assessment.correct_answers || 0}/{lesson.assessment.required_questions || 10} câu đúng ({lesson.assessment.score_percent || 0}%)
                              </p>
                              <div className="mt-3">
                                <div className="flex items-center justify-between text-[11px] text-[#8f1025] font-medium">
                                  <span>Đã trả lời {getAnsweredCount(lesson)}/{getRequiredQuestionCount(lesson)} câu</span>
                                  <span>{getAnsweredProgress(lesson)}%</span>
                                </div>
                                <div className="mt-1 h-2 overflow-hidden rounded-full bg-[#f3d7e3]">
                                  <div
                                    className="h-full rounded-full bg-[#8f1025] transition-all duration-300"
                                    style={{ width: `${getAnsweredProgress(lesson)}%` }}
                                  />
                                </div>
                              </div>
                              {!!lessonQuizState[lesson.lesson_id]?.confidenceScore && (
                                <div className="mt-3 rounded-[10px] border border-[#f0c8d7] bg-white p-3">
                                  <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div>
                                      <p className="text-[11px] text-[#666]">Confidence score</p>
                                      <div className="mt-1 flex items-center gap-2">
                                        <span className={`rounded-full border px-2 py-1 text-[11px] font-medium ${getConfidenceTone(lessonQuizState[lesson.lesson_id].confidenceScore).badge}`}>
                                          {Math.round(lessonQuizState[lesson.lesson_id].confidenceScore * 100)}%
                                        </span>
                                        <span className="text-[11px] text-[#666]">
                                          Attempt #{lessonQuizState[lesson.lesson_id].attemptNumber}
                                        </span>
                                      </div>
                                    </div>
                                    <div className="text-right text-[11px] text-[#666]">
                                      <p>Đúng: {lessonQuizState[lesson.lesson_id].correctCount}</p>
                                      <p>Sai: {Math.max(getRequiredQuestionCount(lesson) - lessonQuizState[lesson.lesson_id].correctCount, 0)}</p>
                                    </div>
                                  </div>
                                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#eef0f2]">
                                    <div
                                      className={`h-full rounded-full transition-all duration-300 ${getConfidenceTone(lessonQuizState[lesson.lesson_id].confidenceScore).bar}`}
                                      style={{ width: `${Math.round(lessonQuizState[lesson.lesson_id].confidenceScore * 100)}%` }}
                                    />
                                  </div>
                                </div>
                              )}
                              <p className={`text-[11px] mt-1 font-medium ${lesson.assessment.passed ? 'text-green-700' : 'text-amber-700'}`}>
                                {lesson.assessment.passed ? 'Đã đạt điều kiện hoàn thành bài học.' : 'Chưa đạt điều kiện điểm, vui lòng cải thiện câu trả lời.'}
                              </p>
                              {(lesson.assessment.question_results || []).length > 0 && (
                                <p className="text-[11px] text-[#666] mt-1">
                                  Đáp án và giải thích đã được hiển thị sau khi bạn nộp bài. Nếu chưa đạt điều kiện qua bài, bạn có thể làm một bộ câu hỏi mới và tiếp tục cho đến khi đủ điều kiện.
                                </p>
                              )}

                              {getLessonBusyPhase(lesson.lesson_id) !== 'idle' && (
                                <p className="text-[11px] text-[#8f1025] mt-1 font-medium">
                                  {getBusyMessage(getLessonBusyPhase(lesson.lesson_id))}
                                </p>
                              )}
                              {getLessonBusyPhase(lesson.lesson_id) === 'idle' &&
                                !(lesson.assessment.question_results || []).length &&
                                !!lessonQuizState[lesson.lesson_id]?.attemptId && (
                                  <p className="text-[11px] text-[#666] mt-1">
                                    Hoàn thành đủ số câu rồi bấm "Nộp và chấm điểm" để xem kết quả ngay.
                                  </p>
                                )}
                              {expandedAssessments[lesson.lesson_id] && (
                                <div className="mt-3 space-y-3 max-h-[360px] overflow-y-auto pr-1">
                                  {getLessonBusyPhase(lesson.lesson_id) !== 'idle' && (
                                    <div className="rounded-[10px] border border-[#f2d5dd] bg-white p-3 text-[12px] text-[#8f1025]">
                                      {getBusyMessage(getLessonBusyPhase(lesson.lesson_id))}
                                    </div>
                                  )}
                                  {(lesson.assessment.questions || []).map((question, qIndex) => {
                                    const shouldShowResults = (lesson.assessment?.question_results || []).length > 0;
                                    const result = (lesson.assessment?.question_results || []).find(
                                      (item: QuestionResult) => item.question_id === question.question_id
                                    );
                                    const answersLocked = shouldShowResults || getLessonBusyPhase(lesson.lesson_id) !== 'idle';

                                    return (
                                      <div key={question.question_id} className="rounded-[10px] border border-[#f2d5dd] bg-white p-3">
                                        <p className="text-[12px] font-medium text-[#333] mb-2">
                                          {qIndex + 1}. {question.question}
                                        </p>
                                        <div className="space-y-2">
                                          {(question.options || []).map((option) => {
                                            const selected = ((lessonAnswers[lesson.lesson_id] || [])[qIndex] || '') === option.key;
                                            const isCorrectOption = result?.correct_option === option.key;
                                            const isSelectedWrong = selected && !!result && !result.is_correct;

                                            let optionClass = 'border-[#e8d3da] bg-white';
                                            if (selected) {
                                              optionClass = 'border-[#8f1025] bg-[#fdf3f7]';
                                            }
                                            if (shouldShowResults && result && isCorrectOption) {
                                              optionClass = 'border-green-300 bg-green-50';
                                            }
                                            if (shouldShowResults && isSelectedWrong && selected) {
                                              optionClass = 'border-red-300 bg-red-50';
                                            }

                                            return (
                                              <label
                                                key={`${question.question_id}-${option.key}`}
                                                className={`flex items-start gap-2 rounded-[8px] border px-3 py-2 cursor-pointer ${optionClass}`}
                                              >
                                                <input
                                                  type="radio"
                                                name={`answer-${lesson.lesson_id}-${qIndex}`}
                                                value={option.key}
                                                checked={selected}
                                                onChange={() => handleAnswerChange(lesson.lesson_id, qIndex, option.key as OptionKey)}
                                                disabled={answersLocked}
                                                className="mt-0.5"
                                              />
                                              <span className="text-[12px] text-[#333]">
                                                <strong>{option.key}.</strong> {option.text}
                                              </span>
                                              </label>
                                            );
                                          })}
                                        </div>
                                        {shouldShowResults && result?.selected_answer && (
                                          <div className={`mt-3 rounded-[8px] px-3 py-2 text-[11px] ${
                                            result.is_correct
                                              ? 'bg-green-50 text-green-700 border border-green-200'
                                              : 'bg-red-50 text-red-700 border border-red-200'
                                          }`}>
                                            <p className="font-medium">
                                              {result.is_correct
                                                ? `Đúng. Bạn chọn ${result.selected_answer}.`
                                                : `Sai. Bạn chọn ${result.selected_answer}, đáp án đúng là ${result.correct_option}.`}
                                            </p>
                                            {result.explanation && (
                                              <p className="mt-1">{result.explanation}</p>
                                            )}
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                  <div className="pt-2">
                                    <div className="flex flex-wrap gap-2">
                                      <button
                                        type="button"
                                        onClick={() => handleSubmitAssessment(lesson)}
                                        disabled={(lesson.assessment.question_results || []).length > 0 || getLessonBusyPhase(lesson.lesson_id) !== 'idle'}
                                        aria-busy={getLessonBusyPhase(lesson.lesson_id) === 'submitting' ? 'true' : 'false'}
                                        className="text-[11px] px-3 py-2 rounded-[8px] border border-[#8f1025] text-[#8f1025] hover:bg-[#f7dfed] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                                      >
                                        Nộp và chấm điểm
                                      </button>
                                      {(lesson.assessment.question_results || []).length > 0 && (
                                        <button
                                          type="button"
                                          onClick={() => handleRestartAssessment(lesson)}
                                          disabled={getLessonBusyPhase(lesson.lesson_id) !== 'idle'}
                                          className="text-[11px] px-3 py-2 rounded-[8px] bg-[#8f1025] text-white hover:bg-[#7a0e20] disabled:opacity-50 disabled:cursor-not-allowed"
                                        >
                                          Làm lại bộ câu hỏi mới
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              )}
                            </div>
                          )}

                          {lesson.resources && lesson.resources.length > 0 && (
                            <div className="mt-3">
                              <p className="text-[12px] font-semibold text-[#8f1025] mb-2">Tài nguyên gợi ý</p>
                              <div className="space-y-2">
                                {lesson.resources.slice(0, 3).map((resource, resourceIndex) => (
                                  <button
                                    key={`${chapterIndex}-${lessonIndex}-${resourceIndex}`}
                                    type="button"
                                    onClick={() => handleSearchResource(resource)}
                                    className="w-full text-left px-3 py-2 bg-[#f7dfed] rounded-[10px] text-[12px] text-[#5b1724] hover:bg-[#f3cfe2] transition-colors"
                                  >
                                    {resource}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : steps.length === 0 ? (
              <div className="bg-yellow-50 border border-yellow-200 text-yellow-700 px-4 py-3 rounded-[12px]">
                Lộ trình chưa có bước nào. Hãy thử tạo lại lộ trình với mục tiêu khác.
              </div>
            ) : (
              <div className="space-y-4">
                {steps.map((step, index) => (
                  <div
                    key={`${step.concept_id}-${index}`}
                    className="bg-white border border-[#ce6a86] rounded-[16px] p-5"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-[13px] text-[#8f1025] font-semibold mb-1">
                          Bước {index + 1}
                        </div>
                        <h3 className="text-[16px] font-semibold text-[#333]">
                          {step.concept_name || 'Khái niệm'}
                        </h3>
                        <p className="text-[12px] text-[#666] mt-1">
                          Độ khó: {step.difficulty ?? 'N/A'} • Chế độ: {step.mode || 'normal'}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleViewResources(step.concept_id)}
                          className="bg-white border border-[#8f1025] text-[#8f1025] text-[12px] font-medium px-3 py-2 rounded-[10px] hover:bg-gray-50"
                        >
                          Tài nguyên
                        </button>
                        <button
                          onClick={() => handleAskAI(step.concept_id)}
                          className="bg-[#8f1025] text-white text-[12px] font-medium px-3 py-2 rounded-[10px] hover:bg-[#7a0e20]"
                        >
                          Hỏi AI
                        </button>
                      </div>
                    </div>

                    {step.resources && step.resources.length > 0 && (
                      <div className="mt-4">
                        <p className="text-[12px] font-semibold text-[#8f1025] mb-2">Tài nguyên gợi ý</p>
                        <div className="space-y-2">
                          {step.resources.slice(0, 3).map((resource: any, resourceIndex: number) => (
                            <div
                              key={`${step.concept_id}-res-${resourceIndex}`}
                              className="px-3 py-2 bg-[#f7dfed] rounded-[10px] text-[12px] text-[#5b1724]"
                            >
                              {resource.title || 'Tài nguyên'}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
