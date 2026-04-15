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

export interface ResourceCurationItem {
  resource_id: string;
  title: string;
  topic: string;
  source: string;
  type: string;
  status: string;
  chunks_count: number;
  quality_score: number;
  quality_label: string;
  quality_breakdown: Record<string, number | string>;
  curated_concept_ids: string[];
  admin_notes: string;
  hidden_from_recommendation: boolean;
  duplicate_key?: string | null;
  duplicate_count: number;
  problem_flags: string[];
  updated_at?: string;
}

export interface ResourceCurationSnapshot {
  items: ResourceCurationItem[];
  status_counts: Record<string, number>;
  duplicate_groups: Array<{
    duplicate_key: string;
    resource_ids: string[];
    duplicate_count: number;
  }>;
  low_quality_count: number;
  total_items: number;
}

export interface IngestionHealthSnapshot {
  resource_status_counts: Record<string, number>;
  chunk_totals: {
    total: number;
    with_embeddings: number;
    without_embeddings: number;
    by_backend: Record<string, number>;
  };
  embedding: Record<string, unknown>;
  vector_store: {
    available: boolean;
  };
  recent_jobs: Array<Record<string, unknown>>;
}
