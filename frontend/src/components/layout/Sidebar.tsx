import { Link, useLocation } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import iconDashboard from '../../assets/activity.png';
import iconLearningPath from '../../assets/learning-journey.png';
import iconResources from '../../assets/resources.png';
import iconAiTutor from '../../assets/ai-tutor.png';
import iconSettings from '../../assets/setting.png';
import { useAuth } from '../../contexts/AuthContext';

interface NavItem {
  name: string;
  path: string;
  icon: string;
  badge?: string;
}

const learnerNavItems: NavItem[] = [
  { name: 'Tổng quan', path: '/dashboard', icon: iconDashboard },
  { name: 'Lộ trình học', path: '/learning-path', icon: iconLearningPath },
  { name: 'Tài nguyên', path: '/resources', icon: iconResources },
  { name: 'Trợ giảng AI', path: '/ai-tutor', icon: iconAiTutor },
];

const adminNavItems: NavItem[] = [
  { name: 'Quản trị', path: '/dashboard', icon: iconDashboard, badge: 'admin' },
  { name: 'Resource', path: '/resources', icon: iconResources, badge: 'ql' },
];

export default function Sidebar() {
  const location = useLocation();
  const { user } = useAuth();

  const isAdmin = user?.role === 'admin';
  const navItems = isAdmin ? adminNavItems : learnerNavItems;
  const sidebarWidthClass = isAdmin ? 'w-[88px] lg:w-[96px]' : 'w-[112px]';
  const shellClass = isAdmin
    ? 'sidebar-shell rounded-[28px] px-3 py-4'
    : 'sidebar-shell h-full';
  const logoClass = isAdmin
    ? 'relative flex h-[66px] w-[66px] items-center justify-center rounded-[22px] bg-white/92 shadow-[0_14px_28px_rgba(114,62,83,0.12)]'
    : 'relative flex h-[72px] w-[72px] items-center justify-center rounded-[24px] bg-white/92 shadow-[0_14px_28px_rgba(114,62,83,0.12)]';
  const navGapClass = isAdmin ? 'gap-4' : 'gap-5';
  const navButtonClass = isAdmin ? 'side-icon-btn h-14 w-14' : 'side-icon-btn';

  return (
    <aside className={`${sidebarWidthClass} shrink-0`}>
      <div className={shellClass}>
        <div className="flex w-full flex-col items-center gap-7">
          <Link to="/dashboard" className={logoClass}>
            <img alt="Bunny" className="h-11 w-11 rounded-full object-cover" src={bunnyLogo} />
            {isAdmin ? (
              <span className="absolute -bottom-1 rounded-full bg-[#8c3451] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-white">
                Admin
              </span>
            ) : null}
          </Link>

          <div className={`flex flex-col ${navGapClass}`}>
            {navItems.map((item) => {
              const isActive =
                location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);

              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`${navButtonClass} relative ${isActive ? 'active' : ''}`}
                  title={item.name}
                >
                  <img
                    alt={item.name}
                    className={`h-7 w-7 object-contain ${isActive ? 'brightness-[8]' : 'opacity-85'}`}
                    src={item.icon}
                  />
                  {item.badge ? (
                    <span className="absolute -bottom-1 rounded-full bg-white px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-[0.14em] text-[#8c3451] shadow-[0_6px_12px_rgba(114,62,83,0.12)]">
                      {item.badge}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </div>
        </div>

        <div className="flex flex-col items-center gap-4">
          <Link
            to="/settings"
            title={isAdmin ? 'Admin settings' : 'Cài đặt'}
            className={`${navButtonClass} ${location.pathname === '/settings' ? 'active' : ''}`}
          >
            <img
              alt={isAdmin ? 'Admin settings' : 'Cài đặt'}
              className={`h-7 w-7 object-contain ${location.pathname === '/settings' ? 'brightness-[8]' : 'opacity-85'}`}
              src={iconSettings}
            />
          </Link>
        </div>
      </div>
    </aside>
  );
}
