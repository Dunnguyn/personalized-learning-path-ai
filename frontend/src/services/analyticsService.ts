import { apiClient } from '../utils/apiClient';
import type {
  AdminAverageStudyHoursMetrics,
  AdminDashboardMetrics,
  AdminResearchDashboardMetrics,
  LearnerAnalyticsDashboard,
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

  async getAdminDashboard(): Promise<AdminDashboardMetrics> {
    return (await apiClient.get('/analytics/admin/dashboard')) as AdminDashboardMetrics;
  },

  async getAdminAverageStudyHours(): Promise<AdminAverageStudyHoursMetrics> {
    return (await apiClient.get(
      '/analytics/admin/average-study-hours',
    )) as AdminAverageStudyHoursMetrics;
  },

  async getAdminResearchDashboard(days = 30): Promise<AdminResearchDashboardMetrics> {
    return (await apiClient.get(
      `/analytics/admin/research-dashboard?days=${encodeURIComponent(String(days))}`,
    )) as AdminResearchDashboardMetrics;
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
