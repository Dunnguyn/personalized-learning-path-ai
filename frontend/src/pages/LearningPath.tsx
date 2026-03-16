import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import { SUBJECTS } from '../utils/subjects';
import type { ConceptNode, LearningPath } from '../services/learningPathService';

interface ConceptWithProgress extends ConceptNode {
  mastery?: number;
  status?: 'not_started' | 'in_progress' | 'proficient' | 'complete';
  prerequisites?: number[];
}

export default function LearningPath() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [concepts, setConcepts] = useState<ConceptWithProgress[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreatePath, setShowCreatePath] = useState(false);
  const [pathForm, setPathForm] = useState({
    subjectId: SUBJECTS[0]?.id ?? '',
    goalDetail: '',
    level: 'beginner' as const,
  });
  const [generatingPath, setGeneratingPath] = useState(false);
  const [learningPaths, setLearningPaths] = useState<LearningPath[]>([]);
  const [hoveredPathId, setHoveredPathId] = useState<string | null>(null);
  const [pathNotice, setPathNotice] = useState<string | null>(null);

  const buildGoal = (subjectId: string, goalDetail: string) => {
    const subject = SUBJECTS.find((item) => item.id === subjectId);
    const baseGoal = subject?.goal ?? '';
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

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }
    fetchLearningPath();
  }, [user, navigate]);

  const fetchLearningPath = async () => {
    if (!user) return;
    try {
      setLoading(true);
      setError(null);

      // Get user progress
      const progress = await learningPathService.getUserProgress(user.user_id);
      
      // Get concepts
      const allConcepts = await learningPathService.getConcepts();
      
      // Combine concepts with progress data
      const conceptsWithProgress = allConcepts.map((concept) => {
        const progressData = progress.summary?.concepts?.find(
          (p: any) => p.concept_id === concept.concept_id
        );
        
        return {
          ...concept,
          mastery: progressData?.mastery || 0,
          status: progressData?.status || 'not_started',
          prerequisites: concept.prerequisites || [],
        };
      });

      setConcepts(conceptsWithProgress);
      
      // Get all learning paths with full details
      const history = await learningPathService.getLearningPathHistory(user.user_id);
      if (history && history.length > 0) {
        const pathsWithDetails = await Promise.all(
          history.map(async (path) => {
            try {
              const detail = await learningPathService.getLearningPathById(path.path_id);
              const pathData = detail?.path ?? detail;
              return pathData as LearningPath;
            } catch (detailError) {
              console.error('Error fetching learning path detail:', detailError);
              return path as LearningPath;
            }
          })
        );
        setLearningPaths(pathsWithDetails);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error fetching learning path';
      setError(message);
      console.error('Error fetching learning path:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleGeneratePath = async (e: React.FormEvent) => {
    e.preventDefault();
    const goal = buildGoal(pathForm.subjectId, pathForm.goalDetail);
    if (!user || !goal) {
      setError('Vui lòng chọn môn học');
      return;
    }

    setGeneratingPath(true);
    setError(null);

    try {
      const result = await learningPathService.generateLearningPath({
        user_id: user.user_id,
        goal: goal,
        level: pathForm.level,
      });
      setPathNotice(
        result.curriculum_source === 'fallback'
          ? (result.curriculum_notice || 'AI hiện chưa phản hồi ổn định. Hệ thống đã dùng lộ trình dự phòng.')
          : null
      );

      // Add new path to the list (keep old paths)
      setLearningPaths([result, ...learningPaths]);
      
      // Update concepts with new path info
      const updatedConcepts = concepts.map((c) => {
        const pathItem = result.recommended_path.find((p) => p.concept_id === c.concept_id);
        return pathItem ? { ...c, ...pathItem } : c;
      });
      
      setConcepts(updatedConcepts);
      setShowCreatePath(false);
      setPathForm({
        subjectId: SUBJECTS[0]?.id ?? '',
        goalDetail: '',
        level: 'beginner',
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error generating learning path';
      setError(message);
      console.error('Error generating path:', err);
    } finally {
      setGeneratingPath(false);
    }
  };

  const getStatusText = (status?: string) => {
    switch (status) {
      case 'complete':
        return '✓ Hoàn thành';
      case 'in_progress':
        return '⟳ Đang học';
      case 'proficient':
        return '◆ Thành thạo';
      case 'not_started':
        return '◯ Chưa bắt đầu';
      default:
        return '◯ Chưa bắt đầu';
    }
  };
  void getStatusText;

  const getDifficultyColor = (difficulty: number) => {
    if (difficulty === 1) return 'text-green-600';
    if (difficulty === 2) return 'text-yellow-600';
    if (difficulty === 3) return 'text-orange-600';
    return 'text-red-600';
  };
  void getDifficultyColor;

  const getDifficultyText = (difficulty: number) => {
    switch (difficulty) {
      case 1:
        return 'Cơ bản';
      case 2:
        return 'Trung bình';
      case 3:
        return 'Nâng cao';
      case 4:
        return 'Chuyên sâu';
      default:
        return 'N/A';
    }
  };
  void getDifficultyText;

  const getChapterStatus = (lessons: Array<{ status?: string }>) => {
    if (!lessons.length) return 'Chưa bắt đầu';
    if (lessons.every((lesson) => lesson.status === 'complete')) return 'Hoàn thành';
    if (lessons.some((lesson) => lesson.status === 'in_progress')) return 'Đang học';
    return 'Chưa bắt đầu';
  };

  const hoveredPath = learningPaths.find(path => path.path_id === hoveredPathId);

  // Calculate statistics from all learning paths
  const calculateStatistics = () => {
    let totalLessons = 0;
    let completedLessons = 0;
    let inProgressLessons = 0;
    
    learningPaths.forEach(path => {
      if (path.curriculum) {
        path.curriculum.forEach(chapter => {
          if (chapter.lessons) {
            chapter.lessons.forEach(lesson => {
              totalLessons++;
              if (lesson.status === 'complete') {
                completedLessons++;
              } else if (lesson.status === 'in_progress') {
                inProgressLessons++;
              }
            });
          }
        });
      }
    });

    const progress = totalLessons > 0 ? Math.round((completedLessons / totalLessons) * 100) : 0;

    return {
      total: totalLessons,
      completed: completedLessons,
      inProgress: inProgressLessons,
      progress
    };
  };

  const stats = calculateStatistics();

  return (
    <DashboardLayout>
      <div className="max-w-[1190px]">
        {/* Page Title */}
        <h1 className="text-[25px] font-semibold text-[#8f1025] mb-[30px] mt-[25px]">
          Lộ trình học tập
        </h1>

        {/* Error Alert */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-[12px] mb-[40px] text-[14px]">
            ✕ {error}
          </div>
        )}

        {pathNotice && (
          <div className="bg-amber-50 border border-amber-200 text-amber-900 px-4 py-3 rounded-[12px] mb-[24px] text-[14px]">
            <span className="font-medium">AI chưa sẵn sàng cho lần tạo lộ trình này. </span>
            {pathNotice}
          </div>
        )}

        {/* Top Actions */}
        <div className="flex gap-4 mb-[40px]">
          <button
            onClick={() => setShowCreatePath(!showCreatePath)}
            className="bg-[#8f1025] text-white text-[14px] font-medium px-6 py-2 rounded-[12px] hover:bg-[#7a0e20] transition-colors duration-200"
          >
            + Tạo lộ trình mới
          </button>
          <button
            onClick={fetchLearningPath}
            disabled={loading}
            className="bg-white border border-[#ce6a86] text-[#8f1025] text-[14px] font-medium px-6 py-2 rounded-[12px] hover:bg-gray-50 disabled:opacity-50 transition-colors duration-200"
          >
            {loading ? 'Đang tải...' : 'Làm mới'}
          </button>
        </div>

        {loading && (
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#8f1025] mx-auto mb-4"></div>
              <p className="text-[#8f1025]">Đang tải lộ trình học tập...</p>
            </div>
          </div>
        )}

      {/* Create Path Form */}
        {showCreatePath && !loading && (
          <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 mb-[40px]">
            <h2 className="text-[18px] font-semibold text-[#8f1025] mb-6">Tạo lộ trình học tập mới</h2>
            <form onSubmit={handleGeneratePath} className="space-y-5">
              <div>
                <label className="block text-[14px] font-medium text-[#8f1025] mb-2">
                  Môn học
                </label>
                <select
                  value={pathForm.subjectId}
                  onChange={(e) => setPathForm({ ...pathForm, subjectId: e.target.value })}
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[14px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
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
                <label className="block text-[14px] font-medium text-[#8f1025] mb-2">
                  Mục tiêu chi tiết (tùy chọn)
                </label>
                <input
                  type="text"
                  value={pathForm.goalDetail}
                  onChange={(e) => setPathForm({ ...pathForm, goalDetail: e.target.value })}
                  placeholder="VD: backend, OOP, cấu trúc dữ liệu..."
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[14px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
              </div>

              <div>
                <label className="block text-[14px] font-medium text-[#8f1025] mb-2">
                  Cấp độ
                </label>
                <select
                  value={pathForm.level}
                  onChange={(e) =>
                    setPathForm({ ...pathForm, level: e.target.value as any })
                  }
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[14px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
              </div>

              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded-[10px] text-[13px]">
                  {error}
                </div>
              )}

              <div className="flex gap-3">
                <button
                  type="submit"
                  disabled={generatingPath}
                  className="bg-[#8f1025] text-white text-[14px] font-medium px-6 py-2 rounded-[10px] hover:bg-[#7a0e20] disabled:opacity-50 transition-colors"
                >
                  {generatingPath ? 'Đang tạo...' : 'Tạo lộ trình'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreatePath(false);
                    setError(null);
                  }}
                  className="bg-gray-100 text-[#8f1025] text-[14px] font-medium px-6 py-2 rounded-[10px] hover:bg-gray-200 transition-colors"
                >
                  Hủy
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Main Content */}
        {!loading && (
          <>
        <div className="grid grid-cols-3 gap-[30px]">
          {/* Left: Learning Paths Graph */}
          <div className="col-span-2">
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-[30px]">
              <h2 className="text-[18px] font-semibold text-[#8f1025] mb-6 flex items-center gap-2">
                <span className="w-[3px] h-[24px] bg-[#8f1025]" />
                Graph Lộ trình học tập
              </h2>

              {/* Learning Paths List */}
              {learningPaths.length === 0 ? (
                <div className="bg-white border border-[#ce6a86] rounded-[12px] p-[20px] text-center text-[13px] text-[#832e44]">
                  Chưa có lộ trình. Hãy tạo lộ trình mới để hiển thị tại đây.
                </div>
              ) : (
                <div className="space-y-[16px]">
                  {learningPaths.map((path) => (
                    <div
                      key={path.path_id}
                      onClick={() => navigate(`/learning-path/${path.path_id}`, { state: { path } })}
                      onMouseEnter={() => setHoveredPathId(path.path_id)}
                      onMouseLeave={() => setHoveredPathId(null)}
                      className="rounded-[10px] p-[18px] cursor-pointer transition-all duration-200 bg-[#de8fac] text-white hover:shadow-md relative"
                    >
                      <p className="text-[12px] font-medium mb-2">
                        {path.goal || 'Tên môn học - Mục tiêu'}
                      </p>
                      <p className="text-[10px] opacity-90">
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

          {/* Right: Hover Details */}
          <div>
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-[30px] sticky top-[100px]">
              <h3 className="text-[12px] font-semibold text-[#5b1724] mb-4">
                Thông tin chi tiết môn học
              </h3>

              {hoveredPath?.curriculum && hoveredPath.curriculum.length > 0 ? (
                <div className="space-y-4">
                  <div className="mb-4 pb-3 border-b border-[#ce6a86]">
                    <p className="text-[11px] font-semibold text-[#8f1025]">{hoveredPath.goal}</p>
                  </div>
                  {hoveredPath.curriculum.map((chapter, index) => {
                    const lessons = chapter.lessons || [];
                    const status = getChapterStatus(lessons);
                    return (
                      <div
                        key={`${chapter.title}-${index}`}
                        className="border border-[#ce6a86] rounded-[12px] p-4"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-[12px] font-semibold text-[#8f1025]">
                              {chapter.title || `Chương ${index + 1}`}
                            </p>
                            <p className="text-[10px] text-[#8f1025]/70 mt-1">{lessons.length} bài học</p>
                          </div>
                          <span className="text-[10px] px-2 py-0.5 rounded-full border border-[#8f1025] text-[#8f1025]">
                            {status}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-12">
                  <p className="text-[14px] text-gray-500">
                    {learningPaths.length > 0 
                      ? 'Di chuột vào lộ trình để xem chi tiết'
                      : 'Chưa có thông tin chương học.'}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Statistics Section */}
        <div className="grid grid-cols-4 gap-[20px] mt-[40px]">
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Tổng bài học</p>
            <p className="text-[28px] font-bold text-[#8f1025]">{stats.total}</p>
          </div>
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Đã hoàn thành</p>
            <p className="text-[28px] font-bold text-green-600">
              {stats.completed}
            </p>
          </div>
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Đang học</p>
            <p className="text-[28px] font-bold text-blue-600">
              {stats.inProgress}
            </p>
          </div>
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Tiến độ</p>
            <p className="text-[28px] font-bold text-[#8f1025]">
              {stats.progress}%
            </p>
          </div>
        </div>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
