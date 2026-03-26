import type { IngestionJobStatus, Resource, SearchResponse } from '../../types/resource';

const DEFAULT_PAGE_SIZE = 10;
type ResourceRecord = Record<string, unknown>;

export type UploadPayload = {
  resource_id?: string;
  job_id?: string;
  status?: string;
  message?: string;
};

export const asRecord = (value: unknown): ResourceRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as ResourceRecord) : {};

const normalizeLevel = (value: unknown): Resource['level'] => {
  if (value === 'intermediate' || value === 'advanced') {
    return value;
  }
  return 'beginner';
};

export const normalizeUploadPayload = (value: unknown): UploadPayload => {
  const record = asRecord(value);
  return {
    resource_id: typeof record.resource_id === 'string' ? record.resource_id : undefined,
    job_id: typeof record.job_id === 'string' ? record.job_id : undefined,
    status: typeof record.status === 'string' ? record.status : undefined,
    message: typeof record.message === 'string' ? record.message : undefined,
  };
};

export const normalizeIngestionJobStatus = (value: unknown): IngestionJobStatus => {
  const record = asRecord(value);
  return {
    job_id: String(record.job_id ?? ''),
    resource_id: String(record.resource_id ?? ''),
    status: String(record.status ?? ''),
    chunks_count: typeof record.chunks_count === 'number' ? record.chunks_count : 0,
    processing_time: typeof record.processing_time === 'number' ? record.processing_time : 0,
    error: typeof record.error === 'string' ? record.error : null,
    resource_status: typeof record.resource_status === 'string' ? record.resource_status : null,
  };
};

export const normalizeResource = (resource: unknown): Resource => {
  const resourceRecord = asRecord(resource);
  const metadata = asRecord(resourceRecord.metadata);
  const videoMetadata = asRecord(metadata.video_metadata ?? resourceRecord.video_metadata);

  return {
    ...resourceRecord,
    id: resourceRecord.id ? String(resourceRecord.id) : undefined,
    resource_id: resourceRecord.resource_id
      ? String(resourceRecord.resource_id)
      : resourceRecord._id
        ? String(resourceRecord._id)
        : undefined,
    _id: resourceRecord._id ? String(resourceRecord._id) : undefined,
    title: String(resourceRecord.title ?? 'Tài nguyên'),
    content: resourceRecord.content ? String(resourceRecord.content) : undefined,
    content_summary: resourceRecord.content_summary
      ? String(resourceRecord.content_summary)
      : undefined,
    url: (resourceRecord.url as string | undefined) ?? (metadata.url as string | undefined),
    source: String(resourceRecord.source ?? 'manual'),
    type: resourceRecord.type ? String(resourceRecord.type) : undefined,
    topic: String(resourceRecord.topic ?? ''),
    level: normalizeLevel(resourceRecord.level ?? metadata.level),
    concept_id:
      typeof resourceRecord.concept_id === 'number'
        ? resourceRecord.concept_id
        : typeof metadata.concept_id === 'number'
          ? metadata.concept_id
          : undefined,
    thumbnail:
      (resourceRecord.thumbnail as string | undefined) ??
      (metadata.thumbnail as string | undefined),
    pdf_file_path:
      (resourceRecord.pdf_file_path as string | undefined) ??
      (metadata.pdf_file_path as string | undefined),
    created_at: resourceRecord.created_at ? String(resourceRecord.created_at) : undefined,
    video_id:
      (resourceRecord.video_id as string | undefined) ?? (metadata.video_id as string | undefined),
    youtube_url:
      (resourceRecord.youtube_url as string | undefined) ??
      (metadata.youtube_url as string | undefined) ??
      (resourceRecord.url as string | undefined),
    video_metadata: {
      thumbnail_url: videoMetadata.thumbnail_url as string | undefined,
      duration: typeof videoMetadata.duration === 'number' ? videoMetadata.duration : undefined,
      channel: videoMetadata.channel as string | undefined,
    },
    score: typeof resourceRecord.score === 'number' ? resourceRecord.score : undefined,
    snippet: resourceRecord.snippet ? String(resourceRecord.snippet) : undefined,
  };
};

export const transformToSearchResponse = (response: unknown): SearchResponse => {
  if (Array.isArray(response)) {
    const results = response.map(normalizeResource);
    return {
      results,
      total: results.length,
      page: 1,
      size: DEFAULT_PAGE_SIZE,
    };
  }

  const responseRecord = asRecord(response);
  const rawResults =
    responseRecord.resources || responseRecord.results || responseRecord.data || [];

  return {
    results: Array.isArray(rawResults) ? rawResults.map(normalizeResource) : [],
    total:
      typeof responseRecord.total === 'number'
        ? responseRecord.total
        : typeof responseRecord.result_count === 'number'
          ? responseRecord.result_count
          : 0,
    page: typeof responseRecord.page === 'number' ? responseRecord.page : 1,
    size: typeof responseRecord.size === 'number' ? responseRecord.size : DEFAULT_PAGE_SIZE,
  };
};
