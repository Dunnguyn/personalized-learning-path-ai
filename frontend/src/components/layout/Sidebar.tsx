import { Link, useLocation } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import iconDashboard from '../../assets/activity.png';
import iconLearningPath from '../../assets/learning-journey.png';
import iconResources from '../../assets/resources.png';
import iconAiTutor from '../../assets/ai-tutor.png';
import iconSettings from '../../assets/setting.png';

interface NavItem {
  name: string;
  path: string;
  icon: string;
}

const navItems: NavItem[] = [
  { name: 'Dashboard', path: '/dashboard', icon: iconDashboard },
  { name: 'Learning Path', path: '/learning-path', icon: iconLearningPath },
  { name: 'Question Bank', path: '/question-banks', icon: iconResources },
  { name: 'Resources', path: '/resources', icon: iconResources },
  { name: 'AI Tutor', path: '/ai-tutor', icon: iconAiTutor },
];

export default function Sidebar() {
  const location = useLocation();

  return (
    <div className="fixed left-0 top-0 h-screen w-[250px] bg-accent overflow-y-auto shadow-md">
      {/* Logo */}
      <div className="flex items-center px-[21px] py-[10px] gap-3">
        <img
          alt="Bunny Logo"
          className="w-[50px] h-[50px] rounded-full object-cover shadow-sm"
          src={bunnyLogo}
        />
        <p className="font-semibold text-[25px] text-secondary">Bunny</p>
      </div>

      {/* Divider */}
      <div className="w-full h-[0.5px] bg-secondary/20 mt-[10px]" />

      {/* Navigation */}
      <nav className="mt-[32px] space-y-[20px] px-[21px]">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <div key={item.path} className="relative">
              <Link
                to={item.path}
                className={`flex items-center gap-3 text-[15px] transition-all duration-200 ${
                  isActive
                    ? 'text-secondary font-normal'
                    : 'text-secondary/50 font-normal hover:text-secondary/70 hover:translate-x-1'
                }`}
              >
                <img
                  alt={item.name}
                  className={`w-[20px] h-[20px] object-cover transition-opacity duration-200 ${
                    isActive ? '' : 'opacity-50'
                  }`}
                  src={item.icon}
                />
                <span>{item.name}</span>
              </Link>
              {isActive && (
                <div className="mt-2 w-[110px] h-[2px] bg-secondary rounded-full" />
              )}
            </div>
          );
        })}
      </nav>

      {/* Settings - at bottom */}
      <div className="absolute bottom-[30px] left-[21px]">
        <Link
          to="/settings"
          className={`flex items-center gap-3 text-[15px] transition-all duration-200 ${
            location.pathname === '/settings'
              ? 'text-secondary font-normal'
              : 'text-secondary/50 hover:text-secondary/70 hover:translate-x-1'
          }`}
        >
          <img
            alt="Setting"
            className={`w-[20px] h-[20px] object-cover transition-opacity duration-200 ${
              location.pathname === '/settings' ? '' : 'opacity-50'
            }`}
            src={iconSettings}
          />
          <span>Setting</span>
        </Link>
      </div>
    </div>
  );
}
