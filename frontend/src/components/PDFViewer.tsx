import { useEffect, useMemo, useState } from 'react';

interface PDFViewerProps {
  isOpen: boolean;
  title: string;
  resourceId: string;
  initialPage?: number;
  isPinned?: boolean;
  onClose: () => void;
  onPageChange?: (page: number) => void;
  onTogglePin?: (page: number) => void;
}

export default function PDFViewer({
  isOpen,
  title,
  resourceId,
  initialPage,
  isPinned = false,
  onClose,
  onPageChange,
  onTogglePin,
}: PDFViewerProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowLoadingHint, setShowSlowLoadingHint] = useState(false);
  const [currentPage, setCurrentPage] = useState(initialPage && initialPage > 0 ? initialPage : 1);

  const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  const apiBasePath = import.meta.env.VITE_API_BASE_PATH || '/api';
  const normalizedBaseUrl = apiBaseUrl.replace(/\/$/, '');
  const normalizedBasePath = apiBasePath.startsWith('/') ? apiBasePath : `/${apiBasePath}`;
  const pdfUrl = `${normalizedBaseUrl}${normalizedBasePath}/resources/pdf/${resourceId}`;
  const viewerUrl = useMemo(() => `${pdfUrl}#page=${Math.max(currentPage, 1)}`, [currentPage, pdfUrl]);
  const iframeKey = useMemo(() => `${resourceId}-${currentPage}`, [currentPage, resourceId]);

  useEffect(() => {
    if (!loading) {
      return;
    }

    const hintTimer = setTimeout(() => {
      setShowSlowLoadingHint(true);
    }, 3000);

    const timeoutTimer = setTimeout(() => {
      setLoading(false);
      setError('\u0054\u1ea3\u0069\u0020\u0050\u0044\u0046\u0020\u0071\u0075\u00e1\u0020\u006c\u00e2\u0075\u002e\u0020\u0056\u0075\u0069\u0020\u006c\u00f2\u006e\u0067\u0020\u0074\u0068\u1eed\u0020\u006d\u1edf\u0020\u0074\u0072\u006f\u006e\u0067\u0020\u0074\u0061\u0062\u0020\u006d\u1edb\u0069\u0020\u0068\u006f\u1eb7\u0063\u0020\u0074\u1ea3\u0069\u0020\u0078\u0075\u1ed1\u006e\u0067\u002e');
    }, 15000);

    return () => {
      clearTimeout(hintTimer);
      clearTimeout(timeoutTimer);
    };
  }, [loading]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setLoading(true);
    setError(null);
    setShowSlowLoadingHint(false);
    setCurrentPage(initialPage && initialPage > 0 ? initialPage : 1);
  }, [initialPage, isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    onPageChange?.(currentPage);
  }, [currentPage, isOpen, onPageChange]);

  if (!isOpen) {
    return null;
  }

  const openInNewTab = () => {
    window.open(viewerUrl, '_blank', 'noopener,noreferrer');
  };

  const goToPreviousPage = () => {
    setCurrentPage((page) => Math.max(page - 1, 1));
    setLoading(true);
    setShowSlowLoadingHint(false);
  };

  const goToNextPage = () => {
    setCurrentPage((page) => page + 1);
    setLoading(true);
    setShowSlowLoadingHint(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4">
      <div className="flex h-[90vh] w-full max-w-5xl flex-col rounded-[10px] bg-white shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-[#e4b6d0] p-4">
          <div className="min-w-0">
            <h2 className="truncate text-[18px] font-semibold text-[#5b1724]">{title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] font-medium text-[#8c3451]/70">
              <span>{'\u0054\u0072\u0061\u006e\u0067\u0020\u0068\u0069\u1ec7\u006e\u0020\u0074\u1ea1\u0069'} {currentPage}</span>
              {initialPage ? <span className="rounded-full bg-[#faf2f5] px-2 py-1">{'\u0047\u1ee3\u0069\u0020\u00fd\u0020\u0074\u1eeb\u0020\u0074\u0072\u0061\u006e\u0067'} {initialPage}</span> : null}
              {isPinned ? <span className="rounded-full bg-[#f7dfe8] px-2 py-1 text-[#8c3451]">{'\u0110\u00e3\u0020\u0067\u0068\u0069\u006d'}</span> : null}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onTogglePin?.(currentPage)}
              className={`rounded-full px-4 py-2 text-[12px] font-semibold transition-colors ${
                isPinned ? 'bg-[#f7dfe8] text-[#8c3451]' : 'bg-[#f6f1f4] text-[#6f5260] hover:bg-[#f1e5ea]'
              }`}
            >
              {isPinned ? '\u0042\u1ecf\u0020\u0067\u0068\u0069\u006d' : '\u0047\u0068\u0069\u006d\u0020\u0074\u00e0\u0069\u0020\u006c\u0069\u1ec7\u0075\u0020\u006e\u00e0\u0079'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-[24px] text-[#8f1025] transition-colors hover:bg-gray-100"
            >
              x
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#f1d6e0] bg-[#fff8fb] px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={goToPreviousPage}
              disabled={currentPage <= 1}
              className="rounded-full border border-[#ead1dc] bg-white px-4 py-2 text-[13px] font-medium text-[#6f5260] transition-colors hover:bg-[#faf2f5] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {'\u0054\u0072\u0061\u006e\u0067\u0020\u0074\u0072\u01b0\u1edb\u0063'}
            </button>
            <button
              type="button"
              onClick={goToNextPage}
              className="rounded-full border border-[#ead1dc] bg-white px-4 py-2 text-[13px] font-medium text-[#6f5260] transition-colors hover:bg-[#faf2f5]"
            >
              {'\u0054\u0072\u0061\u006e\u0067\u0020\u0073\u0061\u0075'}
            </button>
          </div>
          <p className="text-[12px] text-[#8c3451]/70">
            {'\u0044\u00f9\u006e\u0067\u0020\u0111\u0069\u1ec1\u0075\u0020\u0068\u01b0\u1edb\u006e\u0067\u0020\u006e\u00e0\u0079\u0020\u0111\u1ec3\u0020\u006e\u0068\u1ea3\u0079\u0020\u006e\u0068\u0061\u006e\u0068\u0020\u0067\u0069\u1eefa\u0020\u0063\u00e1\u0063\u0020\u0074\u0072\u0061\u006e\u0067\u0020\u0067\u1ee3\u0069\u0020\u00fd\u0020\u006d\u00e0\u0020\u006b\u0068\u00f4\u006e\u0067\u0020\u0072\u1eddi\u0020\u006c\u0065\u0073\u0073\u006f\u006e\u002e'}
          </p>
        </div>

        <div className="relative flex-1 overflow-auto bg-gray-50">
          {loading ? (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white bg-opacity-75">
              <div className="text-center">
                <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8f1025]" />
                <p className="mb-2 text-[#8f1025]">{'\u0110\u0061\u006e\u0067\u0020\u0074\u1ea3\u0069\u0020\u0050\u0044\u0046\u002e\u002e\u002e'}</p>
                {showSlowLoadingHint ? (
                  <div className="mt-4 space-y-2">
                    <p className="text-[13px] text-gray-600">{'\u0054\u1ea3\u0069\u0020\u006c\u00e2\u0075\u0020\u0068\u01a1\u006e\u0020\u0062\u00ec\u006e\u0068\u0020\u0074\u0068\u01b0\u1edd\u006e\u0067\u003f'}</p>
                    <button
                      type="button"
                      onClick={openInNewTab}
                      className="rounded-[8px] bg-[#8f1025] px-4 py-2 text-[12px] text-white hover:bg-[#7a0e20]"
                    >
                      {'\u004d\u1edf\u0020\u0074\u0072\u006f\u006e\u0067\u0020\u0074\u0061\u0062\u0020\u006d\u1edb\u0069'}
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {error ? (
            <div className="absolute inset-0 flex items-center justify-center bg-white">
              <div className="max-w-md px-6 text-center">
                <p className="mb-4 text-[16px] text-red-600">{'\u004c\u1ed7\u0069\u0020\u0074\u1ea3\u0069\u0020\u0050\u0044\u0046'}</p>
                <p className="mb-6 text-[14px] text-gray-600">{error}</p>
                <div className="flex justify-center gap-3">
                  <button
                    type="button"
                    onClick={openInNewTab}
                    className="rounded-[8px] bg-[#8f1025] px-4 py-2 text-[13px] text-white hover:bg-[#7a0e20]"
                  >
                    {'\u004d\u1edf\u0020\u0074\u0072\u006f\u006e\u0067\u0020\u0074\u0061\u0062\u0020\u006d\u1edb\u0069'}
                  </button>
                  <a
                    href={pdfUrl}
                    download
                    className="rounded-[8px] bg-gray-600 px-4 py-2 text-[13px] text-white hover:bg-gray-700"
                  >
                    {'\u0054\u1ea3\u0069\u0020\u0078\u0075\u1ed1\u006e\u0067'}
                  </a>
                </div>
              </div>
            </div>
          ) : null}

          <iframe
            key={iframeKey}
            src={viewerUrl}
            className="h-full w-full border-none"
            title={title}
            onLoad={() => {
              setLoading(false);
              setError(null);
            }}
            onError={() => {
              setLoading(false);
              setError('\u004b\u0068\u00f4\u006e\u0067\u0020\u0074\u0068\u1ec3\u0020\u0074\u1ea3\u0069\u0020\u0066\u0069\u006c\u0065\u0020\u0050\u0044\u0046\u002e\u0020\u0056\u0075\u0069\u0020\u006c\u00f2\u006e\u0067\u0020\u0074\u0068\u1eed\u0020\u0074\u1ea3\u0069\u0020\u0078\u0075\u1ed1\u006e\u0067\u0020\u0066\u0069\u006c\u0065\u002e');
            }}
          />
        </div>

        <div className="flex justify-between gap-3 border-t border-[#e4b6d0] p-4">
          <button
            type="button"
            onClick={openInNewTab}
            className="rounded-[8px] bg-gray-100 px-4 py-2 text-[13px] font-medium text-gray-700 transition-colors hover:bg-gray-200"
          >
            {'\u004d\u1edf\u0020\u0074\u0061\u0062\u0020\u006d\u1edb\u0069'}
          </button>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => onTogglePin?.(currentPage)}
              className={`rounded-[8px] px-6 py-2 text-[13px] font-medium transition-colors ${
                isPinned ? 'bg-[#f7dfe8] text-[#8c3451] hover:bg-[#f2d2df]' : 'bg-[#f6f1f4] text-[#6f5260] hover:bg-[#eee2e8]'
              }`}
            >
              {isPinned ? '\u0042\u1ecf\u0020\u0067\u0068\u0069\u006d' : '\u0047\u0068\u0069\u006d\u0020\u0111\u1ec3\u0020\u0111\u1ecdc\u0020\u0074\u0069\u1ebf\u0070'}
            </button>
            <a
              href={pdfUrl}
              download
              className="rounded-[8px] bg-[#8f1025] px-6 py-2 text-[13px] font-medium text-white transition-colors hover:bg-[#7a0e20]"
            >
              {'\u0054\u1ea3\u0069\u0020\u0078\u0075\u1ed1\u006e\u0067'}
            </a>
            <button
              type="button"
              onClick={onClose}
              className="rounded-[8px] bg-gray-200 px-6 py-2 text-[13px] font-medium text-gray-800 transition-colors hover:bg-gray-300"
            >
              {'\u0110\u00f3\u006e\u0067'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
