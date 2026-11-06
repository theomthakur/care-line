/** CareLine mark: a heart carrying a voice waveform. One component, used everywhere. */
export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="CareLine logo" className="logo-mark">
      <defs>
        <linearGradient id="cl-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#14b8a6" />
          <stop offset="1" stopColor="#0b5f59" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill="url(#cl-bg)" />
      <path
        d="M32 51C14 39.5 10 27 16 20.2c5-5.6 13-3.6 16 2.6 3-6.2 11-8.2 16-2.6 6 6.8 2 19.3-16 30.8Z"
        fill="#ffffff"
        fillOpacity="0.96"
      />
      <path
        d="M19 32h6.5l3.2-7.5 5.6 15 3.4-7.5H45"
        fill="none"
        stroke="#0f766e"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ size = 36, sub = "MEMBER SERVICES" }: { size?: number; sub?: string }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="logo-text">
        <strong>CareLine</strong>
        {sub && <small>{sub}</small>}
      </span>
    </span>
  );
}
