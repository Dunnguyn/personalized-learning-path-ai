import type { ReactNode } from 'react';

interface PageHeroMetric {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}

interface PageHeroProps {
  kicker: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  metrics?: PageHeroMetric[];
  children?: ReactNode;
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  actionsClassName?: string;
}

const joinClasses = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function PageHero({
  kicker,
  title,
  description,
  actions,
  metrics,
  children,
  className,
  titleClassName,
  descriptionClassName,
  actionsClassName,
}: PageHeroProps) {
  const headerLayoutClassName = actions
    ? 'grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start lg:gap-6'
    : 'flex flex-col gap-4';

  return (
    <section className={joinClasses('page-hero', className)}>
      <p className="page-kicker">{kicker}</p>
      <div className={headerLayoutClassName}>
        <div className="min-w-0">
          <h1 className={joinClasses('page-title mb-3', titleClassName)}>{title}</h1>
          {description ? (
            <p className={joinClasses('max-w-[780px] text-[15px] leading-7 text-[#5b544d]', descriptionClassName)}>
              {description}
            </p>
          ) : null}
        </div>

        {actions ? <div className={joinClasses('flex w-full flex-wrap gap-2 lg:w-auto lg:flex-none', actionsClassName)}>{actions}</div> : null}
      </div>

      {metrics?.length ? (
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {metrics.map((metric) => (
            <article key={metric.label} className="metric-card">
              <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">{metric.label}</p>
              <p className="mt-3 text-[24px] font-semibold tracking-[-0.04em] text-[#17141a]">{metric.value}</p>
              {metric.detail ? (
                <p className="mt-2 text-[13px] leading-5 text-[#645d57]">{metric.detail}</p>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}

      {children ? <div className="mt-6">{children}</div> : null}
    </section>
  );
}
