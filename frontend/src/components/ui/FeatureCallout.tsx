import type { ReactNode } from 'react';

interface FeatureCalloutProps {
  kicker: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  description?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  className?: string;
  kickerClassName?: string;
  titleClassName?: string;
  metaClassName?: string;
  descriptionClassName?: string;
}

const joinClasses = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function FeatureCallout({
  kicker,
  title,
  meta,
  description,
  badges,
  actions,
  className,
  kickerClassName,
  titleClassName,
  metaClassName,
  descriptionClassName,
}: FeatureCalloutProps) {
  return (
    <div
      className={joinClasses(
        'mt-6 rounded-[24px] border border-[#efd7e0] bg-[linear-gradient(135deg,#fffafd_0%,#fdf2f6_100%)] p-5 shadow-[0_16px_36px_rgba(114,62,83,0.08)]',
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {badges ? <div className="flex flex-wrap items-center gap-2">{badges}</div> : null}
          <p
            className={joinClasses(
              badges ? 'mt-3' : '',
              'text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/60',
              kickerClassName,
            )}
          >
            {kicker}
          </p>
          <h3
            className={joinClasses(
              'mt-2 text-[20px] font-semibold tracking-[-0.03em] text-[#141217]',
              titleClassName,
            )}
          >
            {title}
          </h3>
          {meta ? (
            <p className={joinClasses('mt-2 text-[14px] leading-6 text-[#6a625d]', metaClassName)}>
              {meta}
            </p>
          ) : null}
          {description ? (
            <p
              className={joinClasses(
                'mt-3 max-w-3xl text-[13px] leading-6 text-[#6a625d]',
                descriptionClassName,
              )}
            >
              {description}
            </p>
          ) : null}
        </div>

        {actions ? <div className="flex flex-wrap gap-3">{actions}</div> : null}
      </div>
    </div>
  );
}
