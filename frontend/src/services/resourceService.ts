import { apiClient } from '@/utils/apiClient';
import type {
  IngestionJobStatus,
  Resource,
  SearchResponse,
  UploadResponse,
} from '../types/resource';
import {
  asRecord,
  normalizeIngestionJobStatus,
  normalizeResource,
  normalizeUploadPayload,
  transformToSearchResponse,
} from './parsers/resourceParser';

export type {
  IngestionJobStatus,
  Resource,
  SearchResponse,
  UploadResponse,
} from '../types/resource';

const DEFAULT_PAGE_SIZE = 10;
const PDF_UPLOAD_TIMEOUT = 60000;

function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  timeoutMessage: string = 'Request timeout',
): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error(timeoutMessage)), ms)),
  ]);
}

export const resourceService = {
  async searchResources(
    query: string,
    page: number = 1,
    size: number = DEFAULT_PAGE_SIZE,
  ): Promise<SearchResponse> {
    if (!query || query.trim().length === 0) {
      return {
        results: [],
        total: 0,
        page: 1,
        size,
      };
    }

    const endpoint = `/resources/search?q=${encodeURIComponent(query)}&page=${page}&size=${size}`;
    const response = await apiClient.get(endpoint);
    return transformToSearchResponse(response);
  },

  async getResourcesByConceptId(conceptId: number): Promise<Resource[]> {
    if (!conceptId || conceptId <= 0) {
      return [];
    }

    const response = await apiClient.get(`/resources?concept_id=${conceptId}`);
    return transformToSearchResponse(response).results;
  },

  async getAllResources(filters?: {
    topic?: string;
    level?: string;
    source?: string;
    page?: number;
    size?: number;
  }): Promise<SearchResponse> {
    const params = new URLSearchParams();

    if (filters?.topic) params.append('topic', filters.topic);
    if (filters?.level) params.append('level', filters.level);
    if (filters?.source) params.append('source', filters.source);
    if (filters?.page) params.append('page', filters.page.toString());
    if (filters?.size) params.append('size', filters.size.toString());

    const query = params.toString();
    const endpoint = query ? `/resources?${query}` : '/resources';
    const response = await apiClient.get(endpoint);
    return transformToSearchResponse(response);
  },

  async uploadPDF(
    file: File,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId?: number,
  ): Promise<UploadResponse> {
    try {
      if (!file) {
        throw new Error('Vui lòng chọn tệp PDF');
      }

      if (!topic || topic.trim().length === 0) {
        throw new Error('Vui lòng nhập chủ đề');
      }

      const maxSize = 100 * 1024 * 1024;
      if (file.size > maxSize) {
        throw new Error('Kích thước tệp vượt quá giới hạn 100MB');
      }

      const formData = new FormData();
      formData.append('file', file);
      formData.append('topic', topic.trim());
      formData.append('level', level);

      if (conceptId && conceptId > 0) {
        formData.append('concept_id', conceptId.toString());
      }

      const controller = new AbortController();
      const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const apiBasePath = import.meta.env.VITE_API_BASE_PATH || '/api';
      const normalizedBaseUrl = apiBaseUrl.replace(/\/$/, '');
      const normalizedBasePath = apiBasePath.startsWith('/') ? apiBasePath : `/${apiBasePath}`;

      const response = (await withTimeout(
        fetch(`${normalizedBaseUrl}${normalizedBasePath}/resources/import-pdf`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
          },
          body: formData,
          signal: controller.signal,
        }),
        PDF_UPLOAD_TIMEOUT,
        'Tải PDF quá lâu. Tệp có thể quá lớn hoặc quá phức tạp, vui lòng thử tệp nhỏ hơn.',
      )) as Response;

      if (!response.ok) {
        const errorData = asRecord(await response.json().catch(() => ({})));
        throw new Error(
          String(
            errorData.detail || errorData.message || `Tải tệp thất bại: ${response.statusText}`,
          ),
        );
      }

      const data = normalizeUploadPayload(await response.json());

      return {
        success: true,
        resource_id: data.resource_id,
        job_id: data.job_id,
        status: data.status,
        message: 'Tải PDF lên thành công',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Đã xảy ra lỗi không xác định';
      return {
        success: false,
        error: message,
      };
    }
  },

  async addYouTubeResource(
    url: string,
    title: string,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId?: number,
  ): Promise<UploadResponse> {
    try {
      if (!url || (!url.includes('youtube.com') && !url.includes('youtu.be'))) {
        throw new Error('Vui lòng nhập liên kết YouTube hợp lệ');
      }

      const response = normalizeUploadPayload(
        await apiClient.post('/resources/import-youtube', {
          url: url.trim(),
          title: title.trim(),
          topic: topic.trim(),
          level,
          concept_id: conceptId && conceptId > 0 ? conceptId : undefined,
        }),
      );

      return {
        success: true,
        resource_id: response.resource_id,
        job_id: response.job_id,
        status: response.status,
        message: 'Đã thêm tài nguyên YouTube thành công',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Không thể thêm tài nguyên YouTube';
      return {
        success: false,
        error: message,
      };
    }
  },

  async addWebResource(data: {
    title: string;
    content: string;
    topic: string;
    level: 'beginner' | 'intermediate' | 'advanced';
    url?: string;
    conceptId?: number;
  }): Promise<UploadResponse> {
    try {
      if (!data.title.trim()) {
        throw new Error('Vui lòng nhập tiêu đề');
      }
      if (!data.content.trim() || data.content.trim().length < 10) {
        throw new Error('Nội dung phải có ít nhất 10 ký tự');
      }
      if (!data.topic.trim()) {
        throw new Error('Vui lòng nhập chủ đề');
      }

      const response = normalizeUploadPayload(
        await apiClient.post('/resources', {
          title: data.title.trim(),
          content: data.content.trim(),
          source: 'web',
          type: 'text',
          topic: data.topic.trim(),
          level: data.level,
          url: data.url?.trim() || undefined,
          concept_id: data.conceptId && data.conceptId > 0 ? data.conceptId : undefined,
        }),
      );

      return {
        success: true,
        resource_id: response.resource_id,
        job_id: response.job_id,
        status: response.status,
        message: 'Đã thêm tài nguyên web thành công',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Không thể thêm tài nguyên web';
      return {
        success: false,
        error: message,
      };
    }
  },

  async deleteResource(_resourceId: string): Promise<{ success: boolean; error?: string }> {
    try {
      if (!_resourceId.trim()) {
        throw new Error('Thiếu mã tài nguyên');
      }

      await apiClient.delete(`/resources/${encodeURIComponent(_resourceId)}`);
      return {
        success: true,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Không thể xóa tài nguyên';
      return {
        success: false,
        error: message,
      };
    }
  },

  async getIngestionJobStatus(jobId: string): Promise<IngestionJobStatus> {
    if (!jobId.trim()) {
      throw new Error('Thiếu mã job xử lý tài nguyên');
    }

    return normalizeIngestionJobStatus(
      await apiClient.get(`/resources/jobs/${encodeURIComponent(jobId)}`),
    );
  },

  async waitForIngestionCompletion(
    jobId: string,
    options?: {
      intervalMs?: number;
      timeoutMs?: number;
    },
  ): Promise<IngestionJobStatus> {
    const intervalMs = options?.intervalMs ?? 1500;
    const timeoutMs = options?.timeoutMs ?? 45000;
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      const status = await this.getIngestionJobStatus(jobId);
      const normalizedStatus = String(status.status || '').toLowerCase();

      if (['completed', 'complete', 'done', 'success'].includes(normalizedStatus)) {
        return status;
      }

      if (['failed', 'error', 'cancelled'].includes(normalizedStatus)) {
        throw new Error(status.error || 'Xử lý tài nguyên thất bại');
      }

      await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
    }

    throw new Error('Xử lý tài nguyên mất quá nhiều thời gian. Vui lòng thử tải lại sau.');
  },

  async getResourceById(resourceId: string): Promise<Resource | null> {
    try {
      if (!resourceId) {
        throw new Error('Thiếu mã tài nguyên');
      }

      const response = await apiClient.get(`/resources/${encodeURIComponent(resourceId)}`);
      return normalizeResource(response);
    } catch (error) {
      console.error(`Error fetching resource ${resourceId}:`, error);
      return null;
    }
  },
};
