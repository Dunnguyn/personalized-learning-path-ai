import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import PDFViewer from '../components/PDFViewer';
import { useAuth } from '../contexts/AuthContext';
import { resourceService } from '../services/resourceService';
import { recommendationInteractionService } from '../services/recommendationInteractionService';
import type { Resource, SearchResponse } from '../types/resource';

type ResourceLevel = Resource['level'];
const PDF_PAGE_MARKER_REGEX = /\[Page\s+\d+\]\s*/gi;
const MAX_PREVIEW_LENGTH = 240;

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
  const pageSize = 12;

  const [filters, setFilters] = useState({
    level: '',
    source: '',
  });

  const [showAddResource, setShowAddResource] = useState(false);
  const [addResourceType, setAddResourceType] = useState<'pdf' | 'youtube' | 'web'>('web');
  const [uploadingPDF, setUploadingPDF] = useState(false);
  const [addingResource, setAddingResource] = useState(false);
  const [deletingResourceId, setDeletingResourceId] = useState<string | null>(null);
  const [pendingDeleteResource, setPendingDeleteResource] = useState<Resource | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const [playingVideo, setPlayingVideo] = useState<{
    videoId: string;
    title: string;
  } | null>(null);

  const [viewingPDF, setViewingPDF] = useState<{
    title: string;
    resourceId: string;
  } | null>(null);

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
    if (!toast) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setToast(null);
    }, 2600);

    return () => window.clearTimeout(timer);
  }, [toast]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    await fetchResources();
  };

  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
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
      showToast('error', 'Ban khong co quyen them tai nguyen.');
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
      showToast('error', 'Ban khong co quyen them tai nguyen.');
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
      showToast('error', 'Ban khong co quyen them tai nguyen.');
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

  const getYouTubeThumbnail = (resource: Resource): string | null => {
    if (resource.video_metadata?.thumbnail_url) {
      return resource.video_metadata.thumbnail_url;
    }

    const videoId = extractVideoId(resource);
    if (videoId) {
      return `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
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
      showToast('error', 'Chi admin moi co the xoa tai nguyen.');
      return;
    }
    setPendingDeleteResource(resource);
  };

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message });
  };

  const handleConfirmDeleteResource = async () => {
    if (!canManageResources) {
      showToast('error', 'Chi admin moi co the xoa tai nguyen.');
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
        chip: 'border-[#f2d7e0] bg-[#fff6fa] text-[#9b2f55]',
        icon: 'border-[#f2d7e0] bg-[#fff6fa] text-[#9b2f55]',
        preview: 'bg-[linear-gradient(180deg,#fff9fb_0%,#fcecf3_100%)]',
        accent: 'bg-[#9b2f55]',
        soft: 'bg-[#fff2f7]',
      };
    }

    if (source === 'pdf') {
      return {
        chip: 'border-[#e8dff3] bg-[#fbf8ff] text-[#6d4c8f]',
        icon: 'border-[#e8dff3] bg-[#fbf8ff] text-[#6d4c8f]',
        preview: 'bg-[linear-gradient(180deg,#fffaff_0%,#f5eefc_100%)]',
        accent: 'bg-[#6d4c8f]',
        soft: 'bg-[#f7f1ff]',
      };
    }

    return {
      chip: 'border-[#dbe8f2] bg-[#f6fbff] text-[#2f657f]',
      icon: 'border-[#dbe8f2] bg-[#f6fbff] text-[#2f657f]',
      preview: 'bg-[linear-gradient(180deg,#fbfeff_0%,#edf7fc_100%)]',
      accent: 'bg-[#2f657f]',
      soft: 'bg-[#eef8fd]',
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

  const getResourceTimestamp = (resource: Resource) => {
    if (!resource.created_at) {
      return 'Cập nhật gần đây';
    }

    const date = new Date(resource.created_at);
    if (Number.isNaN(date.getTime())) {
      return 'Cập nhật gần đây';
    }

    return `Cập nhật ${date.toLocaleDateString('vi-VN')}`;
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
      <div className="page-shell pb-6">
        <p className="page-kicker">Thư viện học tập</p>
        <h1 className="page-title">Tài nguyên học tập</h1>

        {error && (
          <div className="white-panel mb-6 border border-red-200 px-4 py-3 text-[14px] text-red-700">
            • {error}
          </div>
        )}

        {statusMessage && !error && (
          <div className="white-panel mb-6 border border-emerald-200 px-4 py-3 text-[14px] text-emerald-700">
            {statusMessage}
          </div>
        )}

        <div
          className={`mb-6 rounded-[24px] border px-5 py-4 text-[14px] leading-6 ${
            canManageResources
              ? 'border-[#ead7df] bg-[#fff7fb] text-[#6f5260]'
              : 'border-[#dbe8f2] bg-[#f6fbff] text-[#2f657f]'
          }`}
        >
          {canManageResources
            ? 'Bạn đang ở chế độ Admin. Tại màn này bạn có thể tìm kiếm, xem và quản lý resource học tập.'
            : 'Tài khoản learner chỉ có quyền xem, tìm kiếm và mở resource. Các thao tác thêm hoặc xóa chỉ dành cho Admin.'}
        </div>

        <div className="soft-panel sticky top-4 z-10 mb-[40px] space-y-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-[#6f6661]">
              {totalResults > 0
                ? `${totalResults} tài nguyên khớp với bộ lọc`
                : 'Tìm kiếm, lọc và thêm tài nguyên nhanh hơn'}
            </p>
          </div>
          <form onSubmit={handleSearch} className="flex flex-col gap-3 sm:flex-row">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm tài nguyên..."
              className="theme-input"
            />
            <button type="submit" className="theme-button justify-center sm:self-auto">
              Tìm
            </button>
          </form>

          <div className="flex flex-wrap items-center gap-3">
            <select
              value={filters.level}
              onChange={(e) => handleFilterChange('level', e.target.value)}
              className="theme-input min-w-[160px] flex-1 rounded-full py-2 sm:w-auto sm:min-w-[180px] sm:flex-none"
            >
              <option value="">Tất cả cấp độ</option>
              <option value="beginner">Bước đầu</option>
              <option value="intermediate">Trung bình</option>
              <option value="advanced">Nâng cao</option>
            </select>

            <select
              value={filters.source}
              onChange={(e) => handleFilterChange('source', e.target.value)}
              className="theme-input min-w-[160px] flex-1 rounded-full py-2 sm:w-auto sm:min-w-[180px] sm:flex-none"
            >
              <option value="">Tất cả nguồn</option>
              <option value="youtube">YouTube</option>
              <option value="pdf">PDF</option>
              <option value="web">Trang web</option>
            </select>

            <button
              disabled={!canManageResources}
              onClick={() => canManageResources && setShowAddResource(!showAddResource)}
              className="theme-button-secondary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50 sm:ml-auto sm:w-auto"
            >
              + Thêm tài nguyên
            </button>
          </div>
        </div>

        {canManageResources && showAddResource && (
          <div className="white-panel mb-[40px] p-8">
            <div className="mb-6 flex flex-wrap gap-3">
              {(['web', 'youtube', 'pdf'] as const).map((type) => (
                <button
                  key={type}
                  onClick={() => setAddResourceType(type)}
                  className={`rounded-full px-5 py-2.5 font-medium text-[13px] transition-colors ${
                    addResourceType === type
                      ? 'bg-[#8c3451] text-white'
                      : 'bg-[#fdf0f5] text-[#8c3451] hover:bg-[#f8dce7]'
                  }`}
                >
                  {type === 'web' ? 'Trang web' : type === 'youtube' ? 'YouTube' : 'PDF'}
                </button>
              ))}
            </div>

            {addResourceType === 'web' && (
              <form ref={webFormRef} onSubmit={handleWebAdd} className="space-y-4">
                <input
                  type="text"
                  name="title"
                  placeholder="Tiêu đề"
                  required
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <input
                  type="url"
                  name="web_url"
                  placeholder="URL (tùy chọn)"
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <input
                  type="text"
                  name="topic"
                  placeholder="Chủ đề"
                  required
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <textarea
                  name="content"
                  placeholder="Nội dung tài nguyên hoặc mô tả chi tiết"
                  required
                  rows={5}
                  className="theme-input w-full resize-y rounded-[14px] px-4 py-3 text-[13px]"
                />
                <select
                  name="level"
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={addingResource}
                    className="theme-button px-6 py-3 text-[13px] disabled:opacity-50"
                  >
                    {addingResource ? 'Đang thêm...' : 'Thêm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="theme-button-secondary px-6 py-3 text-[13px]"
                  >
                    Hủy
                  </button>
                </div>
              </form>
            )}

            {addResourceType === 'youtube' && (
              <form ref={youtubeFormRef} onSubmit={handleYouTubeAdd} className="space-y-4">
                <input
                  type="url"
                  name="youtube_url"
                  placeholder="Liên kết YouTube"
                  required
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <input
                  type="text"
                  name="title"
                  placeholder="Tiêu đề"
                  required
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <input
                  type="text"
                  name="topic"
                  placeholder="Chủ đề"
                  required
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <select
                  name="level"
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={addingResource}
                    className="theme-button px-6 py-3 text-[13px] disabled:opacity-50"
                  >
                    {addingResource ? 'Đang thêm...' : 'Thêm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="theme-button-secondary px-6 py-3 text-[13px]"
                  >
                    Hủy
                  </button>
                </div>
              </form>
            )}

            {addResourceType === 'pdf' && (
              <form ref={pdfFormRef} onSubmit={handlePDFUpload} className="space-y-4">
                <input
                  type="file"
                  name="pdf_file"
                  accept=".pdf"
                  required
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px]"
                />
                <input
                  type="text"
                  name="topic"
                  placeholder="Chủ đề"
                  required
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                />
                <select
                  name="level"
                  className="theme-input w-full rounded-[14px] px-4 py-3 text-[13px]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={uploadingPDF}
                    className="theme-button px-6 py-3 text-[13px] disabled:opacity-50"
                  >
                    {uploadingPDF ? 'Đang tải lên...' : 'Tải lên'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="theme-button-secondary px-6 py-3 text-[13px]"
                  >
                    Hủy
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="text-center">
              <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8c3451]"></div>
              <p className="text-[#8c3451]">Đang tải tài nguyên...</p>
            </div>
          </div>
        ) : resources.length === 0 ? (
          <div className="white-panel p-[60px] text-center">
            <p className="text-[#8c3451] text-[16px]">Không tìm thấy tài nguyên nào</p>
            <p className="text-gray-500 text-[13px] mt-2">
              Hãy thử tìm kiếm hoặc thêm tài nguyên mới
            </p>
          </div>
        ) : (
          <>
            <div className="mb-[40px] grid grid-cols-1 gap-6 md:grid-cols-2 2xl:grid-cols-3">
              {resources.map((resource) => {
                const sourceTheme = getSourceTheme(resource.source);
                const resourceId = getResourceIdentifier(resource);
                const displayTitle = getDisplayTitle(resource);
                const previewText = getDisplaySnippet(resource);
                const resourceHost = resource.url
                  ? resource.url.replace(/^https?:\/\//, '').replace(/^www\./, '')
                  : 'Nguồn web';

                return (
                  <article
                    key={resourceId || displayTitle}
                    className="group flex min-h-[460px] flex-col overflow-hidden rounded-[34px] border border-[#ebe2e8] bg-[linear-gradient(180deg,#ffffff_0%,#fffafc_100%)] p-6 shadow-[0_18px_40px_rgba(114,62,83,0.08)] transition-all duration-200 hover:-translate-y-1.5 hover:shadow-[0_26px_54px_rgba(114,62,83,0.14)]"
                  >
                    <div className="mb-5 flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-[12px] font-semibold tracking-[0.08em] text-[#8d7e84]">
                          {resource.topic || 'Bunny Library'}
                        </p>
                        <h3 className="mt-3 line-clamp-2 break-words text-[22px] font-semibold leading-[1.22] tracking-[-0.04em] text-[#17141a]">
                          {displayTitle}
                        </h3>
                      </div>
                      <div className="flex shrink-0 items-start gap-2">
                        {resource.is_completed ? (
                          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700">
                            Đã học xong
                          </span>
                        ) : null}
                        <span
                          className={`rounded-full px-3 py-1.5 text-[11px] font-medium ${getLevelColor(resource.level)}`}
                        >
                          {getLevelLabel(resource.level)}
                        </span>
                        <button
                          type="button"
                          onClick={() => void handleDeleteResource(resource)}
                          disabled={!canManageResources || deletingResourceId === resourceId}
                          className="rounded-full border border-[#ebe2e7] bg-white px-3 py-1.5 text-[11px] font-medium text-[#8c3451] transition-colors hover:bg-[#fff4f8] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {deletingResourceId === resourceId ? 'Đang xóa...' : 'Xóa'}
                        </button>
                      </div>
                    </div>

                    <div className="mb-5 flex items-center justify-between gap-3">
                      <span
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[12px] font-medium ${sourceTheme.chip}`}
                      >
                        {getSourceLabel(resource.source)}
                      </span>
                      <span
                        className={`flex h-11 w-11 items-center justify-center rounded-full border ${sourceTheme.icon}`}
                      >
                        {getSourceIcon(resource.source)}
                      </span>
                    </div>

                    <div
                      className={`relative mb-5 flex min-h-[250px] flex-1 overflow-hidden rounded-[28px] border border-[#efeaed] ${sourceTheme.preview}`}
                    >
                      {resource.source === 'youtube' ? (
                        (() => {
                          const thumbnailUrl = getYouTubeThumbnail(resource);
                          return thumbnailUrl ? (
                            <button
                              type="button"
                              className="relative h-full w-full overflow-hidden text-left"
                              onClick={() => handleOpenResource(resource)}
                            >
                              <img
                                src={thumbnailUrl}
                                alt={displayTitle}
                                className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                                onError={(e) => {
                                  e.currentTarget.style.display = 'none';
                                  e.currentTarget.parentElement!.innerHTML =
                                    '<p class="flex h-full items-center justify-center px-4 text-center text-[12px] text-[#7f3650]">Xem trước YouTube</p>';
                                }}
                              />
                              <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(19,16,22,0.02)_0%,rgba(19,16,22,0.35)_100%)]" />
                              <div className="absolute inset-x-5 bottom-5 flex items-end justify-between gap-4">
                                <div className="max-w-[70%] rounded-[20px] bg-white/88 px-4 py-3 backdrop-blur-sm">
                                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#9b2f55]">
                                    YouTube
                                  </p>
                                  <p className="mt-1 line-clamp-2 text-[14px] font-medium leading-5 text-[#17141a]">
                                    {displayTitle}
                                  </p>
                                </div>
                                <span
                                  className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-white shadow-[0_18px_30px_rgba(114,62,83,0.18)] ${sourceTheme.accent}`}
                                >
                                  <svg
                                    className="ml-1 h-8 w-8"
                                    fill="currentColor"
                                    viewBox="0 0 24 24"
                                  >
                                    <path d="M8 5v14l11-7z" />
                                  </svg>
                                </span>
                              </div>
                            </button>
                          ) : (
                            <div className="flex h-full w-full items-center justify-center px-6 text-center text-[13px] font-medium text-[#7f3650]">
                              Xem trước YouTube
                            </div>
                          );
                        })()
                      ) : resource.source === 'pdf' ? (
                        <button
                          type="button"
                          className="relative h-full w-full overflow-hidden text-left"
                          onClick={() => handleOpenResource(resource)}
                        >
                          {resource.thumbnail ? (
                            <img
                              src={resource.thumbnail}
                              alt={displayTitle}
                              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                              onError={(e) => {
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.parentElement!.innerHTML =
                                  '<div class="flex h-full flex-col items-center justify-center gap-3 px-4 text-center"><p class="text-[12px] font-medium text-[#7f3650]">PDF không có xem trước</p></div>';
                              }}
                            />
                          ) : (
                            <div
                              className={`flex h-full w-full flex-col items-center justify-center gap-4 px-6 text-center ${sourceTheme.soft}`}
                            >
                              <span
                                className={`flex h-16 w-16 items-center justify-center rounded-[20px] border bg-white shadow-[0_12px_24px_rgba(114,62,83,0.08)] ${sourceTheme.icon}`}
                              >
                                {getSourceIcon(resource.source)}
                              </span>
                              <div>
                                <p className="text-[12px] font-semibold tracking-[0.08em] text-[#8d7e84]">
                                  Tệp PDF
                                </p>
                                <p className="mt-2 text-[16px] font-medium leading-6 text-[#1b171c]">
                                  Xem nhanh tài liệu trực tiếp trong thư viện của bạn.
                                </p>
                              </div>
                            </div>
                          )}
                          <div className="pointer-events-none absolute inset-x-5 bottom-5 flex items-center justify-between gap-4">
                            <div className="rounded-[18px] bg-white/90 px-4 py-3 backdrop-blur-sm">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6d4c8f]">
                                PDF
                              </p>
                              <p className="mt-1 text-[14px] font-medium text-[#17141a]">
                                Xem trước tài liệu
                              </p>
                            </div>
                            <span className="rounded-full bg-white/90 p-3 text-[#8c3451] shadow-[0_12px_24px_rgba(114,62,83,0.12)] backdrop-blur-sm">
                              <svg
                                className="h-6 w-6"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                                />
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                                />
                              </svg>
                            </span>
                          </div>
                        </button>
                      ) : (
                        <div className="flex h-full w-full flex-col justify-between p-6">
                          <div>
                            <p className="text-[12px] font-semibold tracking-[0.08em] text-[#2f657f]/70">
                              Nguồn tham khảo
                            </p>
                            <p className="mt-4 line-clamp-5 text-[17px] font-medium leading-8 text-[#1b171c]">
                              {previewText}
                            </p>
                          </div>
                          <div className="flex items-end justify-between gap-3">
                            <span
                              className={`max-w-[75%] rounded-full px-3 py-2 text-[12px] ${sourceTheme.soft} ${sourceTheme.icon}`}
                            >
                              {resourceHost}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleOpenResource(resource)}
                              className={`rounded-full border bg-white px-4 py-2 text-[12px] font-medium transition hover:bg-white ${sourceTheme.chip}`}
                            >
                              Mở nguồn
                            </button>
                          </div>
                        </div>
                      )}
                    </div>

                    <div
                      className={`rounded-[24px] border px-4 py-4 ${sourceTheme.soft} border-white/70`}
                    >
                      <p className="line-clamp-2 min-h-[44px] break-words text-[13px] leading-6 text-[#6a625d]">
                        {previewText}
                      </p>

                      <div className="mt-4 flex items-center justify-between gap-3 border-t border-white/80 pt-4">
                        <div className="flex min-w-0 items-center gap-3">
                          <span
                            className={`flex h-10 w-10 items-center justify-center rounded-[14px] border bg-white ${sourceTheme.icon}`}
                          >
                            {getSourceIcon(resource.source)}
                          </span>
                          <div className="min-w-0">
                            <p className="text-[13px] font-normal leading-5 tracking-normal text-[#8f7b87]">
                              Mới cập nhật
                            </p>
                            <p className="line-clamp-1 text-[15px] font-semibold leading-6 tracking-[-0.01em] text-[#18141a]">
                              {resource.topic || displayTitle}
                            </p>
                            <p className="text-[12px] font-normal leading-5 tracking-normal text-[#7a726d]">
                              {getResourceTimestamp(resource)}
                            </p>
                          </div>
                        </div>
                        <div className="flex flex-wrap justify-end gap-2">
                          {resource.source !== 'web' && (
                            <button
                              type="button"
                              onClick={() => handleOpenResource(resource)}
                              className={`rounded-full border bg-white px-4 py-2 text-[12px] font-medium transition hover:bg-white ${sourceTheme.chip}`}
                            >
                              {resource.source === 'youtube' ? 'Xem video' : 'Xem trước'}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => void handleMarkResourceCompleted(resource)}
                            disabled={resource.is_completed}
                            className={`rounded-full border px-4 py-2 text-[12px] font-medium transition ${
                              resource.is_completed
                                ? 'cursor-not-allowed border-emerald-200 bg-emerald-50 text-emerald-700'
                                : 'border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50'
                            }`}
                          >
                            {resource.is_completed ? 'Đã học xong' : 'Đánh dấu đã học'}
                          </button>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>

            {totalPages > 1 && (
              <div className="mb-[40px] flex justify-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="theme-button-secondary px-4 py-2 text-[12px] disabled:opacity-50"
                >
                  ← Trước
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`px-3 py-1 text-[12px] rounded-[8px] transition-colors ${
                      currentPage === page
                        ? 'bg-[#8c3451] text-white'
                        : 'border border-[#ce6a86] bg-white/80 hover:bg-[#fff4f8]'
                    }`}
                  >
                    {page}
                  </button>
                ))}
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="theme-button-secondary px-4 py-2 text-[12px] disabled:opacity-50"
                >
                  Sau →
                </button>
              </div>
            )}
          </>
        )}

        {resources.length > 0 && (
          <div className="text-center text-[13px] text-gray-600 mt-[40px]">
            Hiển thị {(currentPage - 1) * pageSize + 1} đến{' '}
            {Math.min(currentPage * pageSize, totalResults)} trên tổng {totalResults} tài nguyên
          </div>
        )}
      </div>

      {playingVideo && (
        <div
          className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
          onClick={() => setPlayingVideo(null)}
        >
          <div
            className="bg-white rounded-[20px] overflow-hidden max-w-4xl w-full shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-[#8c3451] px-6 py-4 flex items-center justify-between">
              <h3 className="text-white font-semibold text-[16px] flex-1 pr-4 line-clamp-1">
                {playingVideo.title}
              </h3>
              <button
                onClick={() => setPlayingVideo(null)}
                className="text-white hover:bg-[#7a2d46] rounded-full p-2 transition-colors flex-shrink-0"
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

            <div className="relative w-full" style={{ paddingBottom: '56.25%' }}>
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
        <div className="ui-toast-fade fixed right-5 top-5 z-[60] max-w-[360px]">
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
          onClick={() => setPendingDeleteResource(null)}
        >
          <div
            className="ui-pop-in white-panel w-full max-w-[420px] rounded-[28px] border border-[#f0c7d5] p-7 shadow-[0_24px_50px_rgba(114,62,83,0.18)]"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="mb-2 text-[12px] font-semibold uppercase tracking-[0.28em] text-[#b07a8e]">
              Xác nhận xóa
            </p>
            <h3 className="mb-3 text-[28px] font-semibold tracking-[-0.04em] text-[#8c3451]">
              Xóa tài nguyên này?
            </h3>
            <p className="mb-6 text-[14px] leading-6 text-[#6f5260]">
              Tài nguyên{' '}
              <span className="font-semibold text-[#8c3451]">
                {getDisplayTitle(pendingDeleteResource)}
              </span>{' '}
              sẽ bị xóa khỏi danh sách, đồng thời dọn luôn dữ liệu chunk và gợi ý liên quan trong hệ
              thống.
            </p>

            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setPendingDeleteResource(null)}
                disabled={!!deletingResourceId}
                className="theme-button-secondary justify-center px-5 py-3 text-[13px] disabled:opacity-50"
              >
                Giữ lại
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
