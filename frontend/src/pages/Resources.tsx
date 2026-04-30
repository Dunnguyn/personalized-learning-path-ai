import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { resourcesIcon, searchIcon, downArrowIcon } from '../assets';
import DashboardLayout from '../components/layout/DashboardLayout';
import PDFViewer from '../components/PDFViewer';
import PageHero from '../components/ui/PageHero';
import StatusPanel from '../components/ui/StatusPanel';
import { useAuth } from '../contexts/AuthContext';
import { resourceService } from '../services/resourceService';
import { recommendationInteractionService } from '../services/recommendationInteractionService';
import type { Resource, SearchResponse } from '../types/resource';
import { apiClient } from '../utils/apiClient';

type ResourceLevel = Resource['level'];
const PDF_PAGE_MARKER_REGEX = /\[Page\s+\d+\]\s*/gi;
const MAX_PREVIEW_LENGTH = 240;
const RESOURCE_LEVEL_LABELS: Record<string, string> = {
  beginner: 'Bắt đầu',
  intermediate: 'Trung bình',
  advanced: 'Nâng cao',
};
const RESOURCE_SOURCE_LABELS: Record<string, string> = {
  youtube: 'YouTube',
  pdf: 'PDF',
  web: 'Trang web',
};

type ResourceSortOption = 'relevance' | 'newest' | 'level';

const RESOURCE_SORT_OPTIONS: Array<{ value: ResourceSortOption; label: string }> = [
  { value: 'relevance', label: 'Ưu tiên phù hợp' },
  { value: 'newest', label: 'Mới cập nhật' },
  { value: 'level', label: 'Theo cấp độ' },
];

const RESOURCE_FORM_COPY = {
  web: {
    kicker: 'Nguồn web',
    title: 'Thêm tài nguyên dạng bài viết hoặc ghi chú',
    description:
      'Phù hợp khi bạn muốn lưu một bài viết, một landing page hoặc tự nhập nội dung để dùng lại trong thư viện.',
    tips: ['Có thể bỏ trống URL nếu đây là ghi chú nội bộ.', 'Nên đặt chủ đề ngắn gọn để tìm lại nhanh hơn.'],
    submitLabel: 'Thêm tài nguyên web',
  },
  youtube: {
    kicker: 'Video YouTube',
    title: 'Thêm video học tập từ YouTube',
    description:
      'Dùng khi bạn muốn gom video bài giảng, walkthrough hoặc demo kỹ thuật vào cùng luồng học hiện tại.',
    tips: ['Dán đúng liên kết video để hệ thống lấy thumbnail ổn định.', 'Tiêu đề nên rõ chủ đề để phần gợi ý chính xác hơn.'],
    submitLabel: 'Thêm video',
  },
  pdf: {
    kicker: 'Tài liệu PDF',
    title: 'Tải tài liệu PDF vào thư viện',
    description:
      'Phù hợp với ebook, slide hoặc tài liệu tham khảo muốn đọc trực tiếp và gắn vào hành trình học.',
    tips: ['Chọn đúng chủ đề để gợi ý tài liệu liên quan tốt hơn.', 'Sau khi tải lên, hệ thống có thể cần ít phút để xử lý nội dung.'],
    submitLabel: 'Tải lên PDF',
  },
} as const;

const RESOURCE_TYPE_OPTIONS = [
  {
    type: 'web',
    label: 'Trang web',
    description: 'Bài viết, landing page hoặc ghi chú nội bộ',
  },
  {
    type: 'youtube',
    label: 'YouTube',
    description: 'Video bài giảng, walkthrough hoặc demo kỹ thuật',
  },
  {
    type: 'pdf',
    label: 'PDF',
    description: 'Ebook, slide hoặc tài liệu tham khảo để đọc trực tiếp',
  },
] as const;

const getVisiblePaginationItems = (
  currentPage: number,
  totalPages: number,
): Array<number | 'ellipsis'> => {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  if (currentPage <= 3) {
    return [1, 2, 3, 4, 'ellipsis', totalPages];
  }

  if (currentPage >= totalPages - 2) {
    return [1, 'ellipsis', totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  }

  return [1, 'ellipsis', currentPage - 1, currentPage, currentPage + 1, 'ellipsis', totalPages];
};

const parseResourceLevel = (value: FormDataEntryValue | null): ResourceLevel => {
  if (value === 'intermediate' || value === 'advanced') {
    return value;
  }
  return 'beginner';
};

const collapseText = (value: string): string =>
  value.replace(PDF_PAGE_MARKER_REGEX, ' ').replace(/\s+/g, ' ').trim();

const truncateText = (value: string, maxLength: number = MAX_PREVIEW_LENGTH): string => {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength).trimEnd()}...`;
};

const estimateResourceMinutes = (resource: Resource) => {
  if (resource.video_metadata?.duration && Number.isFinite(resource.video_metadata.duration)) {
    return Math.max(Math.round(resource.video_metadata.duration / 60), 3);
  }

  const baseText = collapseText(resource.content_summary || resource.snippet || resource.content || '');
  const estimatedFromWords = Math.round(baseText.split(/\s+/).filter(Boolean).length / 160);

  if (resource.source === 'pdf') {
    return Math.max(estimatedFromWords, 12);
  }

  if (resource.source === 'web') {
    return Math.max(estimatedFromWords, 6);
  }

  return Math.max(estimatedFromWords, 8);
};

const computeResourceRelevanceScore = (
  resource: Resource,
  query: string,
  levelFilter: string,
  sourceFilter: string,
) => {
  let score = typeof resource.score === 'number' ? resource.score : 0.54;
  const normalizedQuery = query.trim().toLowerCase();
  const haystack = [resource.title, resource.topic, resource.content_summary, resource.snippet]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  if (normalizedQuery && haystack.includes(normalizedQuery)) {
    score += 0.22;
  }
  if (levelFilter && resource.level === levelFilter) {
    score += 0.12;
  }
  if (sourceFilter && resource.source === sourceFilter) {
    score += 0.08;
  }
  if (resource.is_completed) {
    score -= 0.06;
  }

  return Math.max(0.3, Math.min(score, 0.99));
};

const formatPdfTitle = (value: string): string =>
  value
    .replace(/\.pdf$/i, '')
    .replace(/[_-]+/g, ' ')
    .replace(/([A-Za-z])(\d)/g, '$1 $2')
    .replace(/(\d)([A-Za-z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim();

const getDisplayTitle = (resource: Resource): string => {
  const rawTitle = (resource.title || resource.topic || 'Tài nguyên').trim();
  if (resource.source !== 'pdf') {
    return rawTitle;
  }
  return formatPdfTitle(rawTitle) || 'Tài liệu PDF';
};

const getDisplaySnippet = (resource: Resource): string => {
  const rawPreview = resource.snippet || resource.content_summary || resource.content || '';
  const cleanedPreview = collapseText(rawPreview);
  if (cleanedPreview) {
    return truncateText(cleanedPreview, resource.source === 'pdf' ? 220 : MAX_PREVIEW_LENGTH);
  }
  if (resource.source === 'pdf') {
    return 'Tài liệu PDF này đã được thêm vào thư viện và sẵn sàng để xem trực tiếp.';
  }
  if (resource.source === 'youtube') {
    return 'Video này đã được thêm vào thư viện để bạn xem lại bất cứ lúc nào.';
  }
  return 'Tài nguyên được chọn để bổ trợ cho quá trình học tập hiện tại của bạn.';
};

const toNumericResourceId = (resource: Resource): number | undefined => {
  const rawValue = resource.resource_id || resource.id || resource._id;
  if (!rawValue) {
    return undefined;
  }

  const parsed = Number(rawValue);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const isSameResource = (left: Resource, right: Resource): boolean => {
  const leftId = left.resource_id || left.id || left._id;
  const rightId = right.resource_id || right.id || right._id;
  return Boolean(leftId && rightId && leftId === rightId);
};

export default function Resources() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const conceptIdParam = searchParams.get('concept');
  const queryParam = searchParams.get('q');
  const canManageResources = user?.role === 'admin';

  const [searchQuery, setSearchQuery] = useState('');
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalResults, setTotalResults] = useState(0);
  const pageSize = 4;

  const [filters, setFilters] = useState({
    level: '',
    source: '',
  });
  const [sortOption, setSortOption] = useState<ResourceSortOption>('relevance');
  const trimmedSearchQuery = searchQuery.trim();
  const hasActiveFilters = Boolean(trimmedSearchQuery || filters.level || filters.source);
  const activeFilterChips = [
    trimmedSearchQuery ? `Từ khóa: ${trimmedSearchQuery}` : null,
    filters.level ? `Cấp độ: ${RESOURCE_LEVEL_LABELS[filters.level] || filters.level}` : null,
    filters.source ? `Nguồn: ${RESOURCE_SOURCE_LABELS[filters.source] || filters.source}` : null,
    sortOption !== 'relevance'
      ? `Sắp xếp: ${RESOURCE_SORT_OPTIONS.find((option) => option.value === sortOption)?.label}`
      : null,
  ].filter(Boolean) as string[];

  const [showAddResource, setShowAddResource] = useState(false);
  const [addResourceType, setAddResourceType] = useState<'pdf' | 'youtube' | 'web'>('web');
  const selectedFormCopy = RESOURCE_FORM_COPY[addResourceType];
  const [uploadingPDF, setUploadingPDF] = useState(false);
  const [addingResource, setAddingResource] = useState(false);
  const [deletingResourceId, setDeletingResourceId] = useState<string | null>(null);
  const [pendingDeleteResource, setPendingDeleteResource] = useState<Resource | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [aiHealth, setAiHealth] = useState<Record<string, unknown> | null>(null);
  const [aiHealthError, setAiHealthError] = useState<string | null>(null);

  const [playingVideo, setPlayingVideo] = useState<{
    videoId: string;
    title: string;
  } | null>(null);

  const [viewingPDF, setViewingPDF] = useState<{
    title: string;
    resourceId: string;
  } | null>(null);

  const selectedSourceLabel = filters.source ? RESOURCE_SOURCE_LABELS[filters.source] || filters.source : 'Mọi nguồn';
  const selectedLevelLabel = filters.level ? RESOURCE_LEVEL_LABELS[filters.level] || filters.level : 'Mọi cấp độ';
  const contextValue = conceptIdParam ? 'Theo khái niệm' : trimmedSearchQuery ? 'Theo truy vấn' : 'Toàn thư viện';
  const contextDetail = conceptIdParam
    ? `Đang ưu tiên tài nguyên gắn với khái niệm #${conceptIdParam}.`
    : trimmedSearchQuery
      ? trimmedSearchQuery
      : 'Không có truy vấn đang áp dụng.';
  const resultRangeStart = totalResults === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const resultRangeEnd = totalResults === 0 ? 0 : Math.min(currentPage * pageSize, totalResults);
  const displayedResources = useMemo(() => {
    const decorated = resources.map((resource) => ({
      resource,
      relevanceScore: computeResourceRelevanceScore(
        resource,
        trimmedSearchQuery,
        filters.level,
        filters.source,
      ),
      estimatedMinutes: estimateResourceMinutes(resource),
    }));

    return decorated
      .sort((left, right) => {
      if (sortOption === 'newest') {
        return (
          new Date(right.resource.created_at || 0).getTime() -
          new Date(left.resource.created_at || 0).getTime()
        );
      }

      if (sortOption === 'level') {
        const order = { beginner: 1, intermediate: 2, advanced: 3 };
        return order[left.resource.level] - order[right.resource.level];
      }

        return right.relevanceScore - left.relevanceScore;
      })
      .slice(0, 8);
  }, [filters.level, filters.source, resources, sortOption, trimmedSearchQuery]);
  const featuredResources = displayedResources.slice(0, 3);

  // Form refs for handling resets safely
  const pdfFormRef = useRef<HTMLFormElement>(null);
  const youtubeFormRef = useRef<HTMLFormElement>(null);
  const webFormRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (queryParam) {
      setSearchQuery(queryParam);
      setCurrentPage(1);
    }
  }, [queryParam]);

  const fetchResources = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      let response: SearchResponse;

      if (conceptIdParam) {
        const conceptId = parseInt(conceptIdParam);
        const conceptResources = await resourceService.getResourcesByConceptId(conceptId);
        response = {
          results: conceptResources,
          total: conceptResources.length,
          page: 1,
          size: conceptResources.length,
        };
      } else if (searchQuery.trim()) {
        response = await resourceService.searchResources(searchQuery, currentPage, pageSize);
      } else {
        response = await resourceService.getAllResources({
          level: filters.level || undefined,
          source: filters.source || undefined,
          page: currentPage,
          size: pageSize,
        });
      }

      setResources(response.results);
      setTotalResults(response.total);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tải tài nguyên';
      setError(message);
      console.error('Error fetching resources:', err);
    } finally {
      setLoading(false);
    }
  }, [conceptIdParam, currentPage, filters.level, filters.source, searchQuery]);

  useEffect(() => {
    void fetchResources();
  }, [fetchResources]);

  useEffect(() => {
    if (!canManageResources) {
      setAiHealth(null);
      setAiHealthError(null);
      return;
    }

    let active = true;
    const loadAiHealth = async () => {
      try {
        const response =
          ((await apiClient.get('/health/ai')) as Record<string, unknown>) || null;
        if (!active) {
          return;
        }
        setAiHealth(response);
        setAiHealthError(null);
      } catch (error) {
        if (!active) {
          return;
        }
        setAiHealth(null);
        setAiHealthError(
          error instanceof Error ? error.message : 'Không thể tải trạng thái AI stack.',
        );
      }
    };

    void loadAiHealth();
    return () => {
      active = false;
    };
  }, [canManageResources]);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setToast(null);
    }, 2600);

    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!playingVideo && !pendingDeleteResource) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') {
        return;
      }

      if (pendingDeleteResource && !deletingResourceId) {
        setPendingDeleteResource(null);
        return;
      }

      if (playingVideo) {
        setPlayingVideo(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [deletingResourceId, pendingDeleteResource, playingVideo]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    await fetchResources();
  };

  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setCurrentPage(1);
  };

  const handleResetFilters = () => {
    setSearchQuery('');
    setFilters({ level: '', source: '' });
    setSortOption('relevance');
    setCurrentPage(1);
  };

  const finalizeIngestion = async (response: { job_id?: string; message?: string }) => {
    if (response.job_id) {
      setStatusMessage('Tài nguyên đã được gửi lên. Hệ thống đang xử lý nội dung...');
      await resourceService.waitForIngestionCompletion(response.job_id);
      setStatusMessage(null);
      showToast('success', 'Tài nguyên đã xử lý xong và sẵn sàng để học.');
    } else {
      setStatusMessage(null);
      showToast('success', response.message || 'Tài nguyên đã được thêm thành công.');
    }

    await fetchResources();
  };

  const handlePDFUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canManageResources) {
      showToast('error', 'Bạn không có quyền thêm tài nguyên.');
      return;
    }
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const file = form.get('pdf_file') as File;
    const topic = form.get('topic') as string;
    const level = parseResourceLevel(form.get('level'));

    if (!file || !topic) {
      showToast('error', 'Vui lòng điền đầy đủ thông tin.');
      return;
    }

    setUploadingPDF(true);
    setError(null);
    setStatusMessage(null);

    try {
      const response = await resourceService.uploadPDF(file, topic, level);
      if (!response.success) {
        throw new Error(response.error || 'Không thể tải tệp PDF lên');
      }
      // Reset form using ref before closing
      pdfFormRef.current?.reset();
      setShowAddResource(false);
      await finalizeIngestion(response);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tải tệp PDF lên';
      showToast('error', message);
    } finally {
      setUploadingPDF(false);
    }
  };

  const handleYouTubeAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canManageResources) {
      showToast('error', 'Bạn không có quyền thêm tài nguyên.');
      return;
    }
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const url = form.get('youtube_url') as string;
    const title = form.get('title') as string;
    const topic = form.get('topic') as string;
    const level = parseResourceLevel(form.get('level'));

    if (!url || !title || !topic) {
      showToast('error', 'Vui lòng điền đầy đủ thông tin.');
      return;
    }

    setAddingResource(true);
    setError(null);
    setStatusMessage(null);

    try {
      const response = await resourceService.addYouTubeResource(url, title, topic, level);
      if (!response.success) {
        throw new Error(response.error || 'Không thể thêm tài nguyên YouTube');
      }
      // Reset form using ref before closing
      youtubeFormRef.current?.reset();
      setShowAddResource(false);
      await finalizeIngestion(response);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể thêm tài nguyên YouTube';
      showToast('error', message);
    } finally {
      setAddingResource(false);
    }
  };

  const handleWebAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canManageResources) {
      showToast('error', 'Bạn không có quyền thêm tài nguyên.');
      return;
    }
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const url = form.get('web_url') as string;
    const title = form.get('title') as string;
    const content = form.get('content') as string;
    const topic = form.get('topic') as string;
    const level = parseResourceLevel(form.get('level'));

    if (!title || !topic || !content) {
      showToast('error', 'Vui lòng điền đầy đủ thông tin.');
      return;
    }

    setAddingResource(true);
    setError(null);
    setStatusMessage(null);

    try {
      const response = await resourceService.addWebResource({
        url,
        title,
        content,
        topic,
        level,
      });
      if (!response.success) {
        throw new Error(response.error || 'Không thể thêm tài nguyên web');
      }
      // Reset form using ref before closing
      webFormRef.current?.reset();
      setShowAddResource(false);
      await finalizeIngestion(response);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể thêm tài nguyên web';
      showToast('error', message);
    } finally {
      setAddingResource(false);
    }
  };

  const totalPages = Math.ceil(totalResults / pageSize);
  const paginationItems = getVisiblePaginationItems(currentPage, totalPages);

  const extractVideoId = (resource: Resource): string | null => {
    if (resource.video_id) {
      return resource.video_id;
    }

    const url = resource.youtube_url || resource.url;
    if (!url) return null;

    const urlPatterns = [
      /(?:youtube\.com\/watch\?v=)([^&]+)/,
      /(?:youtu\.be\/)([^?]+)/,
      /(?:youtube\.com\/embed\/)([^?]+)/,
    ];

    for (const pattern of urlPatterns) {
      const match = url.match(pattern);
      if (match && match[1]) {
        return match[1];
      }
    }

    return null;
  };


  const handlePlayVideo = (resource: Resource) => {
    const videoId = extractVideoId(resource);
    if (videoId) {
      setPlayingVideo({
        videoId,
        title: resource.title,
      });
    }
  };

  const getResourceIdentifier = (resource: Resource): string => {
    return resource.resource_id || resource._id || resource.id || '';
  };

  const handleDeleteResource = async (resource: Resource) => {
    if (!canManageResources) {
      showToast('error', 'Chỉ admin mới có thể xóa tài nguyên.');
      return;
    }
    setPendingDeleteResource(resource);
  };

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message });
  };

  const handleConfirmDeleteResource = async () => {
    if (!canManageResources) {
      showToast('error', 'Chỉ admin mới có thể xóa tài nguyên.');
      setPendingDeleteResource(null);
      return;
    }
    if (!pendingDeleteResource) {
      return;
    }

    const resource = pendingDeleteResource;
    const resourceId = getResourceIdentifier(resource);
    if (!resourceId) {
      setError('Không tìm thấy mã tài nguyên để xóa.');
      setPendingDeleteResource(null);
      return;
    }

    try {
      setDeletingResourceId(resourceId);
      setError(null);
      setStatusMessage(null);

      const response = await resourceService.deleteResource(resourceId);
      if (!response.success) {
        throw new Error(response.error || 'Không thể xóa tài nguyên.');
      }

      setPendingDeleteResource(null);
      setStatusMessage('Đã xóa tài nguyên thành công.');
      showToast('success', 'Đã xóa tài nguyên thành công.');

      if (resources.length === 1 && currentPage > 1) {
        setCurrentPage((prev) => prev - 1);
      } else {
        await fetchResources();
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể xóa tài nguyên.';
      setError(message);
      showToast('error', message);
    } finally {
      setDeletingResourceId(null);
    }
  };

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'beginner':
        return 'bg-[#f6d9e3] text-[#8c3451]';
      case 'intermediate':
        return 'bg-[#f8e3ea] text-[#7f3650]';
      case 'advanced':
        return 'bg-[#f3cad7] text-[#7a2844]';
      default:
        return 'bg-[#f9eef2] text-[#7f3650]';
    }
  };

  const getLevelLabel = (level: string) => {
    switch (level) {
      case 'beginner':
        return 'Cơ bản';
      case 'intermediate':
        return 'Trung bình';
      case 'advanced':
        return 'Nâng cao';
      default:
        return 'Cơ bản';
    }
  };

  const getSourceLabel = (source: string) => {
    if (source === 'pdf') return 'Tài liệu PDF';
    if (source === 'youtube') return 'YouTube';
    return 'Trang web';
  };

  const getSourceTheme = (source: string) => {
    if (source === 'youtube') {
      return {
        chip: 'border-[#f1d4e0] bg-[#fff5fa] text-[#aa476f]',
        icon: 'border-[#f1d4e0] bg-[#fff5fa] text-[#aa476f]',
        preview: 'bg-[linear-gradient(180deg,#fff9fc_0%,#fbeaf2_100%)]',
        accent: 'bg-[#aa476f]',
        soft: 'bg-[#fff1f7]',
      };
    }

    if (source === 'pdf') {
      return {
        chip: 'border-[#edd8e5] bg-[#fff7fb] text-[#8f5377]',
        icon: 'border-[#edd8e5] bg-[#fff7fb] text-[#8f5377]',
        preview: 'bg-[linear-gradient(180deg,#fffafd_0%,#f8edf4_100%)]',
        accent: 'bg-[#8f5377]',
        soft: 'bg-[#fbf1f7]',
      };
    }

    return {
      chip: 'border-[#f2d9e3] bg-[#fff7fa] text-[#ad5c7b]',
      icon: 'border-[#f2d9e3] bg-[#fff7fa] text-[#ad5c7b]',
      preview: 'bg-[linear-gradient(180deg,#fffbfd_0%,#f9edf3_100%)]',
      accent: 'bg-[#ad5c7b]',
      soft: 'bg-[#fff3f8]',
    };
  };

  const getSourceIcon = (source: string) => {
    if (source === 'youtube') {
      return (
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M21.6 7.2a2.9 2.9 0 0 0-2-2C17.8 4.7 12 4.7 12 4.7s-5.8 0-7.6.5a2.9 2.9 0 0 0-2 2A30.3 30.3 0 0 0 2 12a30.3 30.3 0 0 0 .4 4.8 2.9 2.9 0 0 0 2 2c1.8.5 7.6.5 7.6.5s5.8 0 7.6-.5a2.9 2.9 0 0 0 2-2A30.3 30.3 0 0 0 22 12a30.3 30.3 0 0 0-.4-4.8ZM10 15.5v-7l6 3.5-6 3.5Z" />
        </svg>
      );
    }

    if (source === 'pdf') {
      return (
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          aria-hidden="true"
        >
          <path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7Z" />
          <path d="M14 2v5h5" />
          <path d="M8 13h2.5a1.5 1.5 0 0 0 0-3H8v7" />
          <path d="M14 10h1a2 2 0 0 1 0 4h-1v-4Z" />
          <path d="M18 10h-2v4" />
        </svg>
      );
    }

    return (
      <svg
        className="h-5 w-5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        aria-hidden="true"
      >
        <path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0-18 0Z" />
        <path d="M3.6 9h16.8" />
        <path d="M3.6 15h16.8" />
        <path d="M12 3a15.3 15.3 0 0 1 0 18" />
        <path d="M12 3a15.3 15.3 0 0 0 0 18" />
      </svg>
    );
  };

  const handleOpenResource = (resource: Resource) => {
    const displayTitle = getDisplayTitle(resource);

    if (resource.source === 'youtube') {
      handlePlayVideo(resource);
      return;
    }

    if (resource.source === 'pdf') {
      const resourceId = getResourceIdentifier(resource);
      if (!resourceId) {
        setError('Không tìm thấy ID tài nguyên PDF');
        return;
      }

      setViewingPDF({ title: displayTitle, resourceId });
      return;
    }

    const targetUrl = resource.url?.trim();
    if (targetUrl) {
      window.open(targetUrl, '_blank', 'noopener,noreferrer');
    }
  };

  const handleMarkResourceCompleted = async (
    resource: Resource,
    context: string = 'resource_card',
  ) => {
    if (resource.is_completed) {
      return;
    }

    try {
      await recommendationInteractionService.trackResourceCompleted({
        resource_id: toNumericResourceId(resource),
        concept_id: resource.concept_id,
        goal: resource.topic,
        level: resource.level,
        metadata: {
          source_screen: 'resources',
          completion_context: context,
          resource_source: resource.source,
          resource_identifier: resource.resource_id || resource.id || resource._id,
        },
      });
      setResources((previous) =>
        previous.map((current) =>
          isSameResource(current, resource)
            ? {
                ...current,
                is_completed: true,
              }
            : current,
        ),
      );
      showToast('success', 'Đã ghi nhận hoàn thành tài nguyên.');
    } catch (completionError) {
      console.error('Failed to track resource completion:', completionError);
      showToast('error', 'Không thể ghi nhận hoàn thành tài nguyên.');
    }
  };

  return (
    <DashboardLayout>
      <div className="page-shell desktop-1440-resources pb-6">
        <PageHero
          className="mb-6 resources-hero-minimal"
          descriptionClassName="hidden"
          actionsClassName="hidden"
          kicker="Thư viện tài nguyên"
          title="Tìm kiếm, rà soát và vận hành thư viện học tập trong một màn hình."
          description="Từ tìm kiếm, lọc nguồn đến thêm mới và mở nhanh, các tác vụ chính đã được gom lại để việc duyệt tài nguyên bớt đứt mạch."
          actions={
            <>
              <span className="demo-pill">{totalResults} tài nguyên</span>
              <span className="demo-pill">
                {canManageResources ? 'Chế độ admin' : 'Chế độ learner'}
              </span>
              {canManageResources ? (
                <button
                  type="button"
                  onClick={() => setShowAddResource((previous) => !previous)}
                  className="theme-button-secondary px-4 py-2 text-[12px]"
                >
                  {showAddResource ? 'Thu gọn khung thêm mới' : 'Mở khung thêm mới'}
                </button>
              ) : null}
            </>
          }
          metrics={[
            {
              label: 'Ngữ cảnh hiện tại',
              value: contextValue,
              detail: contextDetail,
            },
            {
              label: 'Nguồn',
              value: selectedSourceLabel,
              detail: 'YouTube, PDF và web cùng nằm trong một luồng duyệt thống nhất.',
            },
            {
              label: 'Cấp độ',
              value: selectedLevelLabel,
              detail: canManageResources ? 'Admin có thể thêm, xóa và kiểm tra trạng thái AI trực tiếp từ màn này.' : 'Learner chỉ có quyền xem, lọc và mở tài nguyên.',
            },
          ]}
        >
          <div className="hero-visual-grid">
            <article className="hero-visual-card">
              <span className="hero-visual-icon">
                <img src={resourcesIcon} alt="" className="h-7 w-7 object-contain" />
              </span>
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Thư viện
                </p>
                <p className="mt-2 text-[16px] font-semibold text-[#17141a]">
                  Gom toàn bộ nguồn học vào một luồng duyệt
                </p>
              </div>
            </article>
            <article className="hero-visual-card">
              <span className="hero-visual-icon">
                <img src={searchIcon} alt="" className="h-7 w-7 object-contain" />
              </span>
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Tìm kiếm
                </p>
                <p className="mt-2 text-[16px] font-semibold text-[#17141a]">
                  Tìm nhanh theo chủ đề, truy vấn hoặc nguồn
                </p>
              </div>
            </article>
            <article className="hero-visual-card">
              <span className="hero-visual-icon">
                <img src={downArrowIcon} alt="" className="h-6 w-6 object-contain" />
              </span>
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Luồng duyệt
                </p>
                <p className="mt-2 text-[16px] font-semibold text-[#17141a]">
                  Giảm thao tác thừa khi lọc và mở tài nguyên
                </p>
              </div>
            </article>
          </div>
        </PageHero>

        {canManageResources && aiHealth && import.meta.env.DEV ? (
          <StatusPanel
            className="mb-6"
            tone={
              String(
                ((aiHealth!.embedding as Record<string, unknown> | undefined)?.backend as
                  | string
                  | undefined) || '',
              ) === 'hash_fallback'
                ? 'error'
                : 'info'
            }
            title="AI embedding stack"
            description={
              String(
                ((aiHealth!.embedding as Record<string, unknown> | undefined)?.backend as
                  | string
                  | undefined) || 'unknown',
              ) === 'hash_fallback'
                ? 'Hệ thống đang chạy bằng hash_fallback. Nên chuyển sang sentence-transformers hoặc Gemini embeddings trước khi demo semantic recommendation.'
                : `Embedding backend đang hoạt động: ${String(
                    ((aiHealth!.embedding as Record<string, unknown> | undefined)?.backend as
                      | string
                      | undefined) || 'unknown',
                  )}.`
            }
          />
        ) : null}

        {canManageResources && aiHealthError && import.meta.env.DEV ? (
          <StatusPanel className="mb-6" tone="error" title="AI embedding stack" description={aiHealthError} />
        ) : null}

        {error && (
          <StatusPanel
            className="white-panel mb-6 px-4 py-3 shadow-none"
            tone="error"
            description={error}
          />
        )}

        {statusMessage && !error && (
          <StatusPanel
            className="white-panel mb-6 border-emerald-200 px-4 py-3 text-emerald-700 shadow-none"
            description={statusMessage}
          />
        )}

        <div
          className={`hidden mb-6 rounded-[24px] border px-5 py-4 text-[14px] leading-6 ${
            canManageResources
              ? 'border-[#ead7df] bg-[#fff7fb] text-[#6f5260]'
              : 'border-[#dbe8f2] bg-[#f6fbff] text-[#2f657f]'
          }`}
        >
          {canManageResources
            ? 'Bạn đang ở chế độ Admin. Màn hình này hỗ trợ tìm kiếm, thêm mới, mở nhanh và dọn tài nguyên học tập trong cùng một luồng.'
            : 'Tài khoản learner chỉ có quyền xem, tìm kiếm và mở tài nguyên. Các thao tác thêm mới hoặc xóa chỉ dành cho Admin.'}
        </div>

        <div className="soft-panel z-10 mb-[40px] space-y-5 p-4 sm:p-5 lg:sticky lg:top-4 lg:p-6">
          <div className="hidden rounded-[24px] border border-white/80 bg-white/75 px-4 py-4 shadow-[0_12px_30px_rgba(114,62,83,0.06)] sm:px-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div className="max-w-2xl">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#b07a8e]">
                  Điều khiển thư viện
                </p>
                <h2 className="mt-2 text-[22px] font-semibold tracking-[-0.04em] text-[#17141a] sm:text-[26px]">
                  Lọc đúng tài nguyên trong ít thao tác hơn
                </h2>
                <p className="mt-3 text-[13px] leading-6 text-[#6f6661] sm:text-[14px]">
                  {canManageResources
                    ? 'Bảng điều khiển này ưu tiên thao tác nhanh: tìm kiếm, đổi nguồn, mở khung thêm mới và xóa bộ lọc ngay tại chỗ.'
                    : 'Bảng điều khiển này giúp bạn chuyển giữa các nguồn học, đổi cấp độ và quay lại toàn thư viện mà không phải thao tác nhiều bước.'}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-[18px] border border-[#ecdce3] bg-[#fff8fb] px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#b07a8e]">
                    Phạm vi
                  </p>
                  <p className="mt-2 text-[15px] font-semibold text-[#17141a]">{contextValue}</p>
                  <p className="mt-1 text-[12px] leading-5 text-[#7a646f]">{contextDetail}</p>
                </div>
                <div className="rounded-[18px] border border-[#ecdce3] bg-white px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#b07a8e]">
                    Kết quả
                  </p>
                  <p className="mt-2 text-[15px] font-semibold text-[#17141a]">
                    {totalResults > 0 ? `${totalResults} tài nguyên phù hợp` : 'Chưa có kết quả phù hợp'}
                  </p>
                  <p className="mt-1 text-[12px] leading-5 text-[#7a646f]">
                    {hasActiveFilters ? 'Bạn đang lọc theo truy vấn hoặc bộ lọc.' : 'Hiện chưa áp dụng bộ lọc nào.'}
                  </p>
                </div>
              </div>
            </div>
          </div>
          {hasActiveFilters ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-[#ecdce3] bg-white/70 px-4 py-3">
              <p className="text-[12px] leading-5 text-[#7a646f]">
                Đang áp dụng truy vấn hoặc bộ lọc. Bạn có thể xóa nhanh để quay lại toàn thư viện.
              </p>
              <button
                type="button"
                onClick={handleResetFilters}
                className="theme-button-secondary px-4 py-2 text-[12px]"
              >
                Xóa bộ lọc
              </button>
            </div>
          ) : null}
          <div className="resources-search-shell">
            <form onSubmit={handleSearch} className="resources-search-form">
              <span className="resources-search-leading" aria-hidden="true">
                <img src={searchIcon} alt="" className="h-5 w-5 object-contain" />
              </span>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Tìm kiếm..."
                className="resources-search-input"
              />
              <button type="submit" className="resources-search-submit" aria-label="Tìm kiếm">
                <img src={downArrowIcon} alt="" className="h-4 w-4 object-contain" />
              </button>
            </form>

            <div className="resources-filter-row">
              <div className="resources-filter-pill">
                <select
                  value={filters.level}
                  onChange={(e) => handleFilterChange('level', e.target.value)}
                  className="resources-filter-select"
                  aria-label="Lọc theo cấp độ"
                >
                  <option value="">Tất cả cấp độ</option>
                  <option value="beginner">Bắt đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
              </div>

              <div className="resources-filter-pill">
                <select
                  value={filters.source}
                  onChange={(e) => handleFilterChange('source', e.target.value)}
                  className="resources-filter-select"
                  aria-label="Lọc theo nguồn"
                >
                  <option value="">Tất cả nguồn</option>
                  <option value="youtube">YouTube</option>
                  <option value="pdf">PDF</option>
                  <option value="web">Trang web</option>
                </select>
              </div>

              <div className="resources-filter-pill">
                <select
                  value={sortOption}
                  onChange={(e) => setSortOption(e.target.value as ResourceSortOption)}
                  className="resources-filter-select"
                  aria-label="Sắp xếp tài nguyên"
                >
                  {RESOURCE_SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              {canManageResources ? (
                <button
                  type="button"
                  onClick={() => setShowAddResource((previous) => !previous)}
                  className="resources-filter-action"
                >
                  {showAddResource ? 'Thu gọn' : 'Thêm tài nguyên'}
                </button>
              ) : null}
            </div>
          </div>
          {hasActiveFilters ? (
            <div className="flex flex-wrap items-center gap-2">
              {activeFilterChips.map((chip) => (
                <span
                  key={chip}
                  className="rounded-full border border-[#ecdce3] bg-[#fff8fb] px-3 py-1.5 text-[11px] font-medium text-[#8c3451]"
                >
                  {chip}
                </span>
              ))}
              <span className="rounded-full border border-[#e5edf5] bg-[#f7fbff] px-3 py-1.5 text-[11px] font-medium text-[#2f657f]">
                {selectedSourceLabel}
              </span>
            </div>
          ) : null}
        </div>

        {canManageResources && showAddResource && (
          <div className="white-panel mb-[40px] p-5 sm:p-6 lg:p-8">
            <div className="mb-6 grid gap-4 xl:grid-cols-[minmax(0,1.8fr)_minmax(280px,1fr)] xl:items-start">
              <div className="max-w-2xl">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#b07a8e]">
                  {selectedFormCopy.kicker}
                </p>
                <h2 className="mt-3 text-[24px] font-semibold tracking-[-0.04em] text-[#17141a] sm:text-[28px]">
                  {selectedFormCopy.title}
                </h2>
                <p className="mt-3 text-[14px] leading-7 text-[#6f5260]">
                  {selectedFormCopy.description}
                </p>
              </div>
              <div className="rounded-[24px] border border-[#f0d7e0] bg-[linear-gradient(180deg,#fffafd_0%,#fff4f8_100%)] p-4 sm:p-5">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#b07a8e]">
                  Hướng dẫn nhanh
                </p>
                <p className="mt-3 text-[13px] leading-6 text-[#6f5260]">
                  Chọn đúng loại tài nguyên trước khi nhập dữ liệu. Các trường chủ đề, cấp độ và nội dung rõ ràng sẽ giúp hệ thống gợi ý chính xác hơn.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded-full border border-white/80 bg-white/80 px-3 py-1.5 text-[11px] font-medium text-[#8c3451]">
                    Có thể đổi loại ngay trong khung
                  </span>
                  <span className="rounded-full border border-white/80 bg-white/80 px-3 py-1.5 text-[11px] font-medium text-[#8c3451]">
                    Ưu tiên tiêu đề ngắn và dễ quét
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setShowAddResource(false)}
                  className="theme-button-secondary mt-5 justify-center px-5 py-3 text-[13px]"
                >
                  Thu gọn khung thêm mới
                </button>
              </div>
            </div>

            <div className="mb-6 grid gap-3 rounded-[24px] border border-[#f0d7e0] bg-[linear-gradient(180deg,#fffafd_0%,#fff4f8_100%)] p-4 sm:grid-cols-2 sm:p-5">
              {selectedFormCopy.tips.map((tip) => (
                <div
                  key={tip}
                  className="rounded-[18px] border border-white/80 bg-white/75 px-4 py-3 text-[13px] leading-6 text-[#7a5e6d]"
                >
                  {tip}
                </div>
              ))}
            </div>
            <div className="mb-6 grid gap-3 lg:grid-cols-3">
              {RESOURCE_TYPE_OPTIONS.map((option) => (
                <button
                  key={option.type}
                  type="button"
                  onClick={() => setAddResourceType(option.type)}
                  aria-pressed={addResourceType === option.type}
                  className={`rounded-[22px] border px-5 py-4 text-left transition-colors ${
                    addResourceType === option.type
                      ? 'border-[#8c3451] bg-[#8c3451] text-white shadow-[0_18px_36px_rgba(114,62,83,0.18)]'
                      : 'border-[#f0d7e0] bg-[#fff8fb] text-[#8c3451] hover:bg-[#fff1f6]'
                  }`}
                >
                  <p className="text-[14px] font-semibold">{option.label}</p>
                  <p
                    className={`mt-2 text-[12px] leading-5 ${
                      addResourceType === option.type ? 'text-white/80' : 'text-[#7a5e6d]'
                    }`}
                  >
                    {option.description}
                  </p>
                </button>
              ))}
            </div>

            {addResourceType === 'web' && (
              <form ref={webFormRef} onSubmit={handleWebAdd} className="grid gap-4 lg:grid-cols-2">
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Tiêu đề</span>
                  <input
                    type="text"
                    name="title"
                    placeholder="Ví dụ: Tổng quan về Binary Search"
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">URL tham chiếu</span>
                  <input
                    type="url"
                    name="web_url"
                    placeholder="https://example.com"
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Chủ đề</span>
                  <input
                    type="text"
                    name="topic"
                    placeholder="Ví dụ: Thuật toán, React, SQL..."
                    required
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Cấp độ</span>
                  <select
                    name="level"
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  >
                    <option value="beginner">Bắt đầu</option>
                    <option value="intermediate">Trung bình</option>
                    <option value="advanced">Nâng cao</option>
                  </select>
                </label>
                <label className="space-y-2 lg:col-span-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Nội dung hoặc mô tả</span>
                  <textarea
                    name="content"
                    placeholder="Tóm tắt ngắn nội dung, ghi chú chính hoặc trích ý quan trọng của tài nguyên..."
                    required
                    rows={6}
                    className="theme-input w-full resize-y rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <div className="flex flex-col gap-3 sm:flex-row lg:col-span-2">
                  <button
                    type="submit"
                    disabled={addingResource}
                    className="theme-button w-full px-6 py-3 text-[13px] disabled:opacity-50 sm:w-auto"
                  >
                    {addingResource ? 'Đang thêm...' : selectedFormCopy.submitLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="theme-button-secondary w-full px-6 py-3 text-[13px] sm:w-auto"
                  >
                    {'Hủy'}
                  </button>
                </div>
              </form>
            )}


            {addResourceType === 'youtube' && (
              <form ref={youtubeFormRef} onSubmit={handleYouTubeAdd} className="grid gap-4 lg:grid-cols-2">
                <label className="space-y-2 lg:col-span-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Liên kết YouTube</span>
                  <input
                    type="url"
                    name="youtube_url"
                    placeholder="https://www.youtube.com/watch?v=..."
                    required
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Tiêu đề</span>
                  <input
                    type="text"
                    name="title"
                    placeholder="Ví dụ: React Query trong 20 phút"
                    required
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Chủ đề</span>
                  <input
                    type="text"
                    name="topic"
                    placeholder="Ví dụ: Frontend, CI/CD, System Design..."
                    required
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Cấp độ</span>
                  <select
                    name="level"
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  >
                    <option value="beginner">Bắt đầu</option>
                    <option value="intermediate">Trung bình</option>
                    <option value="advanced">Nâng cao</option>
                  </select>
                </label>
                <div className="rounded-[18px] border border-[#f0d7e0] bg-[#fff8fb] px-4 py-3 text-[12px] leading-6 text-[#7a5e6d]">
                  Ưu tiên dùng tiêu đề gần với nội dung video để thumbnail, tiêu đề và gợi ý liên quan nhất quán hơn.
                </div>
                <div className="flex flex-col gap-3 sm:flex-row lg:col-span-2">
                  <button
                    type="submit"
                    disabled={addingResource}
                    className="theme-button w-full px-6 py-3 text-[13px] disabled:opacity-50 sm:w-auto"
                  >
                    {addingResource ? 'Đang thêm...' : selectedFormCopy.submitLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="theme-button-secondary w-full px-6 py-3 text-[13px] sm:w-auto"
                  >
                    {'Hủy'}
                  </button>
                </div>
              </form>
            )}


            {addResourceType === 'pdf' && (
              <form ref={pdfFormRef} onSubmit={handlePDFUpload} className="grid gap-4 lg:grid-cols-2">
                <label className="space-y-2 lg:col-span-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Tệp PDF</span>
                  <input
                    type="file"
                    name="pdf_file"
                    accept=".pdf"
                    required
                    className="w-full rounded-[14px] border border-[#e4b6d0] bg-white px-4 py-3 text-[13px] text-[#6f5260]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Chủ đề</span>
                  <input
                    type="text"
                    name="topic"
                    placeholder="Ví dụ: Machine Learning cơ bản"
                    required
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  />
                </label>
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Cấp độ</span>
                  <select
                    name="level"
                    className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                  >
                    <option value="beginner">Bắt đầu</option>
                    <option value="intermediate">Trung bình</option>
                    <option value="advanced">Nâng cao</option>
                  </select>
                </label>
                <div className="rounded-[18px] border border-[#f0d7e0] bg-[#fff8fb] px-4 py-3 text-[12px] leading-6 text-[#7a5e6d] lg:col-span-2">
                  Sau khi tải lên, hệ thống có thể cần vài phút để trích nội dung và đồng bộ preview. Giữ tên file ngắn, rõ chủ đề để dễ tra cứu hơn.
                </div>
                <div className="flex flex-col gap-3 sm:flex-row lg:col-span-2">
                  <button
                    type="submit"
                    disabled={uploadingPDF}
                    className="theme-button w-full px-6 py-3 text-[13px] disabled:opacity-50 sm:w-auto"
                  >
                    {uploadingPDF ? 'Đang tải lên...' : selectedFormCopy.submitLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="theme-button-secondary w-full px-6 py-3 text-[13px] sm:w-auto"
                  >
                    {'Hủy'}
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        {loading ? (
          <StatusPanel
            className="flex min-h-[320px] items-center justify-center sm:min-h-[400px]"
            centered
            tone="info"
            description={'Đang tải tài nguyên...'}
          />
        ) : resources.length === 0 ? (
          <StatusPanel
            className="white-panel px-6 py-12 sm:px-10 sm:py-[60px] shadow-none"
            centered
            tone="info"
            title={'Không tìm thấy tài nguyên nào'}
            description={'Hãy thử tìm kiếm lại, nới bộ lọc hoặc thêm tài nguyên mới.'}
          />
        ) : (
          <>
            <div className="mb-[40px] grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              {displayedResources.map(({ resource, relevanceScore }) => {
                const sourceTheme = getSourceTheme(resource.source);
                const resourceId = getResourceIdentifier(resource);
                const displayTitle = getDisplayTitle(resource);
                const previewText = getDisplaySnippet(resource);

                return (
                  <article
                    key={resourceId || displayTitle}
                    className="group flex min-h-[420px] flex-col overflow-hidden rounded-[30px] border border-[#ebe2e8] bg-[linear-gradient(180deg,#ffffff_0%,#fffafc_100%)] p-5 shadow-[0_18px_40px_rgba(114,62,83,0.08)] transition-all duration-200 hover:-translate-y-1.5 hover:shadow-[0_26px_54px_rgba(114,62,83,0.14)] sm:min-h-[460px] sm:rounded-[34px] sm:p-6"
                  >
                    <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <p className="text-[12px] font-semibold tracking-[0.08em] text-[#8d7e84]">
                          {resource.topic || 'Bunny Library'}
                        </p>
                        <h3 className="mt-3 line-clamp-2 break-words text-[22px] font-semibold leading-[1.22] tracking-[-0.04em] text-[#17141a]">
                          {displayTitle}
                        </h3>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-start gap-2 sm:justify-end">
                        {resource.is_completed ? (
                          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700">
                            {'Đã học xong'}
                          </span>
                        ) : null}
                        <span
                          className={`rounded-full px-3 py-1.5 text-[11px] font-medium ${getLevelColor(resource.level)}`}
                        >
                          {getLevelLabel(resource.level)}
                        </span>
                        {!resource.is_completed ? (
                          <button
                            type="button"
                            onClick={() => void handleMarkResourceCompleted(resource)}
                            className="rounded-full border border-emerald-200 bg-white px-3 py-1.5 text-[11px] font-medium text-emerald-700 transition hover:bg-emerald-50"
                          >
                            {'Đánh dấu đã học'}
                          </button>
                        ) : null}
                        {canManageResources ? (
                          <button
                            type="button"
                            onClick={() => void handleDeleteResource(resource)}
                            disabled={deletingResourceId === resourceId}
                            className="rounded-full border border-[#ebe2e7] bg-white px-3 py-1.5 text-[11px] font-medium text-[#8c3451] transition-colors hover:bg-[#fff4f8] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {deletingResourceId === resourceId ? 'Đang xóa...' : 'Xóa'}
                          </button>
                        ) : null}
                      </div>
                    </div>

                    <div className="mb-5 flex items-center justify-between gap-3">
                      <span
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[12px] font-medium ${sourceTheme.chip}`}
                      >
                        {getSourceLabel(resource.source)}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="rounded-full px-3 py-1 text-[11px] font-semibold semantic-pill-blue">
                          {Math.round(relevanceScore * 100)}%
                        </span>
                        <span
                          className={`flex h-11 w-11 items-center justify-center rounded-full border ${sourceTheme.icon}`}
                        >
                          {getSourceIcon(resource.source)}
                        </span>
                      </div>
                    </div>

                    <div
                      className={`mb-5 rounded-[24px] border px-4 py-4 ${sourceTheme.soft} border-white/70`}
                    >
                      <p className="line-clamp-2 min-h-[48px] break-words text-[13px] leading-5 text-[#6a625d] sm:text-[14px]">
                        {previewText}
                      </p>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleOpenResource(resource)}
                      className="theme-button mt-4 w-full justify-center"
                    >
                      Mở tài nguyên
                    </button>
                  </article>
                );
              })}
              </div>
              <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
                <div className="soft-panel p-5">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#3b82f6]">
                    Gợi ý từ AI
                  </p>
                  <h3 className="mt-3 text-[22px] font-semibold tracking-[-0.04em] text-[#17141a]">
                    Tài nguyên nổi bật
                  </h3>
                  <p className="mt-3 text-[13px] leading-6 text-[#625954]">
                    Các gợi ý này được sắp theo mức phù hợp với truy vấn, nguồn và cấp độ đang xem.
                  </p>
                </div>
                {featuredResources.map(({ resource, relevanceScore }) => (
                  <div
                    key={`featured-${getResourceIdentifier(resource) || resource.title}`}
                    className="white-panel p-5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[15px] font-semibold leading-6 text-[#17141a]">
                          {getDisplayTitle(resource)}
                        </p>
                        <p className="mt-1 text-[12px] text-[#8f6075]">{resource.topic}</p>
                      </div>
                      <span className="rounded-full px-3 py-1 text-[11px] font-semibold semantic-pill-blue">
                        {Math.round(relevanceScore * 100)}%
                      </span>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${getLevelColor(resource.level)}`}>
                        {getLevelLabel(resource.level)}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleOpenResource(resource)}
                      className="theme-button mt-4 w-full justify-center"
                    >
                      Mở tài nguyên
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {totalPages > 1 && (
              <div className="mb-[40px] flex flex-wrap justify-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="theme-button-secondary px-4 py-2 text-[12px] disabled:opacity-50"
                >
                  {'← Trước'}
                </button>
                {paginationItems.map((item, index) =>
                  item === 'ellipsis' ? (
                    <span
                      key={`ellipsis-${index}`}
                      className="flex items-center px-2 text-[12px] font-medium text-[#8f7b87]"
                    >
                      ...
                    </span>
                  ) : (
                    <button
                      key={item}
                      onClick={() => setCurrentPage(item)}
                      className={`min-w-[36px] rounded-[8px] px-3 py-1 text-[12px] transition-colors ${
                        currentPage === item
                          ? 'bg-[#8c3451] text-white'
                          : 'border border-[#ce6a86] bg-white/80 hover:bg-[#fff4f8]'
                      }`}
                    >
                      {item}
                    </button>
                  ),
                )}
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="theme-button-secondary px-4 py-2 text-[12px] disabled:opacity-50"
                >
                  {'Sau →'}
                </button>
              </div>
            )}
          </>
        )}

        {resources.length > 0 && (
          <div className="mt-[40px] text-center text-[13px] text-gray-600">
            {`Hiển thị ${resultRangeStart} đến ${resultRangeEnd} trên tổng ${totalResults} tài nguyên`}
          </div>
        )}
      </div>

      {playingVideo && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#1f0f17]/80 p-3 backdrop-blur-sm sm:p-4"
          onClick={() => setPlayingVideo(null)}
        >
          <div
            className="w-full max-w-4xl overflow-hidden rounded-[24px] border border-[#f0d7e0] bg-white shadow-[0_28px_80px_rgba(45,31,17,0.28)] sm:rounded-[28px]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 bg-[linear-gradient(135deg,#8c3451_0%,#6f2a40_100%)] px-4 py-4 sm:px-6">
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-white/70">
                  Tài nguyên video
                </p>
                <h3 className="mt-2 line-clamp-2 pr-2 text-[15px] font-semibold text-white sm:text-[16px]">
                  {playingVideo.title}
                </h3>
              </div>
              <button
                onClick={() => setPlayingVideo(null)}
                className="shrink-0 rounded-full p-2 text-white transition-colors hover:bg-white/10"
                aria-label="Đóng"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>
            <div className="border-b border-[#f1e4ea] bg-[#fff8fb] px-4 py-3 text-[13px] leading-6 text-[#6f5260] sm:px-6">
              {'Xem trực tiếp trong modal, nhấn '}
              <span className="font-semibold text-[#8c3451]">Esc</span>
              {' hoặc bấm ra ngoài để đóng.'}
            </div>
            <div className="relative w-full bg-black" style={{ paddingBottom: '56.25%' }}>
              <iframe
                className="absolute inset-0 w-full h-full"
                src={`https://www.youtube.com/embed/${playingVideo.videoId}?autoplay=1`}
                title={playingVideo.title}
                frameBorder="0"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          </div>
        </div>
      )}

      <PDFViewer
        isOpen={!!viewingPDF}
        title={viewingPDF?.title || ''}
        resourceId={viewingPDF?.resourceId || ''}
        onClose={() => setViewingPDF(null)}
      />

      {toast && (
        <div className="ui-toast-fade fixed inset-x-4 top-4 z-[60] mx-auto max-w-[360px] sm:inset-x-auto sm:right-5 sm:top-5 sm:mx-0">
          <div
            className={`rounded-[22px] border px-4 py-3 shadow-[0_18px_36px_rgba(114,62,83,0.18)] backdrop-blur-md ${
              toast.type === 'success'
                ? 'border-emerald-200 bg-white/95 text-emerald-700'
                : 'border-rose-200 bg-white/95 text-rose-700'
            }`}
          >
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] opacity-70">
              {toast.type === 'success' ? 'Thành công' : 'Có lỗi xảy ra'}
              </p>
            <p className="mt-1 text-[13px] font-medium">{toast.message}</p>
          </div>
        </div>
      )}

      {canManageResources && pendingDeleteResource && (
        <div
          className="ui-fade-in fixed inset-0 z-50 flex items-center justify-center bg-[#3d1f2c]/30 px-4 backdrop-blur-sm"
          onClick={() => {
            if (!deletingResourceId) {
              setPendingDeleteResource(null);
            }
          }}
        >
          <div
            className="ui-pop-in white-panel w-full max-w-[460px] rounded-[24px] border border-[#f0c7d5] p-5 shadow-[0_24px_50px_rgba(114,62,83,0.18)] sm:rounded-[28px] sm:p-7"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="mb-2 text-[12px] font-semibold uppercase tracking-[0.28em] text-[#b07a8e]">
                  {'Xác nhận xóa'}
                </p>
                <h3 className="text-[24px] font-semibold tracking-[-0.04em] text-[#8c3451] sm:text-[28px]">
                  {'Xóa tài nguyên này?'}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setPendingDeleteResource(null)}
                disabled={!!deletingResourceId}
                className="rounded-full p-2 text-[#8c3451] transition hover:bg-[#fff3f7] disabled:opacity-50"
                aria-label="Đóng"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="mb-4 rounded-[18px] bg-[#fff8fb] px-4 py-3 text-[12px] font-medium text-[#8c3451]">
              {getSourceLabel(pendingDeleteResource.source)} {'•'} {pendingDeleteResource.topic || 'Thư viện học tập'}
            </div>
            <p className="mb-6 text-[14px] leading-6 text-[#6f5260]">
              {'Tài nguyên '}
              <span className="font-semibold text-[#8c3451]">
                {getDisplayTitle(pendingDeleteResource)}
              </span>{' '}
              {'sẽ bị xóa khỏi danh sách, đồng thời dọn luôn dữ liệu chunk và gợi ý liên quan trong hệ'}
              {' thống.'}
            </p>

            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setPendingDeleteResource(null)}
                disabled={!!deletingResourceId}
                className="theme-button-secondary justify-center px-5 py-3 text-[13px] disabled:opacity-50"
              >
                {'Giữ lại'}
              </button>
              <button
                type="button"
                onClick={() => void handleConfirmDeleteResource()}
                disabled={!!deletingResourceId}
                className="theme-button justify-center px-5 py-3 text-[13px] disabled:opacity-50"
              >
                {deletingResourceId ? 'Đang xóa...' : 'Xóa tài nguyên'}
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}

