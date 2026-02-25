import { apiClient } from '@/utils/apiClient';

export interface Resource {
  id?: string;
  resource_id?: string;
  _id?: string;
  title: string;
  content?: string;
  url?: string;
  source: string;
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
  message?: string;
  error?: string;
}

const DEFAULT_PAGE_SIZE = 10;
const PDF_UPLOAD_TIMEOUT = 60000;

/**
 * Wrap a promise with a timeout
 */
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

/**
 * Transform backend response to standard SearchResponse format
 */
function transformToSearchResponse(response: any): SearchResponse {
  if (Array.isArray(response)) {
    return {
      results: response,
      total: response.length,
      page: 1,
      size: DEFAULT_PAGE_SIZE,
    };
  }

  return {
    results: (response as any).resources || (response as any).results || (response as any).data || [],
    total: (response as any).total || 0,
    page: (response as any).page || 1,
    size: (response as any).size || DEFAULT_PAGE_SIZE,
  };
}

// ==========================================
// RESOURCE SERVICE
// ==========================================

export const resourceService = {
  /**
   * Search resources by query string
   * 
   * @param query - Search query
   * @param page - Page number (1-indexed)
   * @param size - Results per page
   * @returns SearchResponse with results and pagination info
   */
  async searchResources(
    query: string,
    page: number = 1,
    size: number = DEFAULT_PAGE_SIZE
  ): Promise<SearchResponse> {
    try {
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
    } catch (error) {
      console.error('Error searching resources:', error);
      throw error;
    }
  },

  /**
   * Get resources by concept ID
   * 
   * @param conceptId - Concept ID to filter by
   * @returns Array of resources for the concept
   */
  async getResourcesByConceptId(conceptId: number): Promise<Resource[]> {
    try {
      if (!conceptId || conceptId <= 0) {
        console.warn('Invalid concept ID:', conceptId);
        return [];
      }

      const response = await apiClient.get(`/resources/?concept_id=${conceptId}`);
      
      if (Array.isArray(response)) {
        return response as Resource[];
      }
      
      return ((response as any).resources || (response as any).results || []) as Resource[];
    } catch (error) {
      console.error(`Error fetching resources for concept ${conceptId}:`, error);
      return [];
    }
  },

  /**
   * Get all resources with optional filtering
   * 
   * @param filters - Filter options (topic, level, source, pagination)
   * @returns SearchResponse with results and pagination
   */
  async getAllResources(filters?: {
    topic?: string;
    level?: string;
    source?: string;
    page?: number;
    size?: number;
  }): Promise<SearchResponse> {
    try {
      const params = new URLSearchParams();
      
      // Add filter parameters
      if (filters?.topic) params.append('topic', filters.topic);
      if (filters?.level) params.append('level', filters.level);
      if (filters?.source) params.append('source', filters.source);
      if (filters?.page) params.append('page', filters.page.toString());
      if (filters?.size) params.append('size', filters.size.toString());

      const query = params.toString();
      const endpoint = query ? `/resources/?${query}` : '/resources/';
      
      const response = await apiClient.get(endpoint);
      
      return transformToSearchResponse(response);
    } catch (error) {
      console.error('Error fetching resources:', error);
      throw error;
    }
  },

  /**
   * Upload and import a PDF resource
   * 
   * @param file - PDF file object
   * @param topic - Topic/subject of the resource
   * @param level - Difficulty level
   * @param conceptId - Optional concept ID to associate
   * @returns Upload response with resource info
   */
  async uploadPDF(
    file: File,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId?: number
  ): Promise<UploadResponse> {
    try {
      // Validate inputs
      if (!file) {
        throw new Error('File is required');
      }

      if (!topic || topic.trim().length === 0) {
        throw new Error('Topic is required');
      }

      if (!level) {
        throw new Error('Level is required');
      }

      // Check file size (max 100MB)
      const maxSize = 100 * 1024 * 1024;
      if (file.size > maxSize) {
        throw new Error('File size exceeds 100MB limit');
      }

      // Create FormData
      const formData = new FormData();
      formData.append('file', file);
      formData.append('topic', topic.trim());
      formData.append('level', level);
      
      if (conceptId && conceptId > 0) {
        formData.append('concept_id', conceptId.toString());
      }

      // Use direct fetch with timeout for file upload (FormData not supported by apiClient yet)
      const controller = new AbortController();
      const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      
      const response = (await withTimeout(
        fetch(
          `${API_BASE_URL}/api/resources/import-pdf`,
          {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
            },
            body: formData,
            signal: controller.signal,
          }
        ),
        PDF_UPLOAD_TIMEOUT,
        'PDF upload timed out. The file may be too large or complex. Please try a smaller file.'
      )) as Response;

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({})) as any;
        throw new Error(
          errorData.detail || 
          errorData.message || 
          `Upload failed: ${response.statusText}`
        );
      }

      const data = (await response.json()) as { resource_id?: string; id?: string; message?: string };
      
      return {
        success: true,
        resource_id: data.resource_id || data.id,
        message: data.message || 'PDF uploaded successfully',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error occurred';
      console.error('Error uploading PDF:', message);
      
      return {
        success: false,
        error: message,
      };
    }
  },

  /**
   * Add a YouTube resource
   * 
   * @param url - YouTube URL
   * @param title - Video title
   * @param topic - Topic/subject
   * @param level - Difficulty level
   * @param conceptId - Optional concept ID
   * @returns Upload response
   */
  async addYouTubeResource(
    url: string,
    title: string,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId?: number
  ): Promise<UploadResponse> {
    try {
      // Validate inputs
      if (!url || (!url.includes('youtube.com') && !url.includes('youtu.be'))) {
        throw new Error('Please provide a valid YouTube URL');
      }

      if (!title || title.trim().length === 0) {
        throw new Error('Title is required');
      }

      if (!topic || topic.trim().length === 0) {
        throw new Error('Topic is required');
      }

      const response = (await apiClient.post('/resources/import-youtube', {
        url: url.trim(),
        title: title.trim(),
        topic: topic.trim(),
        level,
        concept_id: conceptId && conceptId > 0 ? conceptId : undefined,
      })) as { resource_id?: string; id?: string; message?: string };

      return {
        success: true,
        resource_id: response.resource_id || response.id,
        message: response.message || 'YouTube resource added successfully',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to add YouTube resource';
      console.error('Error adding YouTube resource:', message);
      
      return {
        success: false,
        error: message,
      };
    }
  },

  /**
   * Add a web (link) resource
   * 
   * @param url - Web URL
   * @param title - Resource title
   * @param topic - Topic/subject
   * @param level - Difficulty level
   * @param conceptId - Concept ID (required)
   * @returns Upload response
   */
  async addWebResource(
    url: string,
    title: string,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId: number
  ): Promise<UploadResponse> {
    try {
      // Validate inputs
      if (!url || !url.startsWith('http')) {
        throw new Error('Please provide a valid URL starting with http/https');
      }

      if (!title || title.trim().length === 0) {
        throw new Error('Title is required');
      }

      if (!topic || topic.trim().length === 0) {
        throw new Error('Topic is required');
      }

      if (!conceptId || conceptId <= 0) {
        throw new Error('Concept ID is required for web resources');
      }

      const response = (await apiClient.post('/resources/', {
        title: title.trim(),
        url: url.trim(),
        source: 'web',
        topic: topic.trim(),
        level,
        concept_id: conceptId,
      })) as { resource_id?: string; id?: string; message?: string };

      return {
        success: true,
        resource_id: response.resource_id || response.id,
        message: response.message || 'Web resource added successfully',
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to add web resource';
      console.error('Error adding web resource:', message);
      
      return {
        success: false,
        error: message,
      };
    }
  },

  /**
   * Delete a resource by ID
   * 
   * @param resourceId - Resource ID to delete
   * @returns Success status
   */
  async deleteResource(resourceId: string): Promise<{ success: boolean; error?: string }> {
    try {
      if (!resourceId) {
        throw new Error('Resource ID is required');
      }

      await apiClient.delete(`/resources/${resourceId}`);
      
      return { success: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete resource';
      console.error('Error deleting resource:', message);
      
      return {
        success: false,
        error: message,
      };
    }
  },

  /**
   * Get resource details by ID
   * 
   * @param resourceId - Resource ID
   * @returns Resource details or null
   */
  async getResourceById(resourceId: string): Promise<Resource | null> {
    try {
      if (!resourceId) {
        throw new Error('Resource ID is required');
      }

      const response = (await apiClient.get(`/resources/${resourceId}`)) as Resource | null;
      
      return response || null;
    } catch (error) {
      console.error(`Error fetching resource ${resourceId}:`, error);
      return null;
    }
  },
};