/** CareLine: an open conversation enclosing a continuous care line. */
export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="CareLine logo"
      className="logo-mark"
    >
      <rect x="1" y="1" width="62" height="62" rx="20" fill="#196c59" />
      <path
        d="M43 20a17 17 0 1 0 1 24"
        fill="none"
        stroke="#f3faf5"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path
        d="M28 32h7l4-7 5 14 4-7h5"
        fill="none"
        stroke="#b6e6cf"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({
  size = 36,
  sub = "MEMBER SERVICES",
}: {
  size?: number;
  sub?: string;
}) {
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
