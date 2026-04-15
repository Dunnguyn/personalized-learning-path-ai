import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { searchIcon } from '../../assets';
import { useAuth } from '../../contexts/AuthContext';

const getRouteMeta = (pathname: string) => {
  if (pathname.startsWith('/learning-path/')) {
    return {
      hint: 'Tìm lesson, quiz hoặc chủ đề trong lộ trình này...',
    };
  }
  if (pathname === '/learning-path') {
    return {
      hint: 'Tìm lộ trình, bài học hoặc mục tiêu học tập...',
    };
  }
  if (pathname === '/resources') {
    return {
      hint: 'Tìm video, PDF hoặc tài liệu phù hợp...',
    };
  }
  if (pathname === '/ai-tutor') {
    return {
      hint: 'Hỏi AI Tutor về bài học hiện tại...',
    };
  }
  if (pathname === '/settings') {
    return {
      hint: 'Tìm tùy chọn cá nhân hóa...',
    };
  }
  if (pathname === '/dashboard') {
    return {
      hint: 'Tìm bài học, tài liệu hoặc chủ đề cần tiếp tục...',
    };
  }
  return {
    hint: 'Tìm trong không gian học tập...',
  };
};

export default function Header() {
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [isLogoutModalOpen, setIsLogoutModalOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const routeMeta = useMemo(() => getRouteMeta(location.pathname), [location.pathname]);
  const displayName = user?.name?.trim() || 'Người học';
  const avatarInitial = displayName.charAt(0).toUpperCase();
  const routePath = location.pathname || '/dashboard';

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTypingField =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable;

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
        return;
      }

      if (event.key === '/' && !isTypingField) {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    };

    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, []);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) {
      return;
    }
    navigate(`/resources?q=${encodeURIComponent(query)}`);
  };

  const handleConfirmLogout = async () => {
    try {
      setIsLoggingOut(true);
      await logout();
      navigate('/login', { replace: true });
    } finally {
      setIsLoggingOut(false);
      setIsLogoutModalOpen(false);
    }
  };

  return (
    <>
      <header className="app-toolbar px-4 py-4 md:px-5 lg:px-6">
        <div className="flex w-full flex-col gap-3 xl:flex-row xl:items-center xl:gap-6">
          <div className="hidden shrink-0 items-center gap-3 xl:flex">
            <span className="window-dot bg-[#fb7e6a]" />
            <span className="window-dot bg-[#f7c64f]" />
            <span className="window-dot bg-[#57c95b]" />
          </div>

          <form onSubmit={handleSearch} className="min-w-0 flex-1">
            <div
              className={`browser-pill mx-auto flex h-[46px] w-full max-w-[700px] items-center gap-2.5 rounded-full border px-3 pr-2 transition ${
                isSearchFocused
                  ? 'border-[#d694af] ring-4 ring-[#a94872]/10'
                  : 'border-[#efd9e3]'
              }`}
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[#efd9e3] bg-[#fff7fa] text-[#b45b81]">
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className="h-3.5 w-3.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M8.5 10V7.75a3.5 3.5 0 1 1 7 0V10" />
                  <rect x="6.5" y="10" width="11" height="9" rx="2.5" />
                  <path d="M12 13.5v2.5" />
                </svg>
              </span>

              <div className="relative min-w-0 flex-1">
                <input
                  ref={searchInputRef}
                  id="global-search"
                  name="globalSearch"
                  type="text"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  onFocus={() => setIsSearchFocused(true)}
                  onBlur={() => setIsSearchFocused(false)}
                  placeholder={isSearchFocused ? routeMeta.hint : ''}
                  className={`w-full bg-transparent text-[13px] font-medium outline-none placeholder:text-[#a19098] ${
                    isSearchFocused || searchQuery ? 'text-[#2b2328]' : 'text-transparent'
                  }`}
                  aria-label="Tìm tài nguyên"
                />

                {!isSearchFocused && !searchQuery ? (
                  <div className="pointer-events-none absolute inset-0 flex items-center gap-2 overflow-hidden text-[13px]">
                    <span className="truncate font-semibold text-[#2b2328]">your.education</span>
                    <span className="shrink-0 text-[#c2aeb7]">{routePath}</span>
                  </div>
                ) : null}
              </div>

              <button
                type="submit"
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#efd9e3] bg-[rgba(169,72,114,0.08)] transition hover:-translate-y-0.5 hover:bg-[rgba(169,72,114,0.14)]"
                aria-label="Tìm kiếm"
              >
                <img src={searchIcon} alt="" className="h-4 w-4 object-contain" />
              </button>
            </div>
          </form>

          <div className="flex shrink-0 items-center justify-end gap-2 self-end xl:self-auto">
            <button
              type="button"
              onClick={() => setIsLogoutModalOpen(true)}
              className="inline-flex h-10 items-center justify-center rounded-full border border-[#efd9e3] bg-white/88 px-5 text-[12px] font-semibold text-[#a94872] shadow-[0_8px_18px_rgba(125,76,99,0.08)] transition hover:-translate-y-0.5 hover:bg-white"
              aria-label="Đăng xuất"
            >
              Đăng xuất
            </button>

            <div className="flex min-w-[148px] items-center gap-3 rounded-full border border-[#efd9e3] bg-white/88 px-2 py-1.5 shadow-[0_10px_20px_rgba(125,76,99,0.08)]">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#9c365d] text-[16px] font-semibold text-white">
                {avatarInitial}
              </span>
              <div className="min-w-0 pr-1">
                <p className="text-[11px] font-medium text-[#9a8a92]">Xin chào!</p>
                <p className="truncate text-[13px] font-semibold text-[#2b2328]">{displayName}</p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {isLogoutModalOpen && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-[#2f1d24]/35 px-4 backdrop-blur-sm">
          <div className="w-full max-w-[440px] rounded-[28px] border border-[#f0d7e0] bg-white p-6 shadow-[0_24px_56px_rgba(68,29,46,0.25)]">
            <p className="page-kicker mb-2">Kết thúc phiên</p>
            <h3 className="text-[28px] font-semibold tracking-[-0.03em] text-[#20161b]">
              Đăng xuất ngay?
            </h3>
            <p className="mt-3 text-[14px] leading-7 text-[#6d5d65]">
              Phiên làm việc hiện tại sẽ được đóng và bạn cần đăng nhập lại để tiếp tục sử dụng hệ
              thống.
            </p>
            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setIsLogoutModalOpen(false)}
                disabled={isLoggingOut}
                className="theme-button-secondary disabled:cursor-not-allowed disabled:opacity-60"
              >
                Ở lại
              </button>
              <button
                type="button"
                onClick={handleConfirmLogout}
                disabled={isLoggingOut}
                className="theme-button disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isLoggingOut ? 'Đang đăng xuất...' : 'Đăng xuất'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
