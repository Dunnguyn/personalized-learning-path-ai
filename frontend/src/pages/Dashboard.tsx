import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { dashboardService } from '../services/dashboardService';
import type { ProgressOverview, ConfidenceOverview, ConceptProgress, AdaptiveRecommendation } from '../types/dashboard';

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [progressOverview, setProgressOverview] = useState<ProgressOverview | null>(null);
  const [confidenceOverview, setConfidenceOverview] = useState<ConfidenceOverview | null>(null);
  const [concepts, setConcepts] = useState<ConceptProgress[]>([]);
  const [recommendations, setRecommendations] = useState<AdaptiveRecommendation[]>([]);

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

      // Fetch all dashboard data in parallel
      const [progressData, confidenceData, summaryData, recommendationsData] = await Promise.all([
        dashboardService.getProgressOverview(user.user_id),
        dashboardService.getConfidenceOverview(user.user_id),
        dashboardService.getProgressSummary(user.user_id),
        dashboardService.getAdaptiveRecommendations(user.user_id),
      ]);

      setProgressOverview(progressData);
      setConfidenceOverview(confidenceData);
      setConcepts(summaryData.summary.concepts || []);
      setRecommendations(recommendationsData);
    } catch (err) {
      console.error('Error fetching dashboard data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  const getStatusDisplay = (status: string) => {
    const statusMap: Record<string, string> = {
      'not_started': 'not-started',
      'in_progress': 'in-progress',
      'proficient': 'completed',
      'complete': 'completed',
    };
    return statusMap[status] || status;
  };

  const handleViewResources = (conceptId: number) => {
    // TODO: Navigate to resources page filtered by concept
    navigate(`/resources?concept=${conceptId}`);
  };

  const handleAskAI = (conceptId: number) => {
    // TODO: Navigate to AI Tutor with concept context
    navigate(`/ai-tutor?concept=${conceptId}`);
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#8f1025] mx-auto mb-4"></div>
            <p className="text-[#8f1025]">Đang tải dữ liệu...</p>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <p className="text-red-600 mb-4">{error}</p>
            <button 
              onClick={fetchDashboardData}
              className="bg-[#8f1025] text-white px-6 py-2 rounded-lg hover:bg-[#7a0e20] transition-colors"
            >
              Thử lại
            </button>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  const overallProgress = progressOverview?.overall_progress_percent || 0;
  const completedConcepts = progressOverview?.summary.total_concepts_completed || 0;
  const totalConcepts = progressOverview?.summary.total_concepts_started || 0;
  const weeklyComparison = progressOverview?.weekly_comparison_percent || 0;
  
  const confidenceScore = confidenceOverview?.confidence || 0;
  const confidenceLevel = confidenceOverview?.level || "beginner";
  const confidenceTrend = confidenceOverview?.trend || "stable";

  const topRecommendation = recommendations[0];

  return (
    <DashboardLayout>
      <div className="max-w-[1190px]">
        {/* Page Title */}
        <h1 className="text-[25px] font-semibold text-secondary mb-[75px] mt-[25px]">Dashboard</h1>

        {/* Overview Section */}
        <div className="mb-[63px]">
          <div className="flex items-center gap-2 mb-[40px]">
            <div className="w-[3px] h-[28px] bg-[#8f1025] rounded-[5px]" />
            <h2 className="text-[18px] font-medium text-[#8f1025]">Tổng quan tiến độ</h2>
          </div>

          <div className="grid grid-cols-2 gap-x-[88px] gap-y-[37px]">
            {/* Overall Progress Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5 h-[180px] flex flex-col">
              <h3 className="text-[18px] font-medium text-[#8f1025] mb-3">Overall Progress (%)</h3>
              <div className="space-y-2 text-[12px] italic text-[#8f1025]">
                <p className="mb-1">% hoàn thành toàn bộ learning path</p>
                <div className="flex items-center gap-3 my-3">
                  <div className="flex-1 h-2.5 bg-gray-200 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-[#8f1025] rounded-full transition-all"
                      style={{ width: `${overallProgress}%` }}
                    />
                  </div>
                  <span className="text-[16px] font-semibold text-[#8f1025] not-italic min-w-[40px]">{overallProgress}%</span>
                </div>
                <p className="mt-2">
                  So sánh với tuần trước {weeklyComparison > 0 ? `(+${weeklyComparison}%)` : weeklyComparison < 0 ? `(${weeklyComparison}%)` : '(không đổi)'}
                </p>
              </div>
            </div>

            {/* Completed Concepts Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5 h-[180px]">
              <h3 className="text-[18px] font-medium text-[#8f1025] mb-4">Completed Concepts / Total Concepts</h3>
              <div className="space-y-3 text-[12px] italic text-[#8f1025]">
                <p className="text-[20px] font-semibold not-italic text-[#8f1025]">{completedConcepts} / {totalConcepts} concepts</p>
                <p className="mt-3">Estimated completion time còn lại</p>
              </div>
            </div>

            {/* Confidence Score Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5 h-[180px]">
              <h3 className="text-[18px] font-medium text-[#8f1025] mb-4">Confidence Score</h3>
              <div className="space-y-2 text-[12px] italic text-[#8f1025]">
                <p>Confidence: <span className="font-semibold text-[14px]">{confidenceScore}</span></p>
                <p>Level hiện tại: <span className="font-medium">{confidenceLevel}</span></p>
                <p>Xu hướng: <span className="text-green-600">↑</span> {confidenceTrend}</p>
              </div>
            </div>

            {/* Adaptive Recommendation Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5 h-[180px]">
              <h3 className="text-[18px] font-medium text-[#8f1025] mb-3">Adaptive Recommendation</h3>
              <div className="space-y-1 text-[12px] italic text-[#8f1025]">
                {topRecommendation ? (
                  <>
                    <p>Concept nên học tiếp theo</p>
                    <p className="font-semibold not-italic text-[14px] my-1">{topRecommendation.concept_name}</p>
                    <p className="mt-2">Lý do gợi ý:</p>
                    <ul className="list-disc pl-5 space-y-0.5 mt-1">
                      {topRecommendation.reasons.map((reason, index) => (
                        <li key={index} className="text-[11px]">{reason}</li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="not-italic">Chưa có gợi ý. Hãy bắt đầu học để nhận recommendations!</p>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Concepts List Section */}
        <div>
          <div className="flex items-center gap-2 mb-[37px]">
            <div className="w-[3px] h-[28px] bg-[#8f1025] rounded-[5px]" />
            <h2 className="text-[18px] font-medium text-[#8f1025]">Danh sách</h2>
          </div>

          {/* Concept Cards */}
          <div className="space-y-[24px]">
            {concepts.length === 0 ? (
              <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 text-center">
                <p className="text-[#8f1025]">Chưa có concepts nào. Hãy bắt đầu learning path của bạn!</p>
              </div>
            ) : (
              concepts.slice(0, 5).map((concept) => {
                const displayStatus = getStatusDisplay(concept.status);
                const progress = Math.round(concept.mastery * 100);
                
                return (
                  <div key={concept.concept_id} className="bg-white border border-[#ce6a86] rounded-[20px] p-6 w-[400px] shadow-sm">
                    <h3 className="text-[18px] font-medium text-[#8f1025] mb-5">{concept.concept_name}</h3>
                    
                    {/* Progress Bar */}
                    <div className="mb-5">
                      <p className="text-[16px] font-medium text-[#8f1025] mb-3">Progress bar</p>
                      <div className="flex items-center gap-3">
                        <div className="flex-1 h-2.5 bg-gray-200 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-[#8f1025] rounded-full transition-all duration-300"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                        <span className="text-[14px] font-semibold text-[#8f1025] min-w-[45px]">{progress}%</span>
                      </div>
                    </div>

                    {/* Status */}
                    <div className="mb-5">
                      <p className="text-[16px] font-medium text-[#8f1025] mb-2">Status:</p>
                      <ul className="list-disc pl-6 space-y-1 text-[15px]">
                        <li className={displayStatus === 'completed' ? 'text-[#8f1025] font-medium' : 'text-gray-400'}>
                          Completed
                        </li>
                        <li className={displayStatus === 'in-progress' ? 'text-[#8f1025] font-medium' : 'text-gray-400'}>
                          In progress
                        </li>
                        <li className={displayStatus === 'not-started' ? 'text-[#8f1025] font-medium' : 'text-gray-400'}>
                          Not started
                        </li>
                      </ul>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex gap-5 mt-4">
                      <button 
                        onClick={() => handleViewResources(concept.concept_id)}
                        className="bg-[#8f1025] text-white text-[14px] font-medium px-6 py-1.5 rounded-[10px] hover:bg-[#7a0e20] active:scale-95 transition-all duration-200"
                      >
                        Xem tài liệu
                      </button>
                      <button 
                        onClick={() => handleAskAI(concept.concept_id)}
                        className="bg-[#8f1025] text-white text-[14px] font-medium px-8 py-1.5 rounded-[10px] hover:bg-[#7a0e20] active:scale-95 transition-all duration-200"
                      >
                        Hỏi AI
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
