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
  is_completed?: boolean;
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

export interface IngestionJobStatus {
  job_id: string;
  resource_id: string;
  status: string;
  chunks_count: number;
  processing_time: number;
  error?: string | null;
  resource_status?: string | null;
}
