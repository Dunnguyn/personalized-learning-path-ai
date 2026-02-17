import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { resourceService } from '../services/resourceService';
import type { Resource, SearchResponse } from '../services/resourceService';

export default function Resources() {
  const [searchParams] = useSearchParams();
  const conceptIdParam = searchParams.get('concept');

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

  useEffect(() => {
    fetchResources();
  }, [currentPage, filters]);

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

  const getSourceIcon = (source: string) => {
    switch (source) {
      case 'youtube':
        return '▶️';
      case 'pdf':
        return '📄';
      case 'web':
        return '🌐';
      default:
        return '📚';
    }
  };

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'beginner':
        return 'bg-green-100 text-green-800';
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
          📚 Tài nguyên học tập
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
              🔍 Tìm
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
                  className="bg-white border border-[#ce6a86] rounded-[16px] p-[20px] hover:shadow-lg transition-all"
                >
                  {/* Header */}
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1">
                      <h3 className="text-[14px] font-semibold text-[#8f1025] line-clamp-2">
                        {resource.title}
                      </h3>
                    </div>
                    <span className="text-[20px] ml-2">{getSourceIcon(resource.source)}</span>
                  </div>

                  {/* Topic & Level */}
                  <div className="flex flex-wrap gap-2 mb-3">
                    <span className="text-[11px] bg-gray-100 text-[#8f1025] px-2 py-1 rounded-full">
                      {resource.topic}
                    </span>
                    <span
                      className={`text-[11px] font-medium px-2 py-1 rounded-full ${getLevelColor(
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

                  {/* Snippet */}
                  {resource.snippet && (
                    <p className="text-[12px] text-gray-600 line-clamp-2 mb-3">{resource.snippet}</p>
                  )}

                  {/* Score */}
                  {resource.score && (
                    <div className="text-[12px] text-gray-500 mb-3">
                      📊 Điểm liên quan: {(resource.score * 100).toFixed(0)}%
                    </div>
                  )}

                  {/* Source Link */}
                  {resource.url && (
                    <a
                      href={resource.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-block text-[12px] text-[#8f1025] font-medium hover:underline mt-2"
                    >
                      🔗 Xem tài nguyên
                    </a>
                  )}
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
    </DashboardLayout>
  );
}
