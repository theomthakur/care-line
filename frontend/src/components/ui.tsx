import type { ReactNode } from "react";
import { AlertCircle, ChevronDown } from "lucide-react";

export type ChipTone = "slate" | "green" | "amber" | "red" | "blue" | "teal" | "outline";

export function Chip({ tone = "slate", lg, children, title }: { tone?: ChipTone; lg?: boolean; children: ReactNode; title?: string }) {
  return (
    <span className={`chip ${tone === "slate" ? "" : tone} ${lg ? "lg" : ""}`} title={title}>
      {children}
    </span>
  );
}

export function Card({
  title,
  icon,
  meta,
  className = "",
  bodyClass = "card-body",
  children,
  as: Tag = "section",
  label,
  collapsible,
  defaultOpen = true,
}: {
  title: ReactNode;
  icon?: ReactNode;
  meta?: ReactNode;
  className?: string;
  bodyClass?: string;
  children: ReactNode;
  as?: "section" | "div";
  label?: string;
  /** Progressive disclosure: the header becomes a toggle and the body can be folded away. */
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  if (collapsible) {
    return (
      <details className={`card disclosure ${className}`} open={defaultOpen} aria-label={label}>
        <summary className="card-head">
          <h2>
            {icon}
            {title}
          </h2>
          <span className="spacer" />
          {meta && <span className="card-meta">{meta}</span>}
          <ChevronDown size={15} className="disc-chev" aria-hidden="true" />
        </summary>
        <div className={bodyClass}>{children}</div>
      </details>
    );
  }
  return (
    <Tag className={`card ${className}`} aria-label={label}>
      <header className="card-head">
        <h2>
          {icon}
          {title}
        </h2>
        <span className="spacer" />
        {meta && <span className="card-meta">{meta}</span>}
      </header>
      <div className={bodyClass}>{children}</div>
    </Tag>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div>
        <div className="icon">{icon}</div>
        <h3>{title}</h3>
        {children && <p>{children}</p>}
      </div>
    </div>
  );
}

export function Na({ children = "Not available" }: { children?: ReactNode }) {
  return <span className="na">{children}</span>;
}

export function InlineError({ children }: { children: ReactNode }) {
  return (
    <div className="inline-error" role="alert">
      <AlertCircle size={15} />
      <span>{children}</span>
    </div>
  );
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function SkeletonLines({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: "grid", gap: 10 }} aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skel" style={{ height: 14, width: `${88 - i * 14}%` }} />
      ))}
    </div>
  );
}
