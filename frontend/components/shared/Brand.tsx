import clsx from 'clsx';

type BrandProps = {
  /** 'short' renders "EngageOS"; 'full' renders the full product name. */
  variant?: 'short' | 'full';
  /** Logo dimension in px (square). Defaults to 32. */
  size?: number;
  /** Extra classes for the outer wrapper (e.g. layout, spacing, text size). */
  className?: string;
};

export function Brand({ variant = 'short', size = 32, className }: BrandProps) {
  return (
    <div className={clsx('flex min-w-0 items-center gap-2', className)}>
      {/* Plain <img> (not next/image): the logo is a small static asset and the app
          builds in `output: 'standalone'` mode, where the next/image optimizer needs
          `sharp` at runtime — avoiding it keeps the logo robust on Railway. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/engageos-logo.png"
        alt="EngageOS logo"
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className="shrink-0 object-contain"
      />
      <span className="truncate font-semibold tracking-tight">
        {variant === 'full' ? 'EngageOS WhatsApp CRM' : 'EngageOS'}
      </span>
    </div>
  );
}
