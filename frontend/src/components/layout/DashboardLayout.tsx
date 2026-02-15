import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';

interface DashboardLayoutProps {
  children: ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="bg-light min-h-screen">
      <Sidebar />
      <Header />
      <main className="ml-[250px] mt-[70.5px] p-8">
        {children}
      </main>
    </div>
  );
}
