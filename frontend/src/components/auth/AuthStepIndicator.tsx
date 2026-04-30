import { brandLogo } from '../../assets';

type AuthStepIndicatorProps = {
  activeStep: 1 | 2;
};

export default function AuthStepIndicator({ activeStep }: AuthStepIndicatorProps) {
  return (
    <div className="flex flex-col items-center">
      <div className="flex h-18 w-18 items-center justify-center rounded-full bg-[#fff4f8] shadow-[0_14px_32px_rgba(162,94,121,0.12)]">
        <img src={brandLogo} alt="Learning brand" className="h-11 w-11 rounded-full object-cover" />
      </div>

      <div className="mt-5 flex items-center gap-1.5" aria-hidden="true">
        {[1, 2].map((step) => {
          const isActive = activeStep === step;

          return (
            <span
              key={step}
              className={[
                'block rounded-full transition-all duration-200',
                isActive
                  ? 'h-1.5 w-4 bg-[#6f2638]'
                  : 'h-1.5 w-3 bg-[#d98aaa]',
              ].join(' ')}
            />
          );
        })}
      </div>
    </div>
  );
}
