import type { ReactNode } from 'react';

type StatusTone = 'default' | 'info' | 'error';

interface StatusPanelProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  tone?: StatusTone;
  centered?: boolean;
  className?: string;
}

const joinClasses = (...values: Array<string | undefined | false>) => values.filter(Boolean).join(' ');

const toneClasses: Record<StatusTone, string> = {
  default: 'border-[#ead7df] bg-white text-[#141217]',
  info: 'border-[#ead7df] bg-[#fff7fb] text-[#8c3451]',
  error: 'border-red-200 bg-red-50 text-red-700',
};

export default function StatusPanel({
  title,
  description,
  actions,
  tone = 'default',
  centered = false,
  className,
}: StatusPanelProps) {
  return (
    <div
      className={joinClasses(
        'rounded-[20px] border px-5 py-5 shadow-[0_12px_24px_rgba(114,62,83,0.06)]',
        toneClasses[tone],
        centered && 'text-center',
        className,
      )}
    >
      {title ? <p className="text-[18px] font-semibold">{title}</p> : null}
      {description ? (
        <p className={joinClasses('text-[14px] leading-7', title ? 'mt-3' : undefined)}>{description}</p>
      ) : null}
      {actions ? (
        <div className={joinClasses('flex flex-wrap gap-3', centered ? 'mt-4 justify-center' : 'mt-3')}>
          {actions}
        </div>
      ) : null}
    </div>
  );
}
