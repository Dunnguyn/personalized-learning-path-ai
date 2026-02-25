import { useState, useEffect } from 'react';

interface PDFViewerProps {
  isOpen: boolean;
  title: string;
  resourceId: string;
  onClose: () => void;
}

export default function PDFViewer({ isOpen, title, resourceId, onClose }: PDFViewerProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowLoadingHint, setShowSlowLoadingHint] = useState(false);

  const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  const apiBasePath = import.meta.env.VITE_API_BASE_PATH || '/api';
  const normalizedBaseUrl = apiBaseUrl.replace(/\/$/, '');
  const normalizedBasePath = apiBasePath.startsWith('/') ? apiBasePath : `/${apiBasePath}`;
  const pdfUrl = `${normalizedBaseUrl}${normalizedBasePath}/resources/pdf/${resourceId}`;

  // Show hint if loading takes too long
  useEffect(() => {
    if (!loading) return;
    
    const hintTimer = setTimeout(() => {
      setShowSlowLoadingHint(true);
    }, 3000); // Show hint after 3 seconds

    const timeoutTimer = setTimeout(() => {
      setLoading(false);
      setError('Tải PDF quá lâu. Vui lòng thử mở trong tab mới hoặc tải xuống.');
    }, 15000); // Timeout after 15 seconds

    return () => {
      clearTimeout(hintTimer);
      clearTimeout(timeoutTimer);
    };
  }, [loading]);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      setError(null);
      setShowSlowLoadingHint(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const openInNewTab = () => {
    window.open(pdfUrl, '_blank');
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-[10px] w-full max-w-5xl h-[90vh] flex flex-col shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[#e4b6d0]">
          <h2 className="text-[18px] font-semibold text-[#5b1724] truncate">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="text-[24px] text-[#8f1025] hover:bg-gray-100 p-2 rounded-full transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto bg-gray-50 relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-white bg-opacity-75 z-10">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#8f1025] mx-auto mb-4"></div>
                <p className="text-[#8f1025] mb-2">Đang tải PDF...</p>
                {showSlowLoadingHint && (
                  <div className="mt-4 space-y-2">
                    <p className="text-gray-600 text-[13px]">Tải lâu hơn bình thường?</p>
                    <button
                      onClick={openInNewTab}
                      className="px-4 py-2 bg-[#8f1025] text-white text-[12px] rounded-[8px] hover:bg-[#7a0e20]"
                    >
                      🔗 Mở trong tab mới
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
          
          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-white">
              <div className="text-center px-6 max-w-md">
                <p className="text-red-600 text-[16px] mb-4">⚠️ Lỗi tải PDF</p>
                <p className="text-gray-600 text-[14px] mb-6">{error}</p>
                <div className="flex gap-3 justify-center">
                  <button
                    onClick={openInNewTab}
                    className="px-4 py-2 bg-[#8f1025] text-white text-[13px] rounded-[8px] hover:bg-[#7a0e20]"
                  >
                    🔗 Mở trong tab mới
                  </button>
                  <a
                    href={pdfUrl}
                    download
                    className="px-4 py-2 bg-gray-600 text-white text-[13px] rounded-[8px] hover:bg-gray-700"
                  >
                    ⬇️ Tải xuống
                  </a>
                </div>
              </div>
            </div>
          )}

          <iframe
            src={pdfUrl}
            className="w-full h-full border-none"
            title={title}
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false);
              setError('Không thể tải file PDF. Vui lòng thử tải xuống file.');
            }}
          />
        </div>

        {/* Footer */}
        <div className="flex gap-3 p-4 border-t border-[#e4b6d0] justify-between">
          <button
            onClick={openInNewTab}
            className="px-4 py-2 bg-gray-100 text-gray-700 text-[13px] font-medium rounded-[8px] hover:bg-gray-200 transition-colors"
          >
            🔗 Mở tab mới
          </button>
          <div className="flex gap-3">
            <a
              href={pdfUrl}
              download
              className="px-6 py-2 bg-[#8f1025] text-white text-[13px] font-medium rounded-[8px] hover:bg-[#7a0e20] transition-colors"
            >
              ⬇️ Tải xuống
            </a>
            <button
              onClick={onClose}
              className="px-6 py-2 bg-gray-200 text-gray-800 text-[13px] font-medium rounded-[8px] hover:bg-gray-300 transition-colors"
            >
              Đóng
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
