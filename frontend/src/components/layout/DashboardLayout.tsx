import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';

interface DashboardLayoutProps {
  children: ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="min-h-screen p-3 lg:p-4">
      <div className="app-window min-h-[calc(100vh-24px)] lg:min-h-[calc(100vh-32px)]">
        <Header />
        <div className="flex min-h-[calc(100vh-97px)] gap-6 p-4 lg:p-5">
          <Sidebar />
          <main className="app-main-surface scroll-soft min-w-0 flex-1 overflow-y-auto px-5 py-6 lg:px-8 lg:py-8">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
