import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import type { LearningPath } from '../services/learningPathService';

interface PathState {
  path?: LearningPath;
}

type LessonItem = NonNullable<LearningPath['curriculum']>[number]['lessons'][number];
type OptionKey = 'A' | 'B' | 'C' | 'D';

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
    status: 'not_started' | 'in_progress' | 'complete',
    answeredQuestions?: string[]
  ) => {
    if (!path?.path_id) {
      return;
    }

    try {
      const response = await learningPathService.updateLessonProgress({
        path_id: path.path_id,
        lesson_id: lessonId,
        status,
        answered_questions: answeredQuestions,
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
                questions: lesson.assessment?.questions || [],
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

  const handleCompleteWithAssessment = async (lesson: LessonItem) => {
    const required = lesson.assessment?.required_questions || 10;
    const answers = lessonAnswers[lesson.lesson_id] || [];
    const answered = answers.filter((item) => item.trim());

    if (answered.length < required) {
      setError(`Cần trả lời đủ ${required} câu trước khi hoàn thành bài học.`);
      return;
    }

    await handleLessonStatusUpdate(lesson.lesson_id, 'complete', answers);
  };

  const handleSubmitAssessment = async (lesson: LessonItem) => {
    const answers = lessonAnswers[lesson.lesson_id] || [];
    await handleLessonStatusUpdate(lesson.lesson_id, 'in_progress', answers);
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
              </div>
            </div>

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
                                  className="text-[11px] px-2 py-1 rounded-[8px] border border-[#8f1025] text-[#8f1025] hover:bg-[#f7dfed]"
                                >
                                  Đang học
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleCompleteWithAssessment(lesson)}
                                  className="text-[11px] px-2 py-1 rounded-[8px] bg-[#8f1025] text-white hover:bg-[#7a0e20]"
                                >
                                  Hoàn thành (10 câu)
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setExpandedAssessments((prev) => ({
                                      ...prev,
                                      [lesson.lesson_id]: !prev[lesson.lesson_id],
                                    }))
                                  }
                                  className="text-[11px] px-2 py-1 rounded-[8px] border border-[#ce6a86] text-[#8f1025] hover:bg-[#fdf3f7]"
                                >
                                  {expandedAssessments[lesson.lesson_id] ? 'Ẩn bài tập' : 'Làm bài tập'}
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
                              <p className={`text-[11px] mt-1 font-medium ${lesson.assessment.passed ? 'text-green-700' : 'text-amber-700'}`}>
                                {lesson.assessment.passed ? 'Đã đạt điều kiện hoàn thành bài học.' : 'Chưa đạt điều kiện điểm, vui lòng cải thiện câu trả lời.'}
                              </p>

                              {expandedAssessments[lesson.lesson_id] && (
                                <div className="mt-3 space-y-3 max-h-[360px] overflow-y-auto pr-1">
                                  {(lesson.assessment.questions || []).map((question, qIndex) => (
                                    <div key={question.question_id} className="rounded-[10px] border border-[#f2d5dd] bg-white p-3">
                                      <p className="text-[12px] font-medium text-[#333] mb-2">
                                        {qIndex + 1}. {question.question}
                                      </p>
                                      <div className="space-y-2">
                                        {(question.options || []).map((option) => {
                                          const selected = ((lessonAnswers[lesson.lesson_id] || [])[qIndex] || '') === option.key;
                                          return (
                                            <label
                                              key={`${question.question_id}-${option.key}`}
                                              className={`flex items-start gap-2 rounded-[8px] border px-3 py-2 cursor-pointer ${selected ? 'border-[#8f1025] bg-[#fdf3f7]' : 'border-[#e8d3da] bg-white'}`}
                                            >
                                              <input
                                                type="radio"
                                                name={`answer-${lesson.lesson_id}-${qIndex}`}
                                                value={option.key}
                                                checked={selected}
                                                onChange={() => handleAnswerChange(lesson.lesson_id, qIndex, option.key as OptionKey)}
                                                className="mt-0.5"
                                              />
                                              <span className="text-[12px] text-[#333]">
                                                <strong>{option.key}.</strong> {option.text}
                                              </span>
                                            </label>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  ))}
                                  <div className="pt-2">
                                    <button
                                      type="button"
                                      onClick={() => handleSubmitAssessment(lesson)}
                                      className="text-[11px] px-3 py-2 rounded-[8px] border border-[#8f1025] text-[#8f1025] hover:bg-[#f7dfed]"
                                    >
                                      Nộp và chấm điểm
                                    </button>
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
