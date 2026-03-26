import { apiClient } from '../utils/apiClient';
import type {
  AdminOverviewMetrics,
  AdminRecommendationMetrics,
  AdminRetentionMetrics,
  LearnerAnalyticsDashboard,
  SystemPerformanceMetrics,
} from '../types/analytics';

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export const analyticsService = {
  async getLearnerDashboard(userId: string): Promise<LearnerAnalyticsDashboard> {
    return (await apiClient.get(
      `/analytics/learner/${encodeURIComponent(userId)}`,
    )) as LearnerAnalyticsDashboard;
  },

  async getAdminOverview(): Promise<AdminOverviewMetrics> {
    return (await apiClient.get('/analytics/admin/overview')) as AdminOverviewMetrics;
  },

  async getAdminRetention(): Promise<AdminRetentionMetrics> {
    return (await apiClient.get('/analytics/admin/retention')) as AdminRetentionMetrics;
  },

  async getAdminRecommendation(): Promise<AdminRecommendationMetrics> {
    return (await apiClient.get('/analytics/admin/recommendation')) as AdminRecommendationMetrics;
  },

  async getSystemPerformance(): Promise<SystemPerformanceMetrics> {
    return (await apiClient.get('/analytics/system/performance')) as SystemPerformanceMetrics;
  },

  formatPercent(value: number): string {
    if (!Number.isFinite(value)) {
      return '0%';
    }
    return `${(value * 100).toFixed(1)}%`;
  },

  safeMetric(value: unknown, fallback = 0): number {
    const record = asRecord({ value });
    const numeric = Number(record.value);
    return Number.isFinite(numeric) ? numeric : fallback;
  },
};
