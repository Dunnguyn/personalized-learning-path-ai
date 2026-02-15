import { Link, useLocation } from 'react-router-dom';

const imgElegantSubLogoDesignsForBeautyBrands1 = "https://www.figma.com/api/mcp/asset/7c1f6878-c01b-4eb7-98db-5a2b41422c7e";
const imgActivity1 = "https://www.figma.com/api/mcp/asset/e273ea49-3417-45df-830e-9801e4afa5c4";
const imgLearningJourney1 = "https://www.figma.com/api/mcp/asset/4042ae65-e400-4452-a714-42432d093524";
const imgResources1 = "https://www.figma.com/api/mcp/asset/effd77a4-9863-4ad9-9e1a-eaaea6b23d4c";
const imgAiTutor1 = "https://www.figma.com/api/mcp/asset/9a9808c5-edd2-4697-ad76-d67fb5a00c25";
const imgSetting1 = "https://www.figma.com/api/mcp/asset/5e6efe65-245b-4ab9-9f0a-f0a0dcc6ee0b";

interface NavItem {
  name: string;
  path: string;
  icon: string;
}

const navItems: NavItem[] = [
  { name: 'Dashboard', path: '/dashboard', icon: imgActivity1 },
  { name: 'Learning Path', path: '/learning-path', icon: imgLearningJourney1 },
  { name: 'Resources', path: '/resources', icon: imgResources1 },
  { name: 'AI Tutor', path: '/ai-tutor', icon: imgAiTutor1 },
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
          src={imgElegantSubLogoDesignsForBeautyBrands1}
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
                <div className="absolute -left-[21px] top-0 w-[78px] h-[2px] bg-secondary mt-6 rounded-full" />
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
            src={imgSetting1}
          />
          <span>Setting</span>
        </Link>
      </div>
    </div>
  );
}
