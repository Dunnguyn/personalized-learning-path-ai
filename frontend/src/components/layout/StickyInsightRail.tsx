import type { ReactNode } from 'react';

interface StickyInsightRailProps {
  children: ReactNode;
  className?: string;
}

export default function StickyInsightRail({
  children,
  className = '',
}: StickyInsightRailProps) {
  return (
    <aside className={`desktop-insight-rail ${className}`.trim()}>
      {children}
    </aside>
  );
}
