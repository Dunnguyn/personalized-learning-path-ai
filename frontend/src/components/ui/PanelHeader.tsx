import type { ReactNode } from 'react';

interface PanelHeaderProps {
  kicker: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
  className?: string;
  contentClassName?: string;
  kickerClassName?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  asideClassName?: string;
}

const joinClasses = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function PanelHeader({
  kicker,
  title,
  description,
  aside,
  children,
  className,
  contentClassName,
  kickerClassName,
  titleClassName,
  descriptionClassName,
  asideClassName,
}: PanelHeaderProps) {
  return (
    <div className={joinClasses('flex flex-wrap items-start justify-between gap-3', className)}>
      <div className={joinClasses('min-w-0 flex-1', contentClassName)}>
        <p className={joinClasses('spotlight-kicker', kickerClassName)}>{kicker}</p>
        {title ? (
          <h3
            className={joinClasses(
              'mt-3 text-[28px] font-medium leading-[1.04] tracking-[-0.04em] text-[#17141b]',
              titleClassName,
            )}
          >
            {title}
          </h3>
        ) : null}
        {description ? (
          <p className={joinClasses('mt-2 text-[14px] leading-6 text-[#5f5954]', descriptionClassName)}>
            {description}
          </p>
        ) : null}
        {children ? <div className="mt-4 flex flex-wrap gap-2">{children}</div> : null}
      </div>

      {aside ? <div className={joinClasses('flex flex-wrap items-center gap-2', asideClassName)}>{aside}</div> : null}
    </div>
  );
}
