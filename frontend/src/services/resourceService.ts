import { apiClient } from '../utils/apiClient';

export interface Resource {
  resource_id: string;
  title: string;
  topic: string;
  level: 'beginner' | 'intermediate' | 'advanced';
  source: 'pdf' | 'youtube' | 'web';
  snippet?: string;
  url?: string;
  created_at?: string;
  score?: number;
}

export interface SearchResponse {
  results: Resource[];
  total: number;
  page: number;
  size: number;
}

export const resourceService = {
  /**
   * Search resources by query
   */
  async searchResources(query: string, page: number = 1, size: number = 10): Promise<SearchResponse> {
    try {
      return await apiClient.get(
        `/resources/search?q=${encodeURIComponent(query)}&page=${page}&size=${size}`
      );
    } catch (error) {
      console.error('Error searching resources:', error);
      throw error;
    }
  },

  /**
   * Get resources by concept
   */
  async getResourcesByConceptId(conceptId: number): Promise<Resource[]> {
    try {
      const response = await apiClient.get(`/resources/?concept_id=${conceptId}`);
      return response.resources || [];
    } catch (error) {
      console.error('Error fetching resources:', error);
      return [];
    }
  },

  /**
   * Get all resources with optional filtering
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
      if (filters?.topic) params.append('topic', filters.topic);
      if (filters?.level) params.append('level', filters.level);
      if (filters?.source) params.append('source', filters.source);
      if (filters?.page) params.append('page', filters.page.toString());
      if (filters?.size) params.append('size', filters.size.toString());

      const query = params.toString();
      const endpoint = query ? `/resources/?${query}` : '/resources/';
      
      const response = await apiClient.get(endpoint);
      
      // Transform backend response (resources) to frontend format (results)
      return {
        results: response.resources || [],
        total: response.total || 0,
        page: response.page || 1,
        size: response.size || 0
      };
    } catch (error) {
      console.error('Error fetching resources:', error);
      throw error;
    }
  },

  /**
   * Upload PDF resource
   */
  async uploadPDF(
    file: File,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId?: number
  ): Promise<any> {
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('topic', topic);
      formData.append('level', level);
      if (conceptId) {
        formData.append('concept_id', conceptId.toString());
      }

      const response = await fetch(
        `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/resources/import-pdf`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
          },
          body: formData,
        }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to upload PDF');
      }

      return await response.json();
    } catch (error) {
      console.error('Error uploading PDF:', error);
      throw error;
    }
  },

  /**
   * Add resource from YouTube
   */
  async addYouTubeResource(
    url: string,
    title: string,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId?: number
  ): Promise<any> {
    try {
      return await apiClient.post('/resources/import-youtube', {
        url,
        title,
        topic,
        level,
        concept_id: conceptId,
      });
    } catch (error) {
      console.error('Error adding YouTube resource:', error);
      throw error;
    }
  },

  /**
   * Add web resource
   */
  async addWebResource(
    url: string,
    title: string,
    topic: string,
    level: 'beginner' | 'intermediate' | 'advanced',
    conceptId: number
  ): Promise<any> {
    try {
      return await apiClient.post('/resources', {
        title,
        content: url,
        source: 'web',
        topic,
        level,
        concept_id: conceptId,
        url,
      });
    } catch (error) {
      console.error('Error adding web resource:', error);
      throw error;
    }
  },
};
