import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import PDFViewer from '../components/PDFViewer';
import { resourceService } from '../services/resourceService';
import type { Resource, SearchResponse } from '../services/resourceService';

export default function Resources() {
  const [searchParams] = useSearchParams();
  const conceptIdParam = searchParams.get('concept');
  const queryParam = searchParams.get('q');

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

  useEffect(() => {
    if (queryParam) {
      setSearchQuery(queryParam);
      setCurrentPage(1);
    }
  }, [queryParam]);

  useEffect(() => {
    fetchResources();
  }, [currentPage, filters, searchQuery, conceptIdParam]);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setToast(null);
    }, 2600);

    return () => window.clearTimeout(timer);
  }, [toast]);

  const fetchResources = async () => {
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
  };

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
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const file = form.get('pdf_file') as File;
    const topic = form.get('topic') as string;
    const level = form.get('level') as any;

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
      setShowAddResource(false);
      (e.currentTarget as HTMLFormElement).reset();
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
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const url = form.get('youtube_url') as string;
    const title = form.get('title') as string;
    const topic = form.get('topic') as string;
    const level = form.get('level') as any;

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
      setShowAddResource(false);
      (e.currentTarget as HTMLFormElement).reset();
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
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const url = form.get('web_url') as string;
    const title = form.get('title') as string;
    const content = form.get('content') as string;
    const topic = form.get('topic') as string;
    const level = form.get('level') as any;

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
      setShowAddResource(false);
      (e.currentTarget as HTMLFormElement).reset();
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
    setPendingDeleteResource(resource);
  };

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message });
  };

  const handleConfirmDeleteResource = async () => {
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

  return (
    <DashboardLayout>
      <div className="page-shell pb-6">
        <p className="page-kicker">Tài nguyên</p>
        <h1 className="page-title">
          Tài nguyên học tập
        </h1>

        {error && (
          <div className="white-panel mb-6 border border-red-200 px-4 py-3 text-[14px] text-red-700">
            ✕ {error}
          </div>
        )}

        {statusMessage && !error && (
          <div className="white-panel mb-6 border border-emerald-200 px-4 py-3 text-[14px] text-emerald-700">
            {statusMessage}
          </div>
        )}

        <div className="soft-panel sticky top-4 z-10 mb-[40px] space-y-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-[#6f6661]">
              {totalResults > 0 ? `${totalResults} tài nguyên phù hợp` : 'Tìm kiếm, lọc và thêm tài nguyên nhanh hơn'}
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
            <button
              type="submit"
              className="theme-button justify-center sm:self-auto"
            >
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
              onClick={() => setShowAddResource(!showAddResource)}
              className="theme-button-secondary w-full justify-center sm:ml-auto sm:w-auto"
            >
              + Thêm tài nguyên
            </button>
          </div>
        </div>

        {showAddResource && (
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
              <form onSubmit={handleWebAdd} className="space-y-4">
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
              <form onSubmit={handleYouTubeAdd} className="space-y-4">
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
              <form onSubmit={handlePDFUpload} className="space-y-4">
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
            <div className="mb-[40px] grid grid-cols-1 gap-[22px] md:grid-cols-2 lg:grid-cols-3">
              {resources.map((resource) => (
                <div
                  key={getResourceIdentifier(resource) || resource.title}
                  className="white-panel overflow-hidden rounded-[28px] border border-[#f0c7d5] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_16px_34px_rgba(114,62,83,0.12)]"
                >
                  <div className="p-6">
                    <div className="mb-3 flex items-start justify-between">
                      <div className="flex-1">
                        <h3 className="line-clamp-1 text-[20px] font-semibold tracking-[-0.03em] text-[#8c3451]">
                          {resource.title}
                        </h3>
                      </div>
                      <span
                        className={`ml-2 rounded-full px-3 py-1 text-[11px] font-medium ${getLevelColor(
                          resource.level
                        )}`}
                      >
                        {resource.level === 'beginner'
                          ? 'Cơ bản'
                          : resource.level === 'intermediate'
                          ? 'Trung bình'
                          : 'Nâng cao'}
                      </span>
                    </div>

                    <p className="mb-3 text-[12px] text-[#7f3650]">
                      Nguồn: {resource.source === 'pdf' ? 'PDF' : resource.source === 'youtube' ? 'YouTube' : 'Trang web'}
                    </p>
                    <div className="mb-3 flex items-center justify-end">
                      <button
                        type="button"
                        onClick={() => void handleDeleteResource(resource)}
                        disabled={deletingResourceId === getResourceIdentifier(resource)}
                        className="rounded-full border border-[#efc7d4] px-3 py-1.5 text-[11px] font-medium text-[#8c3451] transition-colors hover:bg-[#fff1f6] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {deletingResourceId === getResourceIdentifier(resource) ? 'Đang xóa...' : 'Xóa'}
                      </button>
                    </div>
                    {(resource.snippet || resource.content_summary) && (
                      <p className="line-clamp-2 text-[13px] leading-6 text-[#6f5260]">
                        {resource.snippet || resource.content_summary}
                      </p>
                    )}
                  </div>

                  <div className="mx-6 mb-6 flex h-[260px] items-center justify-center overflow-hidden rounded-[24px] bg-[#fdf5f8] shadow-[0_12px_24px_rgba(114,62,83,0.08)] sm:h-[309px]">
                    {resource.source === 'youtube' ? (
                      (() => {
                        const thumbnailUrl = getYouTubeThumbnail(resource);
                        return thumbnailUrl ? (
                          <div
                            className="relative w-full h-full cursor-pointer group"
                            onClick={() => handlePlayVideo(resource)}
                          >
                            <img
                              src={thumbnailUrl}
                              alt={resource.title}
                              className="w-full h-full object-cover"
                              onError={(e) => {
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.parentElement!.innerHTML =
                                  '<p class="text-[10px] text-[#7f3650] text-center px-4">Thumbnail clip YouTube</p>';
                              }}
                            />
                            <div className="absolute inset-0 flex items-center justify-center bg-[#8c3451]/0 transition-all group-hover:bg-[#8c3451]/20">
                              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#8c3451] opacity-85 transition-transform group-hover:scale-110 group-hover:opacity-100">
                                <svg className="w-8 h-8 text-white ml-1" fill="currentColor" viewBox="0 0 24 24">
                                  <path d="M8 5v14l11-7z" />
                                </svg>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <p className="text-[10px] text-[#7f3650] text-center px-4">Thumbnail clip YouTube</p>
                        );
                      })()
                    ) : resource.source === 'pdf' ? (
                      <div
                        className="relative w-full h-full cursor-pointer group"
                        onClick={() => {
                          const resourceId = resource.resource_id || resource._id || resource.id || '';
                          if (!resourceId) {
                            setError('Không tìm thấy ID tài nguyên PDF');
                            return;
                          }
                          setViewingPDF({ title: resource.title, resourceId });
                        }}
                      >
                        {resource.thumbnail ? (
                          <img
                            src={resource.thumbnail}
                            alt={resource.title}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              e.currentTarget.style.display = 'none';
                              e.currentTarget.parentElement!.innerHTML =
                                '<p class="text-[10px] text-gray-600 text-center px-4 flex items-center justify-center h-full">PDF không có preview</p>';
                            }}
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center bg-[#f9eef2] px-4 text-center">
                            <p className="text-[10px] text-[#7f3650]">PDF</p>
                          </div>
                        )}
                        <div className="absolute inset-0 flex items-center justify-center bg-[#8c3451]/0 transition-all group-hover:bg-[#8c3451]/20">
                              <div className="rounded-full bg-white p-3 opacity-0 transition-opacity group-hover:opacity-100">
                            <svg className="w-6 h-6 text-[#8c3451]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            </svg>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="w-full h-full" />
                    )}
                  </div>
                </div>
              ))}
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
            Hiển thị {(currentPage - 1) * pageSize + 1} đến {Math.min(currentPage * pageSize, totalResults)} trên tổng{' '}
            {totalResults} tài nguyên
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
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
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

      {pendingDeleteResource && (
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
              Tài nguyên <span className="font-semibold text-[#8c3451]">{pendingDeleteResource.title}</span> sẽ bị xóa khỏi danh sách,
              đồng thời dọn luôn dữ liệu chunk và gợi ý liên quan trong hệ thống.
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
