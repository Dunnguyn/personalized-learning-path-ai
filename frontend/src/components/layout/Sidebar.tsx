import { Link, useLocation } from 'react-router-dom';
import {
  activityIcon,
  aiTutorIcon,
  brandLogo,
  learningJourneyIcon,
  resourcesIcon,
  settingIcon,
} from '../../assets';
import { useAuth } from '../../contexts/AuthContext';

interface NavItem {
  name: string;
  path: string;
  iconSrc: string;
}

const learnerNavItems: NavItem[] = [
  { name: 'Tổng quan', path: '/dashboard', iconSrc: activityIcon },
  { name: 'Lộ trình', path: '/learning-path', iconSrc: learningJourneyIcon },
  { name: 'Tài nguyên', path: '/resources', iconSrc: resourcesIcon },
  { name: 'AI Tutor', path: '/ai-tutor', iconSrc: aiTutorIcon },
];

const adminNavItems: NavItem[] = [
  { name: 'Quản trị', path: '/dashboard', iconSrc: activityIcon },
  { name: 'Tài nguyên', path: '/resources', iconSrc: resourcesIcon },
];

export default function Sidebar() {
  const location = useLocation();
  const { user } = useAuth();

  const isAdmin = user?.role === 'admin';
  const navItems = isAdmin ? adminNavItems : learnerNavItems;
  const isSettingsActive = location.pathname === '/settings';

  return (
    <aside className="shrink-0 lg:w-[70px] xl:w-[78px]">
      <div className="sidebar-shell h-full w-full gap-4 overflow-hidden rounded-[28px] px-3 py-3 lg:px-1.5 lg:py-4 xl:px-2.5">
        <div className="flex w-full flex-col gap-4">
          <Link
            to="/dashboard"
            className="flex items-center gap-3 rounded-[24px] border border-white/70 bg-white/88 px-3 py-3 shadow-[0_12px_24px_rgba(125,76,99,0.10)] lg:mx-auto lg:min-h-[46px] lg:w-[46px] lg:justify-center lg:rounded-full lg:px-0 lg:py-0"
          >
            <span className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-[16px] border border-white/80 bg-white shadow-[0_10px_18px_rgba(169,72,114,0.10)] lg:h-8 lg:w-8 lg:rounded-full">
              <img src={brandLogo} alt="Learning Hub" className="h-full w-full object-cover" />
            </span>
            <span className="min-w-0 flex-1 lg:hidden">
              <span className="block truncate text-[13px] font-semibold text-[#241f20]">
                {isAdmin ? 'Khu quản trị' : 'Learning Hub'}
              </span>
            </span>
          </Link>

          <nav className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1 lg:gap-3">
            {navItems.map((item) => {
              const isActive =
                location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);

              return (
                <Link
                  key={item.path}
                  to={item.path}
                  aria-current={isActive ? 'page' : undefined}
                  className={`side-icon-btn h-auto w-full justify-start gap-3 px-4 py-3 text-left transition-all duration-200 lg:mx-auto lg:w-[46px] lg:justify-center lg:px-0 lg:py-2.5 ${
                    isActive
                      ? 'active'
                      : 'text-[#5a524d] lg:hover:bg-white/88 lg:hover:shadow-[0_10px_22px_rgba(125,76,99,0.08)]'
                  }`}
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] bg-[#fff4f8] transition-all duration-200 lg:h-8 lg:w-8 lg:rounded-full">
                    <img
                      src={item.iconSrc}
                      alt=""
                      className="h-5 w-5 object-contain transition-all duration-200 lg:h-[18px] lg:w-[18px]"
                    />
                  </span>
                  <span className="min-w-0 flex-1 lg:hidden">
                    <span className="block truncate text-[13px] font-semibold">{item.name}</span>
                  </span>
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="grid w-full grid-cols-1 gap-3 border-t border-white/60 pt-3">
          <Link
            to="/settings"
            aria-current={isSettingsActive ? 'page' : undefined}
            className={`side-icon-btn h-auto w-full justify-start gap-3 px-4 py-3 text-left transition-all duration-200 lg:mx-auto lg:w-[46px] lg:justify-center lg:px-0 lg:py-2.5 ${
              isSettingsActive
                ? 'active'
                : 'text-[#5a524d] lg:hover:bg-white/88 lg:hover:shadow-[0_10px_22px_rgba(125,76,99,0.08)]'
            }`}
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] bg-[#fff4f8] transition-all duration-200 lg:h-8 lg:w-8 lg:rounded-full">
              <img
                src={settingIcon}
                alt=""
                className="h-5 w-5 object-contain transition-all duration-200 lg:h-[18px] lg:w-[18px]"
              />
            </span>
            <span className="min-w-0 flex-1 lg:hidden">
              <span className="block truncate text-[13px] font-semibold">Cài đặt</span>
            </span>
          </Link>
        </div>
      </div>
    </aside>
  );
}
