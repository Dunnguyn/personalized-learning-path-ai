import { apiClient } from '../utils/apiClient';
import type {
  AdaptiveRecommendation,
  ConfidenceOverview,
  ProgressOverview,
  ProgressSummary,
} from '../types/dashboard';

interface RecommendedConceptApiItem {
  concept_id: number;
  concept_name: string;
  difficulty?: number;
  topic?: string;
}

interface RecommendedConceptsResponse {
  success: boolean;
  user_id: string;
  recommended: RecommendedConceptApiItem[];
}

export interface RecommendedResourceItem {
  resource_id: number | string;
  title: string;
  source: string;
  level: string;
  topic: string;
  url?: string | null;
  reason: string;
  relevance_score: number;
}

export interface PersonalizedRecommendationResponse {
  user_id: number | string;
  goal: string;
  level: string;
  recommended_resources: RecommendedResourceItem[];
  completed_concepts: number;
  total_concepts: number;
  progress_percentage: number;
  message: string;
}

export interface GoalProgressConceptItem {
  concept_id: number;
  concept_name: string;
  difficulty: number;
  mastery: number;
  status: string;
}

export interface GoalProgressResponse {
  user_id: number | string;
  goal: string;
  concepts: GoalProgressConceptItem[];
  overall_mastery: number;
  message: string;
}

const buildReasonLines = (
  concept: RecommendedConceptApiItem,
  index: number
): string[] => [
  concept.topic
    ? `Nên ưu tiên tiếp tục với chủ đề ${concept.topic.toLowerCase()}.`
    : 'Đây là khái niệm phù hợp với tiến độ học tập hiện tại của bạn.',
  typeof concept.difficulty === 'number'
    ? `Độ khó tham chiếu: ${concept.difficulty}/10.`
    : 'Mức độ phù hợp để học tiếp ngay lúc này.',
  index === 0
    ? 'Được ưu tiên cao nhất từ dữ liệu tiến độ gần đây.'
    : 'Được đề xuất tiếp theo từ dữ liệu tiến độ gần đây.',
];

const mapRecommendedConcept = (
  concept: RecommendedConceptApiItem,
  index: number
): AdaptiveRecommendation => ({
  concept_id: concept.concept_id,
  concept_name: concept.concept_name,
  reasons: buildReasonLines(concept, index),
  priority_score: Math.max(0.2, 1 - index * 0.2),
});

const buildSummaryFallback = (
  summary: ProgressSummary
): AdaptiveRecommendation[] =>
  summary.concepts
    .filter((concept) => concept.mastery < 0.8 && concept.status !== 'not_started')
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 3)
    .map((concept, index) => ({
      concept_id: concept.concept_id,
      concept_name: concept.concept_name,
      reasons: [
        concept.mastery < 0.5
          ? 'Bạn đang cần củng cố thêm phần nền tảng của khái niệm này.'
          : 'Khái niệm này nên được ôn lại để tăng độ chắc chắn.',
        `Mức độ thành thạo hiện tại: ${Math.round(concept.mastery * 100)}%.`,
        index === 0
          ? 'Đây là ưu tiên cao nhất từ dữ liệu tiến độ hiện có.'
          : 'Đây là một trong những bước học tiếp theo phù hợp.',
      ],
      priority_score: 1 - concept.mastery,
    }));

export const dashboardService = {
  async getProgressOverview(userId?: string): Promise<ProgressOverview> {
    const endpoint = userId
      ? `/progress/overview?user_id=${userId}`
      : '/progress/overview';
    return apiClient.get(endpoint) as Promise<ProgressOverview>;
  },

  async getConfidenceOverview(userId?: string): Promise<ConfidenceOverview> {
    const endpoint = userId
      ? `/progress/confidence?user_id=${userId}`
      : '/progress/confidence';
    return apiClient.get(endpoint) as Promise<ConfidenceOverview>;
  },

  async getProgressSummary(
    userId?: string
  ): Promise<{ success: boolean; user_id: string; summary: ProgressSummary }> {
    const endpoint = userId
      ? `/progress/summary?user_id=${userId}`
      : '/progress/summary';
    return apiClient.get(endpoint) as Promise<{
      success: boolean;
      user_id: string;
      summary: ProgressSummary;
    }>;
  },

  async getAdaptiveRecommendations(userId: string): Promise<AdaptiveRecommendation[]> {
    try {
      const response = (await apiClient.get(
        `/ask/recommend-concepts?user_id=${encodeURIComponent(userId)}&limit=3`
      )) as RecommendedConceptsResponse;

      if (response.success && Array.isArray(response.recommended) && response.recommended.length > 0) {
        return response.recommended.map(mapRecommendedConcept);
      }

      const summary = await this.getProgressSummary(userId);
      return buildSummaryFallback(summary.summary);
    } catch (error) {
      console.error('Error fetching adaptive recommendations:', error);

      try {
        const summary = await this.getProgressSummary(userId);
        return buildSummaryFallback(summary.summary);
      } catch (fallbackError) {
        console.error('Error building fallback recommendations:', fallbackError);
        return [];
      }
    }
  },

  async updateProgress(data: {
    user_id: string;
    concept_id: number;
    mastery: number;
    confidence: number;
    total_attempts: number;
  }): Promise<any> {
    return apiClient.post('/progress/update', data);
  },

  async searchResources(query: string): Promise<any> {
    return apiClient.get(`/resources/search?q=${encodeURIComponent(query)}`);
  },

  async getPersonalizedResourceRecommendations(
    userId: string,
    goal: string,
    level: string,
    limit: number = 6
  ): Promise<PersonalizedRecommendationResponse> {
    const query = new URLSearchParams({
      user_id: userId,
      goal,
      level,
      limit: String(limit),
    });

    return apiClient.get(
      `/recommendations/resources?${query.toString()}`
    ) as Promise<PersonalizedRecommendationResponse>;
  },

  async getGoalLearningProgress(userId: string, goal: string): Promise<GoalProgressResponse> {
    const query = new URLSearchParams({
      user_id: userId,
      goal,
    });

    return apiClient.get(
      `/recommendations/progress?${query.toString()}`
    ) as Promise<GoalProgressResponse>;
  },
};
