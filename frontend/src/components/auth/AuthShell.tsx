import type { ReactNode } from 'react';

interface AuthShellProps {
  badge?: string;
  title: string;
  description: string;
  mediaAlt: string;
  mediaSrc: string;
  sideLabel: string;
  sideTitle: string;
  sideCopy: string;
  showSideContent?: boolean;
  children: ReactNode;
  footer?: ReactNode;
  introVisual?: ReactNode;
  centerContent?: boolean;
  formShellClassName?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  footerClassName?: string;
}

const joinClasses = (...values: Array<string | undefined | false>) => values.filter(Boolean).join(' ');

export default function AuthShell({
  badge,
  title,
  description,
  mediaAlt,
  mediaSrc,
  sideLabel,
  sideTitle,
  sideCopy,
  showSideContent = true,
  children,
  footer,
  introVisual,
  centerContent = false,
  formShellClassName,
  titleClassName,
  descriptionClassName,
  footerClassName,
}: AuthShellProps) {
  return (
    <div className="auth-shell">
      <div className="auth-card lg:grid-cols-[minmax(0,1.02fr)_minmax(360px,0.98fr)]">
        <section className="auth-panel">
          <div
            className={joinClasses(
              'w-full',
              centerContent ? 'mx-auto flex max-w-[420px] flex-1 flex-col items-center justify-center text-center' : undefined,
            )}
          >
            {introVisual ? <div className="mb-5">{introVisual}</div> : null}
            {badge ? <span className="auth-badge">{badge}</span> : null}
            <h1 className={joinClasses('auth-title mt-6 text-balance', titleClassName)}>{title}</h1>
            <p className={joinClasses('auth-copy mt-4', descriptionClassName)}>{description}</p>
            <div className={joinClasses('auth-form-shell', formShellClassName)}>{children}</div>
            {footer ? (
              <div className={joinClasses('mt-8 text-[13px] text-[#6d655f]', centerContent ? 'text-center' : undefined, footerClassName)}>
                {footer}
              </div>
            ) : null}
          </div>
        </section>

        <aside className="auth-aside">
          <img alt={mediaAlt} className="auth-hero-image" src={mediaSrc} />
          <div className="auth-aside-overlay" />
          {showSideContent ? (
            <div className="absolute inset-x-6 bottom-6 space-y-4">
              <div className="auth-metric max-w-[360px]">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-white/70">
                  {sideLabel}
                </p>
                <p className="mt-3 text-[32px] font-semibold leading-[1.04] tracking-[-0.05em] text-white">
                  {sideTitle}
                </p>
                <p className="mt-3 text-[14px] leading-6 text-white/88">{sideCopy}</p>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="auth-metric">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-white/70">Adaptive</p>
                  <p className="mt-2 text-[18px] font-semibold text-white">Learning paths</p>
                </div>
                <div className="auth-metric">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-white/70">Resource</p>
                  <p className="mt-2 text-[18px] font-semibold text-white">PDF, web, video</p>
                </div>
                <div className="auth-metric">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-white/70">AI</p>
                  <p className="mt-2 text-[18px] font-semibold text-white">Tutor in context</p>
                </div>
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
