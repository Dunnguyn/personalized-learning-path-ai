import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
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
  const [selectedConcept, setSelectedConcept] = useState<ConceptWithProgress | null>(null);
  const [showCreatePath, setShowCreatePath] = useState(false);
  const [pathForm, setPathForm] = useState({ goal: '', level: 'beginner' as const });
  const [generatingPath, setGeneratingPath] = useState(false);
  const [currentPath, setCurrentPath] = useState<LearningPath | null>(null);

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
      
      // Try to get recent learning path
      const history = await learningPathService.getLearningPathHistory(user.user_id);
      if (history && history.length > 0) {
        setCurrentPath(history[0] as any);
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
    if (!user || !pathForm.goal.trim()) {
      setError('Please enter a learning goal');
      return;
    }

    setGeneratingPath(true);
    setError(null);

    try {
      const result = await learningPathService.generateLearningPath({
        user_id: user.user_id,
        goal: pathForm.goal,
        level: pathForm.level,
      });

      setCurrentPath(result);
      
      // Update concepts with new path info
      const updatedConcepts = concepts.map((c) => {
        const pathItem = result.recommended_path.find((p) => p.concept_id === c.concept_id);
        return pathItem ? { ...c, ...pathItem } : c;
      });
      
      setConcepts(updatedConcepts);
      setShowCreatePath(false);
      setPathForm({ goal: '', level: 'beginner' });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error generating learning path';
      setError(message);
      console.error('Error generating path:', err);
    } finally {
      setGeneratingPath(false);
    }
  };

  const handleStartConcept = async (conceptId: number) => {
    if (!user) return;
    try {
      await learningPathService.updateConceptProgress({
        user_id: user.user_id,
        concept_id: conceptId,
        mastery: 0.05,
        confidence: 0.3,
        total_attempts: 1,
      });
      
      // Refresh data
      await fetchLearningPath();
    } catch (err) {
      console.error('Error starting concept:', err);
    }
  };

  const handleViewResources = (conceptId: number) => {
    navigate(`/resources?concept=${conceptId}`);
  };

  const handleAskAI = (conceptId: number) => {
    navigate(`/ai-tutor?concept=${conceptId}`);
  };

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'complete':
        return 'bg-green-100 border-green-300 text-green-800';
      case 'in_progress':
        return 'bg-blue-100 border-blue-300 text-blue-800';
      case 'proficient':
        return 'bg-cyan-100 border-cyan-300 text-cyan-800';
      case 'not_started':
        return 'bg-gray-100 border-gray-300 text-gray-800';
      default:
        return 'bg-gray-100 border-gray-300 text-gray-800';
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

  const getDifficultyColor = (difficulty: number) => {
    if (difficulty === 1) return 'text-green-600';
    if (difficulty === 2) return 'text-yellow-600';
    if (difficulty === 3) return 'text-orange-600';
    return 'text-red-600';
  };

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

        {loading ? (
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#8f1025] mx-auto mb-4"></div>
              <p className="text-[#8f1025]">Đang tải lộ trình học tập...</p>
            </div>
          </div>
        ) : (
          <>
            {currentPath && (
              <div className="bg-blue-50 border border-blue-200 rounded-[12px] p-4 mb-[40px] text-[13px]">
                <p className="font-medium text-blue-900">📌 Lộ trình hiện tại:</p>
                <p className="text-blue-800 mt-1">{currentPath.goal}</p>
                <p className="text-blue-700 text-[12px] mt-1">
                  Cấp độ: <span className="font-medium">{currentPath.level}</span> • Cập nhật:{' '}
                  <span className="font-medium">
                    {new Date(currentPath.generated_at).toLocaleDateString('vi-VN')}
                  </span>
                </p>
              </div>
            )}
          </>
        )}

      {/* Create Path Form */}
        {showCreatePath && !loading && (
          <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 mb-[40px]">
            <h2 className="text-[18px] font-semibold text-[#8f1025] mb-6">Tạo lộ trình học tập mới</h2>
            <form onSubmit={handleGeneratePath} className="space-y-5">
              <div>
                <label className="block text-[14px] font-medium text-[#8f1025] mb-2">
                  Chủ đề / Mục tiêu
                </label>
                <input
                  type="text"
                  value={pathForm.goal}
                  onChange={(e) => setPathForm({ ...pathForm, goal: e.target.value })}
                  placeholder="VD: Master Python Backend Development"
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[14px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                  required
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
          {/* Left: Concept Graph */}
          <div className="col-span-2">
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-[30px]">
              <h2 className="text-[18px] font-semibold text-[#8f1025] mb-6 flex items-center gap-2">
                <span className="w-[3px] h-[24px] bg-[#8f1025]" />
                Graph Lộ trình học tập
              </h2>

              {/* Concept Flow */}
              <div className="space-y-[40px]">
                {concepts.map((concept, index) => (
                  <div key={concept.concept_id}>
                    {/* Concept Card */}
                    <div
                      onClick={() => setSelectedConcept(concept)}
                      className={`border-2 rounded-[16px] p-[20px] cursor-pointer transition-all duration-200 ${getStatusColor(
                        concept.status
                      )} ${
                        selectedConcept?.concept_id === concept.concept_id
                          ? 'ring-2 ring-offset-2 ring-[#8f1025]'
                          : 'hover:shadow-lg'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-[16px] font-semibold">{concept.concept_name}</h3>
                        <span
                          className={`text-[12px] font-medium ${getDifficultyColor(concept.difficulty)}`}
                        >
                          {getDifficultyText(concept.difficulty)}
                        </span>
                      </div>

                      {/* Progress bar */}
                      <div className="mb-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-[6px] bg-gray-300 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-[#8f1025] transition-all duration-300"
                              style={{ width: `${(concept.mastery || 0) * 100}%` }}
                            />
                          </div>
                          <span className="text-[12px] font-medium">
                            {Math.round((concept.mastery || 0) * 100)}%
                          </span>
                        </div>
                      </div>

                      {/* Status */}
                      <p className="text-[13px] font-medium mb-2">{getStatusText(concept.status)}</p>

                      {/* Mode Badge */}
                      {concept.mode && (
                        <span className="inline-block bg-white bg-opacity-50 text-[12px] px-3 py-1 rounded-full font-medium mt-2">
                          {concept.mode}
                        </span>
                      )}
                    </div>

                    {/* Arrow (if not last) */}
                    {index < concepts.length - 1 && (
                      <div className="flex justify-center py-4">
                        <svg
                          className="w-6 h-6 text-[#ce6a86]"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                        </svg>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-[30px] sticky top-[100px]">
              {selectedConcept ? (
                <>
                  <h3 className="text-[16px] font-semibold text-[#8f1025] mb-6">Chi tiết concept</h3>

                  {/* Concept Name */}
                  <div className="mb-5">
                    <p className="text-[12px] text-gray-600 font-medium mb-1">Tên</p>
                    <p className="text-[14px] font-semibold text-[#8f1025]">{selectedConcept.concept_name}</p>
                  </div>

                  {/* Status */}
                  <div className="mb-5">
                    <p className="text-[12px] text-gray-600 font-medium mb-1">Trạng thái</p>
                    <span
                      className={`inline-block px-3 py-1 rounded-full text-[12px] font-medium ${getStatusColor(
                        selectedConcept.status
                      )}`}
                    >
                      {getStatusText(selectedConcept.status)}
                    </span>
                  </div>

                  {/* Difficulty */}
                  <div className="mb-5">
                    <p className="text-[12px] text-gray-600 font-medium mb-1">Độ khó</p>
                    <p className={`text-[14px] font-semibold ${getDifficultyColor(selectedConcept.difficulty)}`}>
                      {getDifficultyText(selectedConcept.difficulty)}
                    </p>
                  </div>

                  {/* Mastery */}
                  <div className="mb-5">
                    <p className="text-[12px] text-gray-600 font-medium mb-2">Mức độ thành thạo</p>
                    <div className="w-full h-[8px] bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[#8f1025] transition-all duration-300"
                        style={{ width: `${(selectedConcept.mastery || 0) * 100}%` }}
                      />
                    </div>
                    <p className="text-[14px] font-semibold text-[#8f1025] mt-2">
                      {Math.round((selectedConcept.mastery || 0) * 100)}%
                    </p>
                  </div>

                  {/* Priority Score */}
                  {selectedConcept.priority_score !== undefined && (
                    <div className="mb-5">
                      <p className="text-[12px] text-gray-600 font-medium mb-1">Mức độ ưu tiên</p>
                      <p className="text-[14px] font-semibold text-[#8f1025]">
                        {(selectedConcept.priority_score * 100).toFixed(0)}%
                      </p>
                    </div>
                  )}

                  {/* Prerequisites */}
                  {selectedConcept.prerequisites && selectedConcept.prerequisites.length > 0 && (
                    <div className="mb-5">
                      <p className="text-[12px] text-gray-600 font-medium mb-2">Điều kiện tiên quyết</p>
                      <ul className="space-y-1">
                        {selectedConcept.prerequisites.map((prereq) => {
                          const prereqConcept = concepts.find((c) => c.concept_id === prereq);
                          return (
                            <li key={prereq} className="text-[12px] text-[#8f1025]">
                              • {prereqConcept?.concept_name || `Concept ${prereq}`}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}

                  {/* Bloom Level */}
                  {selectedConcept.bloom_level && (
                    <div className="mb-5">
                      <p className="text-[12px] text-gray-600 font-medium mb-1">Bloom Level</p>
                      <p className="text-[13px] text-[#8f1025]">{selectedConcept.bloom_level}</p>
                    </div>
                  )}

                  {/* Action Buttons */}
                  <div className="space-y-3 mt-8 pt-6 border-t border-[#e4b6d0]">
                    <button
                      onClick={() => handleStartConcept(selectedConcept.concept_id)}
                      className="w-full bg-[#8f1025] text-white text-[14px] font-medium py-2 rounded-[10px] hover:bg-[#7a0e20] transition-colors"
                    >
                      {selectedConcept.status === 'not_started' ? 'Bắt đầu học' : 'Tiếp tục học'}
                    </button>
                    <button
                      onClick={() => handleViewResources(selectedConcept.concept_id)}
                      className="w-full bg-white border border-[#8f1025] text-[#8f1025] text-[14px] font-medium py-2 rounded-[10px] hover:bg-gray-50 transition-colors"
                    >
                      📚 Xem tài liệu
                    </button>
                    <button
                      onClick={() => handleAskAI(selectedConcept.concept_id)}
                      className="w-full bg-white border border-[#8f1025] text-[#8f1025] text-[14px] font-medium py-2 rounded-[10px] hover:bg-gray-50 transition-colors"
                    >
                      🤖 Hỏi AI
                    </button>
                  </div>
                </>
              ) : (
                <div className="text-center py-12">
                  <p className="text-[14px] text-gray-500">Chọn một concept để xem chi tiết</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Statistics Section */}
        <div className="grid grid-cols-4 gap-[20px] mt-[40px]">
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Tổng Concept</p>
            <p className="text-[28px] font-bold text-[#8f1025]">{concepts.length}</p>
          </div>
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Đã hoàn thành</p>
            <p className="text-[28px] font-bold text-green-600">
              {concepts.filter((c) => c.status === 'complete').length}
            </p>
          </div>
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Đang học</p>
            <p className="text-[28px] font-bold text-blue-600">
              {concepts.filter((c) => c.status === 'in_progress').length}
            </p>
          </div>
          <div className="bg-white border border-[#ce6a86] rounded-[16px] p-[24px] text-center">
            <p className="text-[12px] text-gray-600 font-medium mb-2">Tiến độ</p>
            <p className="text-[28px] font-bold text-[#8f1025]">
              {concepts.length > 0
                ? Math.round(
                    (concepts.reduce((sum, c) => sum + (c.mastery || 0), 0) / concepts.length) *
                      100
                  )
                : 0}
              %
            </p>
          </div>
        </div>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
