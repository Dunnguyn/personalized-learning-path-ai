import { useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { dashboardService } from '../../services/dashboardService';

const imgAccount1 = "https://www.figma.com/api/mcp/asset/9da4165c-733e-47bf-a04b-df8d29c8ae03";
const imgImage4 = "https://www.figma.com/api/mcp/asset/fa55dc5b-3339-4c7f-964f-27171f19fd11";

export default function Header() {
  const [searchQuery, setSearchQuery] = useState('');
  const { user } = useAuth();
  
  const userName = user?.name || "Guest User";

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    
    try {
      const results = await dashboardService.searchResources(searchQuery);
      console.log('Search results:', results);
      // TODO: Navigate to search results page or show modal
    } catch (error) {
      console.error('Search error:', error);
    }
  };

  return (
    <div className="fixed left-[250px] top-0 right-0 h-[80.5px] bg-accent border-b-[0.5px] border-[rgba(203,107,134,0.5)] flex items-center px-8 gap-6 z-10">
      {/* Search Bar */}
      <form onSubmit={handleSearch} className="flex-1 max-w-[380px] ml-[180px]">
        <div className="relative flex items-center">
          <input
            type="text"
            placeholder="Tìm kiếm học liệu"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full h-[35px] pl-5 pr-12 rounded-[20px] bg-[rgba(222,143,172,0.5)] text-[#8f1025] text-[15px] placeholder-[#8f1025]/70 focus:outline-none focus:ring-2 focus:ring-[#ce6a86] transition-all"
          />
          <button
            type="submit"
            className="absolute right-0 w-[35px] h-[35px] rounded-[20px] bg-[rgba(222,143,172,0.5)] flex items-center justify-center hover:bg-[rgba(222,143,172,0.7)] transition-all"
          >
            <img
              alt="Search"
              className="w-[18px] h-[18px] object-cover"
              src={imgImage4}
            />
          </button>
        </div>
      </form>

      {/* User Info */}
      <div className="flex items-center gap-4 ml-auto">
        <div className="flex flex-col items-end">
          <p className="text-[10px] text-secondary italic leading-tight">Xin chào,</p>
          <p className="text-[13px] text-secondary font-medium leading-tight mt-0.5">{userName}</p>
        </div>
        <img
          alt="User Avatar"
          className="w-[50px] h-[50px] rounded-full object-cover border-2 border-transparent hover:border-[#ce6a86] transition-all cursor-pointer"
          src={imgAccount1}
        />
      </div>
    </div>
  );
}
