import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Header from './Header';

interface DashboardLayoutProps {
  children: ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="desktop-app-shell min-h-screen px-3 py-3 md:px-4 md:py-4">
      <a
        href="#app-main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[200] focus:rounded-full focus:bg-white focus:px-4 focus:py-2 focus:text-[13px] focus:font-semibold focus:text-[#8c3451] focus:shadow-[0_18px_36px_rgba(114,62,83,0.18)]"
      >
        Bỏ qua điều hướng và tới nội dung chính
      </a>
      <div className="app-window min-h-[calc(100vh-24px)]">
        <Header />
        <div className="desktop-shell-body flex min-h-[calc(100vh-104px)] flex-col gap-4 p-3 md:p-4 lg:flex-row lg:gap-6 lg:p-5">
          <Sidebar />
          <main
            id="app-main-content"
            className="app-main-surface scroll-soft min-w-0 flex-1 overflow-y-auto px-4 py-5 md:px-5 md:py-6 lg:px-8 lg:py-8"
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
