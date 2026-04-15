import type { ReactNode } from 'react';

interface ValueTileProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
  labelClassName?: string;
  valueClassName?: string;
  hintClassName?: string;
}

const joinClasses = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function ValueTile({
  label,
  value,
  hint,
  className,
  labelClassName,
  valueClassName,
  hintClassName,
}: ValueTileProps) {
  return (
    <div className={joinClasses('rounded-[18px] bg-white/90 px-4 py-4 shadow-[0_12px_24px_rgba(114,62,83,0.06)]', className)}>
      <p className={joinClasses('text-[13px] text-[#8b7f88]', labelClassName)}>{label}</p>
      <p className={joinClasses('mt-1 text-[26px] font-semibold tracking-[-0.03em] text-[#141217]', valueClassName)}>
        {value}
      </p>
      {hint ? <p className={joinClasses('mt-1 text-[12px] text-[#8c3451]', hintClassName)}>{hint}</p> : null}
    </div>
  );
}
