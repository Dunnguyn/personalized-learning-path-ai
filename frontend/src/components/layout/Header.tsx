import { useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

const getRouteLabel = (pathname: string) => {
  if (pathname.startsWith('/learning-path/')) {
    return 'learning-path/detail';
  }
  if (pathname === '/learning-path') {
    return 'learning-path';
  }
  if (pathname === '/resources') {
    return 'resources';
  }
  if (pathname === '/ai-tutor') {
    return 'ai-tutor';
  }
  if (pathname === '/settings') {
    return 'settings';
  }
  if (pathname === '/dashboard') {
    return 'dashboard';
  }
  if (pathname === '/signup') {
    return 'signup';
  }
  if (pathname === '/signup-step2') {
    return 'signup/setup';
  }
  if (pathname === '/debug-token') {
    return 'debug-token';
  }
  return 'home';
};

function BrowserIcon({ children }: { children: ReactNode }) {
  return (
    <span className="pointer-events-none inline-flex h-4 w-4 items-center justify-center">
      {children}
    </span>
  );
}

export default function Header() {
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [isLogoutModalOpen, setIsLogoutModalOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const currentRouteLabel = useMemo(() => getRouteLabel(location.pathname), [location.pathname]);
  const currentAddress = useMemo(() => {
    const querySuffix = location.search ? location.search.replace(/^\?/, '?') : '';
    return `https://your.education/${currentRouteLabel}${querySuffix}`;
  }, [currentRouteLabel, location.search]);

  const currentAddressParts = useMemo(() => {
    const querySuffix = location.search ? location.search.replace(/^\?/, '?') : '';
    return {
      domain: 'your.education',
      path: `/${currentRouteLabel}${querySuffix}`,
    };
  }, [currentRouteLabel, location.search]);

  const userInitial = useMemo(() => {
    const name = (user?.name || 'Tester').trim();
    return name.charAt(0).toUpperCase();
  }, [user?.name]);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) {
      return;
    }
    navigate(`/resources?q=${encodeURIComponent(query)}`);
  };

  const handleBack = () => {
    window.history.back();
  };

  const handleForward = () => {
    window.history.forward();
  };

  const handleRequestLogout = () => {
    setIsLogoutModalOpen(true);
  };

  const handleCancelLogout = () => {
    if (isLoggingOut) {
      return;
    }
    setIsLogoutModalOpen(false);
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
      <header className="app-toolbar gap-4">
        <div className="flex min-w-[132px] items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="window-dot bg-[#ff6d5f]" />
            <span className="window-dot bg-[#ffbe2f]" />
            <span className="window-dot bg-[#28c840]" />
          </div>
          <div className="hidden items-center gap-2 md:flex">
            <button
              type="button"
              onClick={handleBack}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-[#ebdbe2] bg-white/78 text-[#6f5b63] shadow-[0_8px_18px_rgba(137,78,99,0.06)] transition hover:-translate-y-0.5 hover:bg-white"
              aria-label="Go back"
            >
              <BrowserIcon>
                <svg
                  viewBox="0 0 16 16"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M9.75 3.5L5.25 8l4.5 4.5" />
                </svg>
              </BrowserIcon>
            </button>
            <button
              type="button"
              onClick={handleForward}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-[#ebdbe2] bg-white/78 text-[#6f5b63] shadow-[0_8px_18px_rgba(137,78,99,0.06)] transition hover:-translate-y-0.5 hover:bg-white"
              aria-label="Go forward"
            >
              <BrowserIcon>
                <svg
                  viewBox="0 0 16 16"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M6.25 3.5L10.75 8l-4.5 4.5" />
                </svg>
              </BrowserIcon>
            </button>
          </div>
        </div>

        <div className="flex flex-1 items-center justify-center">
          <div className="flex w-full max-w-[980px] items-center gap-3">
            <form
              onSubmit={handleSearch}
              className="flex flex-1 justify-center"
              title={currentAddress}
            >
              <div className="browser-pill flex h-[56px] w-full items-center gap-3 rounded-[28px] border border-[#ead9e1] bg-white/84 px-4 shadow-[0_14px_28px_rgba(137,78,99,0.08)]">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#f8e5ed] text-[#8c3451]">
                  <svg
                    viewBox="0 0 20 20"
                    className="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect x="5.5" y="8" width="9" height="6.5" rx="1.75" />
                    <path d="M7.5 8V6.9a2.5 2.5 0 0 1 5 0V8" />
                  </svg>
                </span>

                <div className="min-w-0 flex-1">
                  <div className="relative">
                    {!searchQuery && !isSearchFocused ? (
                      <div className="pointer-events-none absolute inset-0 flex items-center gap-2 overflow-hidden text-[14px]">
                        <span className="truncate font-semibold text-[#241f24]">
                          {currentAddressParts.domain}
                        </span>
                        <span className="truncate text-[#8a7880]">{currentAddressParts.path}</span>
                      </div>
                    ) : null}
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      onFocus={() => setIsSearchFocused(true)}
                      onBlur={() => setIsSearchFocused(false)}
                      placeholder={isSearchFocused ? 'Search lessons, resources, topics' : ''}
                      className={`w-full bg-transparent text-[14px] outline-none placeholder:text-[#8a7880] ${
                        !searchQuery && !isSearchFocused
                          ? 'text-transparent caret-[#8c3451]'
                          : 'text-[#17151a]'
                      }`}
                      aria-label="Search resources"
                    />
                  </div>
                </div>

                <div className="hidden items-center gap-2 md:flex">
                  <span className="rounded-full bg-[#faf1f5] px-2.5 py-1 text-[11px] font-medium text-[#8a7880]">
                    Secure
                  </span>
                  <button
                    type="submit"
                    className="flex h-9 w-9 items-center justify-center rounded-full bg-[#8c3451]/10 text-[#8c3451] transition-colors hover:bg-[#8c3451]/15"
                    aria-label="Search"
                  >
                    <BrowserIcon>
                      <svg
                        viewBox="0 0 16 16"
                        className="h-4 w-4"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                      >
                        <circle cx="7" cy="7" r="3.75" />
                        <path d="M10.25 10.25L13 13" />
                      </svg>
                    </BrowserIcon>
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>

        <div className="flex min-w-[188px] items-center justify-end gap-3 text-[#17151a]">
          <button
            type="button"
            onClick={handleRequestLogout}
            className="inline-flex h-10 items-center justify-center rounded-full border border-[#ebdbe2] bg-white/82 px-4 text-[12px] font-semibold text-[#8c3451] shadow-[0_8px_18px_rgba(137,78,99,0.08)] transition hover:-translate-y-0.5 hover:bg-white"
            aria-label="Đăng xuất"
          >
            Đăng xuất
          </button>
          <div className="hidden items-center gap-3 rounded-full border border-[#ebdbe2] bg-white/82 px-3 py-2 shadow-[0_8px_18px_rgba(137,78,99,0.08)] lg:flex">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#8c3451] text-[13px] font-semibold text-white">
              {userInitial}
            </span>
            <div className="min-w-0">
              <p className="max-w-[120px] truncate text-[13px] font-semibold text-[#2b2328]">
                {user?.name || 'Tester'}
              </p>
              <p className="text-[11px] text-[#8a7880]">Signed in</p>
            </div>
          </div>
        </div>
      </header>

      {isLogoutModalOpen && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-[#2f1d24]/35 px-4">
          <div className="w-full max-w-[420px] rounded-[24px] border border-[#f0d7e0] bg-white p-6 shadow-[0_24px_56px_rgba(68,29,46,0.25)]">
            <h3 className="text-[22px] font-semibold tracking-[-0.02em] text-[#20161b]">
              Đăng xuất?
            </h3>
            <p className="mt-2 text-[14px] leading-6 text-[#6d5d65]">
              Bạn sẽ cần đăng nhập lại để tiếp tục sử dụng hệ thống học tập.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={handleCancelLogout}
                disabled={isLoggingOut}
                className="rounded-full border border-[#ebdbe2] bg-white px-5 py-2 text-[13px] font-semibold text-[#6d5d65] transition hover:bg-[#fff7fb] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleConfirmLogout}
                disabled={isLoggingOut}
                className="rounded-full bg-[#8c3451] px-5 py-2 text-[13px] font-semibold text-white shadow-[0_10px_24px_rgba(140,52,81,0.25)] transition hover:bg-[#7a2d46] disabled:cursor-not-allowed disabled:opacity-60"
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
