import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

export default function Header() {
  const [searchQuery, setSearchQuery] = useState('');
  const { user } = useAuth();
  const navigate = useNavigate();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const query = searchQuery.trim();
    if (!query) return;
    navigate(`/resources?q=${encodeURIComponent(query)}`);
  };

  return (
    <header className="app-toolbar">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="window-dot bg-[#ff6d5f]" />
          <span className="window-dot bg-[#ffbe2f]" />
          <span className="window-dot bg-[#28c840]" />
        </div>
        <div className="hidden items-center gap-3 text-[#6f5b63] md:flex">
          <span className="text-[16px] font-medium">^</span>
          <span className="text-[18px]">&lt;</span>
        </div>
      </div>

      <form onSubmit={handleSearch} className="mx-6 flex-1">
        <div className="browser-pill mx-auto flex w-full max-w-[560px] items-center justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#8c3451] text-[12px] font-semibold text-white">
              /
            </span>
            <input
              type="text"
              placeholder="your.education"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full min-w-0 bg-transparent text-[13px] text-[#17151a] outline-none placeholder:text-[#17151a]"
            />
            <span className="text-[13px] font-semibold text-[#876f79]">o</span>
          </div>
          <button
            type="submit"
            className="ml-4 flex h-8 w-8 items-center justify-center rounded-full bg-[#8c3451]/10 text-[12px] font-semibold text-[#8c3451] transition-colors hover:bg-[#8c3451]/15"
          >
            ...
          </button>
        </div>
      </form>

      <div className="flex items-center gap-3 text-[#17151a]">
        <button className="flex h-10 w-10 items-center justify-center rounded-full bg-white/78 text-[16px] text-[#8c3451] shadow-[0_8px_18px_rgba(137,78,99,0.08)] transition-transform hover:-translate-y-0.5">
          ↺
        </button>
        <button className="flex h-10 w-10 items-center justify-center rounded-full bg-white/78 text-[16px] text-[#8c3451] shadow-[0_8px_18px_rgba(137,78,99,0.08)] transition-transform hover:-translate-y-0.5">
          ↗
        </button>
        <button className="flex h-10 w-10 items-center justify-center rounded-full bg-white/78 text-[18px] text-[#8c3451] shadow-[0_8px_18px_rgba(137,78,99,0.08)] transition-transform hover:-translate-y-0.5">
          +
        </button>
        <div className="hidden rounded-full bg-white/78 px-5 py-2.5 text-[12px] font-medium text-[#6f5b63] shadow-[0_8px_18px_rgba(137,78,99,0.08)] lg:block">
          {user?.name || 'Khách'}
        </div>
      </div>
    </header>
  );
}
