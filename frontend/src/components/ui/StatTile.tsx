import type { ReactNode } from 'react';

interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  className?: string;
  labelClassName?: string;
  valueClassName?: string;
}

const joinClasses = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function StatTile({
  label,
  value,
  className,
  labelClassName,
  valueClassName,
}: StatTileProps) {
  return (
    <div className={joinClasses('dashboard-stat-tile', className)}>
      <p className={joinClasses('text-[12px] text-[#77706a]', labelClassName)}>{label}</p>
      <p
        className={joinClasses(
          'mt-2 text-[28px] font-semibold leading-none tracking-[-0.04em] text-[#121019]',
          valueClassName,
        )}
      >
        {value}
      </p>
    </div>
  );
}
