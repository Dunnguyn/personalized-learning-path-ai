import { Link, useLocation } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import iconDashboard from '../../assets/activity.png';
import iconLearningPath from '../../assets/learning-journey.png';
import iconResources from '../../assets/resources.png';
import iconAiTutor from '../../assets/ai-tutor.png';
import iconSettings from '../../assets/setting.png';
import iconUser from '../../assets/account.png';

interface NavItem {
  name: string;
  path: string;
  icon: string;
}

const navItems: NavItem[] = [
  { name: 'Tổng quan', path: '/dashboard', icon: iconDashboard },
  { name: 'Lộ trình học', path: '/learning-path', icon: iconLearningPath },
  { name: 'Tài nguyên', path: '/resources', icon: iconResources },
  { name: 'Trợ giảng AI', path: '/ai-tutor', icon: iconAiTutor },
];

export default function Sidebar() {
  const location = useLocation();

  return (
    <aside className="w-[112px] shrink-0">
      <div className="sidebar-shell h-full">
        <div className="flex w-full flex-col items-center gap-7">
          <Link
            to="/dashboard"
            className="flex h-[72px] w-[72px] items-center justify-center rounded-[24px] bg-white/92 shadow-[0_14px_28px_rgba(114,62,83,0.12)]"
          >
            <img alt="Bunny" className="h-11 w-11 rounded-full object-cover" src={bunnyLogo} />
          </Link>

          <div className="flex flex-col gap-5">
            {navItems.map((item) => {
              const isActive = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);

              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`side-icon-btn relative ${isActive ? 'active' : ''}`}
                  title={item.name}
                >
                  <img
                    alt={item.name}
                    className={`h-7 w-7 object-contain ${isActive ? 'brightness-[8]' : 'opacity-85'}`}
                    src={item.icon}
                  />
                  {item.path === '/learning-path' && (
                    <span className="absolute right-3 top-3 h-2.5 w-2.5 rounded-full bg-[#f39aa9]" />
                  )}
                </Link>
              );
            })}
          </div>
        </div>

        <div className="flex flex-col items-center gap-5">
          <Link
            to="/settings"
            title="Cài đặt"
            className={`side-icon-btn ${location.pathname === '/settings' ? 'active' : ''}`}
          >
            <img
              alt="Cài đặt"
              className={`h-7 w-7 object-contain ${location.pathname === '/settings' ? 'brightness-[8]' : 'opacity-85'}`}
              src={iconSettings}
            />
          </Link>

          <div className="h-[72px] w-[72px] overflow-hidden rounded-[24px] border border-white/70 shadow-[0_14px_28px_rgba(114,62,83,0.12)]">
            <img alt="Người dùng" className="h-full w-full object-cover" src={iconUser} />
          </div>
        </div>
      </div>
    </aside>
  );
}
