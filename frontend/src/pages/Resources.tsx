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
  const [currentPage, setCurrentPage] = useState(1);
  const [totalResults, setTotalResults] = useState(0);
  const pageSize = 12;

  // Filters
  const [filters, setFilters] = useState({
    level: '',
    source: '',
  });

  const [showAddResource, setShowAddResource] = useState(false);
  const [addResourceType, setAddResourceType] = useState<'pdf' | 'youtube' | 'web'>('web');

  // Loading states
  const [uploadingPDF, setUploadingPDF] = useState(false);
  const [addingResource, setAddingResource] = useState(false);

  // Video player state
  const [playingVideo, setPlayingVideo] = useState<{
    videoId: string;
    title: string;
  } | null>(null);

  // PDF viewer state
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
      const message = err instanceof Error ? err.message : 'Error fetching resources';
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

  const handlePDFUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const file = form.get('pdf_file') as File;
    const topic = form.get('topic') as string;
    const level = form.get('level') as any;

    if (!file || !topic) {
      setError('Please fill in all fields');
      return;
    }

    setUploadingPDF(true);
    setError(null);

    try {
      await resourceService.uploadPDF(file, topic, level);
      setShowAddResource(false);
      (e.currentTarget as HTMLFormElement).reset();
      await fetchResources();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error uploading PDF';
      setError(message);
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
      setError('Please fill in all fields');
      return;
    }

    setAddingResource(true);
    setError(null);

    try {
      await resourceService.addYouTubeResource(url, title, topic, level);
      setShowAddResource(false);
      (e.currentTarget as HTMLFormElement).reset();
      await fetchResources();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error adding YouTube resource';
      setError(message);
    } finally {
      setAddingResource(false);
    }
  };

  const handleWebAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const url = form.get('web_url') as string;
    const title = form.get('title') as string;
    const topic = form.get('topic') as string;
    const level = form.get('level') as any;

    if (!url || !title || !topic) {
      setError('Please fill in all fields');
      return;
    }

    setAddingResource(true);
    setError(null);

    try {
      await resourceService.addWebResource(url, title, topic, level, 0);
      setShowAddResource(false);
      (e.currentTarget as HTMLFormElement).reset();
      await fetchResources();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error adding web resource';
      setError(message);
    } finally {
      setAddingResource(false);
    }
  };

  const totalPages = Math.ceil(totalResults / pageSize);

  // Helper function to extract YouTube video ID
  const extractVideoId = (resource: Resource): string | null => {
    // Try to get from video_id field first
    if (resource.video_id) {
      return resource.video_id;
    }

    // Try to extract from youtube_url or url
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

  // Helper function to get YouTube thumbnail URL
  const getYouTubeThumbnail = (resource: Resource): string | null => {
    // Try to get from metadata first
    if (resource.video_metadata?.thumbnail_url) {
      return resource.video_metadata.thumbnail_url;
    }

    // Fallback: use extractVideoId helper
    const videoId = extractVideoId(resource);
    if (videoId) {
      return `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
    }

    return null;
  };

  // Handle click on YouTube thumbnail to play video
  const handlePlayVideo = (resource: Resource) => {
    const videoId = extractVideoId(resource);
    if (videoId) {
      setPlayingVideo({
        videoId,
        title: resource.title,
      });
    }
  };

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'beginner':
        return 'bg-[#16a34a] text-white';
      case 'intermediate':
        return 'bg-yellow-100 text-yellow-800';
      case 'advanced':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <DashboardLayout>
      <div className="max-w-[1190px]">
        {/* Page Title */}
        <h1 className="text-[25px] font-semibold text-[#8f1025] mb-[30px] mt-[25px]">
          Tài nguyên học tập
        </h1>

        {/* Error Alert */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-[12px] mb-[40px] text-[14px]">
            ✕ {error}
          </div>
        )}

        {/* Search & Controls */}
        <div className="mb-[40px] space-y-4">
          {/* Search Bar */}
          <form onSubmit={handleSearch} className="flex gap-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm tài nguyên..."
              className="flex-1 px-4 py-2 border border-[#e4b6d0] rounded-[12px] text-[14px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
            />
            <button
              type="submit"
              className="bg-[#8f1025] text-white text-[14px] font-medium px-6 py-2 rounded-[12px] hover:bg-[#7a0e20] transition-colors"
            >
              Tìm
            </button>
          </form>

          {/* Filter Bar */}
          <div className="flex flex-wrap gap-3 items-center">
            {/* Level Filter */}
            <select
              value={filters.level}
              onChange={(e) => handleFilterChange('level', e.target.value)}
              className="px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
            >
              <option value="">Tất cả cấp độ</option>
              <option value="beginner">Bước đầu</option>
              <option value="intermediate">Trung bình</option>
              <option value="advanced">Nâng cao</option>
            </select>

            {/* Source Filter */}
            <select
              value={filters.source}
              onChange={(e) => handleFilterChange('source', e.target.value)}
              className="px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
            >
              <option value="">Tất cả nguồn</option>
              <option value="youtube">YouTube</option>
              <option value="pdf">PDF</option>
              <option value="web">Web</option>
            </select>

            {/* Add Resource Button */}
            <button
              onClick={() => setShowAddResource(!showAddResource)}
              className="bg-white border border-[#8f1025] text-[#8f1025] text-[13px] font-medium px-4 py-2 rounded-[10px] hover:bg-gray-50 transition-colors ml-auto"
            >
              + Thêm tài nguyên
            </button>
          </div>
        </div>

        {/* Add Resource Form */}
        {showAddResource && (
          <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 mb-[40px]">
            <div className="flex gap-4 mb-6">
              {(['web', 'youtube', 'pdf'] as const).map((type) => (
                <button
                  key={type}
                  onClick={() => setAddResourceType(type)}
                  className={`px-4 py-2 rounded-[10px] font-medium text-[13px] transition-colors ${
                    addResourceType === type
                      ? 'bg-[#8f1025] text-white'
                      : 'bg-gray-100 text-[#8f1025] hover:bg-gray-200'
                  }`}
                >
                  {type === 'web' ? '🌐 Web' : type === 'youtube' ? '▶️ YouTube' : '📄 PDF'}
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
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <input
                  type="url"
                  name="web_url"
                  placeholder="URL"
                  required
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <input
                  type="text"
                  name="topic"
                  placeholder="Chủ đề"
                  required
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <select
                  name="level"
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={addingResource}
                    className="bg-[#8f1025] text-white text-[13px] font-medium px-6 py-2 rounded-[10px] hover:bg-[#7a0e20] disabled:opacity-50"
                  >
                    {addingResource ? 'Đang thêm...' : 'Thêm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="bg-gray-100 text-[#8f1025] text-[13px] font-medium px-6 py-2 rounded-[10px]"
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
                  placeholder="YouTube URL"
                  required
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <input
                  type="text"
                  name="title"
                  placeholder="Tiêu đề"
                  required
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <input
                  type="text"
                  name="topic"
                  placeholder="Chủ đề"
                  required
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <select
                  name="level"
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={addingResource}
                    className="bg-[#8f1025] text-white text-[13px] font-medium px-6 py-2 rounded-[10px] hover:bg-[#7a0e20] disabled:opacity-50"
                  >
                    {addingResource ? 'Đang thêm...' : 'Thêm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="bg-gray-100 text-[#8f1025] text-[13px] font-medium px-6 py-2 rounded-[10px]"
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
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                />
                <select
                  name="level"
                  className="w-full px-4 py-2 border border-[#e4b6d0] rounded-[10px] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
                >
                  <option value="beginner">Bước đầu</option>
                  <option value="intermediate">Trung bình</option>
                  <option value="advanced">Nâng cao</option>
                </select>
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={uploadingPDF}
                    className="bg-[#8f1025] text-white text-[13px] font-medium px-6 py-2 rounded-[10px] hover:bg-[#7a0e20] disabled:opacity-50"
                  >
                    {uploadingPDF ? 'Đang upload...' : 'Upload'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddResource(false)}
                    className="bg-gray-100 text-[#8f1025] text-[13px] font-medium px-6 py-2 rounded-[10px]"
                  >
                    Hủy
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        {/* Resources Grid */}
        {loading ? (
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#8f1025] mx-auto mb-4"></div>
              <p className="text-[#8f1025]">Đang tải tài nguyên...</p>
            </div>
          </div>
        ) : resources.length === 0 ? (
          <div className="bg-white border border-[#ce6a86] rounded-[20px] p-[60px] text-center">
            <p className="text-[#8f1025] text-[16px]">📭 Không tìm thấy tài nguyên nào</p>
            <p className="text-gray-500 text-[13px] mt-2">Hãy thử tìm kiếm hoặc thêm tài nguyên mới</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-[20px] mb-[40px]">
              {resources.map((resource) => (
                <div
                  key={resource.resource_id}
                  className="bg-white border border-[#832e44] rounded-[5px] hover:shadow-lg transition-all overflow-hidden"
                >
                  {/* Header */}
                  <div className="p-[13px]">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1">
                        <h3 className="text-[18px] font-semibold text-[#5b1724] line-clamp-1">
                          {resource.title}
                        </h3>
                      </div>
                      <span
                        className={`text-[10px] font-normal px-2.5 py-0.5 rounded-full ml-2 ${getLevelColor(
                          resource.level
                        )}`}
                      >
                        {resource.level === 'beginner'
                          ? 'Beginner'
                          : resource.level === 'intermediate'
                          ? 'Intermediate'
                          : 'Advanced'}
                      </span>
                    </div>

                    {/* Source Label */}
                    <p className="text-[12px] text-[#5b1724] mb-3">
                      Nguồn: {resource.source === 'pdf' ? 'PDF' : resource.source === 'youtube' ? 'Youtube' : 'Link Web'}
                    </p>
                  </div>

                  {/* Preview Area */}
                  <div className="bg-[#fafafa] h-[309px] flex items-center justify-center shadow-[0px_0px_4px_0px_rgba(0,0,0,0.25)] mx-[13px] mb-[13px]">
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
                                // Fallback if thumbnail fails to load
                                e.currentTarget.style.display = 'none';
                                e.currentTarget.parentElement!.innerHTML = '<p class="text-[10px] text-black text-center px-4">Thumbnail clip Youtube</p>';
                              }}
                            />
                            {/* Play button overlay */}
                            <div className="absolute inset-0 flex items-center justify-center bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all">
                              <div className="w-16 h-16 bg-red-600 rounded-full flex items-center justify-center transform group-hover:scale-110 transition-transform opacity-80 group-hover:opacity-100">
                                <svg className="w-8 h-8 text-white ml-1" fill="currentColor" viewBox="0 0 24 24">
                                  <path d="M8 5v14l11-7z" />
                                </svg>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <p className="text-[10px] text-black text-center px-4">
                            Thumbnail clip Youtube
                          </p>
                        );
                      })()
                    ) : resource.source === 'pdf' ? (
                      <div 
                        className="relative w-full h-full cursor-pointer group"
                        onClick={() => {
                          const resourceId = resource.resource_id || resource._id || resource.id || '';
                          if (!resourceId) {
                            setError('Khong tim thay ID tai nguyen PDF');
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
                              e.currentTarget.parentElement!.innerHTML = '<p class="text-[10px] text-gray-600 text-center px-4 flex items-center justify-center h-full">📄 PDF không có preview</p>';
                            }}
                          />
                        ) : (
                          <div className="w-full h-full bg-gray-100 flex items-center justify-center text-center px-4">
                            <p className="text-[10px] text-gray-600">📄 PDF</p>
                          </div>
                        )}
                        {/* Hover overlay */}
                        <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-40 transition-all flex items-center justify-center">
                          <div className="opacity-0 group-hover:opacity-100 transition-opacity bg-white rounded-full p-3">
                            <svg className="w-6 h-6 text-[#8f1025]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex justify-center gap-2 mb-[40px]">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="px-3 py-1 text-[12px] border border-[#ce6a86] rounded-[8px] disabled:opacity-50"
                >
                  ← Trước
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`px-3 py-1 text-[12px] rounded-[8px] transition-colors ${
                      currentPage === page
                        ? 'bg-[#8f1025] text-white'
                        : 'border border-[#ce6a86] hover:bg-gray-50'
                    }`}
                  >
                    {page}
                  </button>
                ))}
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="px-3 py-1 text-[12px] border border-[#ce6a86] rounded-[8px] disabled:opacity-50"
                >
                  Sau →
                </button>
              </div>
            )}
          </>
        )}

        {/* Stats */}
        {resources.length > 0 && (
          <div className="text-center text-[13px] text-gray-600 mt-[40px]">
            Hiển thị {(currentPage - 1) * pageSize + 1} đến {Math.min(currentPage * pageSize, totalResults)} trên
            tổng {totalResults} tài nguyên
          </div>
        )}
      </div>

      {/* Video Player Modal */}
      {playingVideo && (
        <div 
          className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
          onClick={() => setPlayingVideo(null)}
        >
          <div 
            className="bg-white rounded-[20px] overflow-hidden max-w-4xl w-full shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="bg-[#8f1025] px-6 py-4 flex items-center justify-between">
              <h3 className="text-white font-semibold text-[16px] flex-1 pr-4 line-clamp-1">
                {playingVideo.title}
              </h3>
              <button
                onClick={() => setPlayingVideo(null)}
                className="text-white hover:bg-[#7a0e20] rounded-full p-2 transition-colors flex-shrink-0"
                aria-label="Đóng"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Video Player */}
            <div className="relative w-full" style={{ paddingBottom: '56.25%' /* 16:9 aspect ratio */ }}>
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

      {/* PDF Viewer Modal */}
      <PDFViewer 
        isOpen={!!viewingPDF}
        title={viewingPDF?.title || ''}
        resourceId={viewingPDF?.resourceId || ''}
        onClose={() => setViewingPDF(null)}
      />
    </DashboardLayout>
  );
}
