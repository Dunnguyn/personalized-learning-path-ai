import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { dashboardService } from '../services/dashboardService';
import { learningPathService } from '../services/learningPathService';
import type { ProgressOverview, ConfidenceOverview, AdaptiveRecommendation } from '../types/dashboard';
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

      // Fetch all dashboard data in parallel
      const [progressData, confidenceData, recommendationsData, pathHistory] = await Promise.all([
        dashboardService.getProgressOverview(user.user_id),
        dashboardService.getConfidenceOverview(user.user_id),
        dashboardService.getAdaptiveRecommendations(user.user_id),
        learningPathService.getLearningPathHistory(user.user_id),
      ]);

      setProgressOverview(progressData);
      setConfidenceOverview(confidenceData);
      setRecommendations(recommendationsData);

      // Fetch full details for all learning paths
      if (pathHistory && pathHistory.length > 0) {
        const pathsWithDetails = await Promise.all(
          pathHistory.map(async (path) => {
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
      console.error('Error fetching dashboard data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  const handleViewResources = (conceptId: number) => {
    // TODO: Navigate to resources page filtered by concept
    navigate(`/resources?concept=${conceptId}`);
  };
  void handleViewResources;

  const handleAskAIForGoal = (goal: string, level?: string) => {
    const goalParam = encodeURIComponent(goal || '');
    const levelParam = level ? `&level=${encodeURIComponent(level)}` : '';
    const subjectMatch = SUBJECTS.find((subject) => goal?.startsWith(subject.goal));
    const subjectParam = subjectMatch ? `&subject=${encodeURIComponent(subjectMatch.id)}` : '';
    navigate(`/ai-tutor?goal=${goalParam}${levelParam}${subjectParam}`);
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

  // Calculate statistics from learning paths
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
  const overallProgress = stats.progress;
  const completedConcepts = stats.completed;
  const totalConcepts = stats.total;
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

            {/* Completed Lessons Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5 h-[180px]">
              <h3 className="text-[18px] font-medium text-[#8f1025] mb-4">Completed Lessons / Total Lessons</h3>
              <div className="space-y-3 text-[12px] italic text-[#8f1025]">
                <p className="text-[20px] font-semibold not-italic text-[#8f1025]">{completedConcepts} / {totalConcepts} bài học</p>
                <p className="mt-3">Đang học: {stats.inProgress} bài học</p>
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

        {/* Learning Lessons List Section */}
        <div>
          <div className="flex items-center gap-2 mb-[37px]">
            <div className="w-[3px] h-[28px] bg-[#8f1025] rounded-[5px]" />
            <h2 className="text-[18px] font-medium text-[#8f1025]">Danh sách</h2>
          </div>

          {/* Lesson Cards */}
          <div className="space-y-[24px]">
            {learningPaths.length === 0 ? (
              <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 text-center">
                <p className="text-[#8f1025]">Chưa có lộ trình nào. Hãy bắt đầu learning path của bạn!</p>
              </div>
            ) : (
              (() => {
                // For each path, find ONE lesson (in-progress or next to study)
                const lessonCards: JSX.Element[] = [];
                
                learningPaths.forEach((path) => {
                  if (path.curriculum) {
                    let selectedLesson: { chapter: any; lesson: any } | null = null;
                    
                    // First, try to find an in-progress lesson
                    for (const chapter of path.curriculum) {
                      if (chapter.lessons) {
                        const inProgressLesson = chapter.lessons.find(
                          (lesson) => lesson.status === 'in_progress'
                        );
                        if (inProgressLesson) {
                          selectedLesson = { chapter, lesson: inProgressLesson };
                          break;
                        }
                      }
                    }
                    
                    // If no in-progress lesson, find the first not-started lesson
                    if (!selectedLesson) {
                      for (const chapter of path.curriculum) {
                        if (chapter.lessons) {
                          const notStartedLesson = chapter.lessons.find(
                            (lesson) => lesson.status === 'not_started' || !lesson.status
                          );
                          if (notStartedLesson) {
                            selectedLesson = { chapter, lesson: notStartedLesson };
                            break;
                          }
                        }
                      }
                    }
                    
                    // Only create a card if we found a lesson to show
                    if (selectedLesson) {
                      lessonCards.push(
                        <div 
                          key={`${path.path_id}-${selectedLesson.chapter.title}-${selectedLesson.lesson.title}`}
                          className="bg-white border border-[#ce6a86] rounded-[20px] p-6 max-w-[800px] shadow-sm"
                        >
                          <h3 className="text-[18px] font-medium text-[#8f1025] mb-3">
                            {path.goal || 'Môn học - Mục tiêu'}
                          </h3>
                          
                          <p className="text-[14px] text-[#8f1025] mb-5">
                            Chương: {selectedLesson.chapter.title || 'Tên chương'} - Bài: {selectedLesson.lesson.title || 'Tên bài'}
                          </p>

                          {/* Action Buttons */}
                          <div className="flex gap-5">
                            <button 
                              onClick={() => handleViewResources(0)}
                              className="bg-[#8f1025] text-white text-[14px] font-medium px-6 py-1.5 rounded-[10px] hover:bg-[#7a0e20] active:scale-95 transition-all duration-200"
                            >
                              Xem tài liệu
                            </button>
                            <button 
                              onClick={() => handleAskAIForGoal(path.goal, path.level)}
                              className="bg-[#8f1025] text-white text-[14px] font-medium px-8 py-1.5 rounded-[10px] hover:bg-[#7a0e20] active:scale-95 transition-all duration-200"
                            >
                              Hỏi AI
                            </button>
                          </div>
                        </div>
                      );
                    }
                  }
                });

                return lessonCards.length > 0 ? lessonCards : (
                  <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 text-center">
                    <p className="text-[#8f1025]">Tất cả bài học đã hoàn thành! 🎉</p>
                  </div>
                );
              })()
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
