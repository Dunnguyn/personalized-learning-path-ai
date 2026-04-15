import type { ReactNode } from 'react';

interface DesktopPageGridProps {
  children: ReactNode;
  className?: string;
}

export default function DesktopPageGrid({
  children,
  className = '',
}: DesktopPageGridProps) {
  return (
    <div className={`desktop-page-grid ${className}`.trim()}>
      {children}
    </div>
  );
}
