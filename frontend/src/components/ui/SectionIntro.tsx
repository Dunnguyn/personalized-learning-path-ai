import type { ReactNode } from 'react';

interface SectionIntroProps {
  kicker?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  actionsClassName?: string;
}

const joinClasses = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function SectionIntro({
  kicker,
  title,
  description,
  actions,
  className,
  titleClassName,
  descriptionClassName,
  actionsClassName,
}: SectionIntroProps) {
  return (
    <div className={joinClasses('flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between', className)}>
      <div className="min-w-0">
        {kicker ? <p className="page-kicker !mb-2">{kicker}</p> : null}
        <h2 className={joinClasses('text-[24px] font-semibold tracking-[-0.03em] text-[#141217] md:text-[30px]', titleClassName)}>
          {title}
        </h2>
        {description ? (
          <p className={joinClasses('mt-3 max-w-3xl text-[14px] leading-7 text-black/48', descriptionClassName)}>
            {description}
          </p>
        ) : null}
      </div>

      {actions ? <div className={joinClasses('flex flex-wrap gap-3', actionsClassName)}>{actions}</div> : null}
    </div>
  );
}
