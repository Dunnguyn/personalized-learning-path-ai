import { apiClient } from '@/utils/apiClient';

export interface Resource {
  id?: string;
  resource_id?: string;
  _id?: string;
  title: string;
  content?: string;
  content_summary?: string;
  url?: string;
  source: string;
  type?: string;
  topic: string;
  level: 'beginner' | 'intermediate' | 'advanced';
  concept_id?: number;
  thumbnail?: string;
  pdf_file_path?: string;
  created_at?: string;
  video_id?: string;
  youtube_url?: string;
  video_metadata?: {
    thumbnail_url?: string;
    duration?: number;
    channel?: string;
  };
  score?: number;
  snippet?: string;
}

export interface SearchResponse {
  results: Resource[];
  total: number;
  page: number;
  size: number;
}

export interface UploadResponse {
  success: boolean;
  resource_id?: string;
  job_id?: string;
  status?: string;
  message?: string;
  error?: string;
}

const DEFAULT_PAGE_SIZE = 10;
const PDF_UPLOAD_TIMEOUT = 60000;

function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  timeoutMessage: string = 'Request timeout'
): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error(timeoutMessage)), ms)
    ),
  ]);
}

const normalizeLevel = (value: unknown): Resource['level'] => {
  if (value === 'intermediate' || value === 'advanced') {
    return value;
  }
  return 'beginner';
};

const normalizeResource = (resource: any): Resource => {
  const metadata = resource?.metadata ?? {};
  const videoMetadata = metadata?.video_metadata ?? resource?.video_metadata ?? {};

  return {
    ...resource,
    id: resource?.id ? String(resource.id) : undefined,
    resource_id: resource?.resource_id
      ? String(resource.resource_id)
      : resource?._id
      ? String(resource._id)
      : undefined,
    _id: resource?._id ? String(resource._id) : undefined,
    title: String(resource?.title ?? 'Tài nguyên'),
    content: resource?.content ? String(resource.content) : undefined,
    content_summary: resource?.content_summary ? String(resource.content_summary) : undefined,
    url: resource?.url ?? metadata?.url,
    source: String(resource?.source ?? 'manual'),
    type: resource?.type ? String(resource.type) : undefined,
    topic: String(resource?.topic ?? ''),
    level: normalizeLevel(resource?.level ?? metadata?.level),
    concept_id:
      typeof resource?.concept_id === 'number'
        ? resource.concept_id
        : typeof metadata?.concept_id === 'number'
        ? metadata.concept_id
        : undefined,
    thumbnail: resource?.thumbnail ?? metadata?.thumbnail,
    pdf_file_path: resource?.pdf_file_path ?? metadata?.pdf_file_path,
    created_at: resource?.created_at ? String(resource.created_at) : undefined,
    video_id: resource?.video_id ?? metadata?.video_id,
    youtube_url: resource?.youtube_url ?? metadata?.youtube_url ?? resource?.url,
    video_metadata: {
      thumbnail_url: videoMetadata?.thumbnail_url,
      duration: videoMetadata?.duration,
      channel: videoMetadata?.channel,
    },
    score: typeof resource?.score === 'number' ? resource.score : undefined,
    snippet: resource?.snippet ? String(resource.snippet) : undefined,
  };
};

function transformToSearchResponse(response: any): SearchResponse {
  if (Array.isArray(response)) {
    const results = response.map(normalizeResource);
    return {
      results,
      total: results.length,
      page: 1,
      size: DEFAULT_PAGE_SIZE,
    };
  }

  const rawResults =
    (response as any)?.resources ||
    (response as any)?.results ||
    (response as any)?.data ||
    [];

  return {
    results: Array.isArray(rawResults) ? rawResults.map(normalizeResource) : [],
    total: (response as any)?.total || (response as any)?.result_count || 0,
    page: (response as any)?.page || 1,
    size: (response as any)?.size || DEFAULT_PAGE_SIZE,
  };
}

export const resourceService = {
  async searchResources(
    query: string,
    page: number = 1,
    size: number = DEFAULT_PAGE_SIZE
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
    conceptId?: number
  ): Promise<UploadResponse> {
    try {
      if (!file) {
        throw new Error('File is required');
      }

      if (!topic || topic.trim().length === 0) {
        throw new Error('Topic is required');
      }

      const maxSize = 100 * 1024 * 1024;
      if (file.size > maxSize) {
        throw new Error('File size exceeds 100MB limit');
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
        'PDF upload timed out. The file may be too large or complex. Please try a smaller file.'
      )) as Response;

      if (!response.ok) {
        const errorData = (await response.json().catch(() => ({}))) as any;
        throw new Error(
          errorData.detail ||
            errorData.message ||
            `Upload failed: ${response.statusText}`
        );
      }

      const data = (await response.json()) as {
        resource_id?: string;
        job_id?: string;
        status?: string;
      };

      return {
        success: true,
        resource_id: data.resource_id,
        job_id: data.job_id,
        status: data.status,
        message: 'PDF uploaded successfully',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error occurred';
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
    conceptId?: number
  ): Promise<UploadResponse> {
    try {
      if (!url || (!url.includes('youtube.com') && !url.includes('youtu.be'))) {
        throw new Error('Please provide a valid YouTube URL');
      }

      const response = (await apiClient.post('/resources/import-youtube', {
        url: url.trim(),
        title: title.trim(),
        topic: topic.trim(),
        level,
        concept_id: conceptId && conceptId > 0 ? conceptId : undefined,
      })) as {
        resource_id?: string;
        job_id?: string;
        status?: string;
      };

      return {
        success: true,
        resource_id: response.resource_id,
        job_id: response.job_id,
        status: response.status,
        message: 'YouTube resource added successfully',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to add YouTube resource';
      return {
        success: false,
        error: message,
      };
    }
  },

  async addWebResource(
    data: {
      title: string;
      content: string;
      topic: string;
      level: 'beginner' | 'intermediate' | 'advanced';
      url?: string;
      conceptId?: number;
    }
  ): Promise<UploadResponse> {
    try {
      if (!data.title.trim()) {
        throw new Error('Title is required');
      }
      if (!data.content.trim() || data.content.trim().length < 10) {
        throw new Error('Content must be at least 10 characters');
      }
      if (!data.topic.trim()) {
        throw new Error('Topic is required');
      }

      const response = (await apiClient.post('/resources', {
        title: data.title.trim(),
        content: data.content.trim(),
        source: 'web',
        type: 'text',
        topic: data.topic.trim(),
        level: data.level,
        url: data.url?.trim() || undefined,
        concept_id: data.conceptId && data.conceptId > 0 ? data.conceptId : undefined,
      })) as {
        resource_id?: string;
        job_id?: string;
        status?: string;
      };

      return {
        success: true,
        resource_id: response.resource_id,
        job_id: response.job_id,
        status: response.status,
        message: 'Web resource added successfully',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to add web resource';
      return {
        success: false,
        error: message,
      };
    }
  },

  async deleteResource(_resourceId: string): Promise<{ success: boolean; error?: string }> {
    return {
      success: false,
      error: 'Delete resource endpoint is not available in the current backend.',
    };
  },

  async getResourceById(resourceId: string): Promise<Resource | null> {
    try {
      if (!resourceId) {
        throw new Error('Resource ID is required');
      }

      const response = await this.getAllResources({ page: 1, size: 100 });
      return (
        response.results.find((item) => item.resource_id === resourceId || item._id === resourceId) ||
        null
      );
    } catch (error) {
      console.error(`Error fetching resource ${resourceId}:`, error);
      return null;
    }
  },
};
