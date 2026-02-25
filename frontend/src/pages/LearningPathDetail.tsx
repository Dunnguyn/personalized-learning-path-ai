import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import type { LearningPath } from '../services/learningPathService';

interface PathState {
  path?: LearningPath;
}

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
      await learningPathService.updateLessonProgress({
        path_id: path.path_id,
        lesson_id: lessonId,
        status,
      });

      setPath((prev) => {
        if (!prev?.curriculum) {
          return prev;
        }

        const updatedCurriculum = prev.curriculum.map((chapter) => ({
          ...chapter,
          lessons: chapter.lessons.map((lesson) =>
            lesson.lesson_id === lessonId ? { ...lesson, status } : lesson
          ),
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
                      Chương {chapterIndex + 1}: {chapter.title}
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
                                  onClick={() => handleLessonStatusUpdate(lesson.lesson_id, 'complete')}
                                  className="text-[11px] px-2 py-1 rounded-[8px] bg-[#8f1025] text-white hover:bg-[#7a0e20]"
                                >
                                  Hoàn thành
                                </button>
                              </div>
                            </div>
                          </div>

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
