import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Code2,
  ChevronsLeft,
  ChevronsRight,
  ChevronRight,
  CircleHelp,
  ShieldCheck,
  HandHeart,
  LayoutDashboard,
  MessagesSquare,
  Menu,
  Moon,
  Presentation,
  Stethoscope,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import { Logo, LogoMark } from "../Logo";
import { buildHash, type View } from "../route";
import type { ThemeMode } from "../theme";

export interface NavCounts {
  active: number;
  attention: number;
  followups: number;
}

const SIDEBAR_KEY = "careline-sidebar";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "closed";
  } catch {
    return false;
  }
}

const ITEMS: { view: View; label: string; icon: ReactNode }[] = [
  { view: "overview", label: "Overview", icon: <LayoutDashboard size={18} /> },
  {
    view: "conversations",
    label: "Conversations",
    icon: <MessagesSquare size={18} />,
  },
  { view: "followups", label: "Follow-ups", icon: <HandHeart size={18} /> },
  { view: "providers", label: "Providers", icon: <Stethoscope size={18} /> },
  {
    view: "architecture",
    label: "System design",
    icon: <Workflow size={18} />,
  },
  {
    view: "presentation",
    label: "Presentation",
    icon: <Presentation size={18} />,
  },
];

export function AppShell({
  view,
  onNavigate,
  counts,
  theme,
  onTheme,
  onDeveloper,
  title,
  right,
  children,
}: {
  view: View;
  onNavigate: (v: View) => void;
  counts: NavCounts;
  theme: ThemeMode;
  onTheme: (m: ThemeMode) => void;
  onDeveloper: (on: boolean) => void;
  title: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawer, setDrawer] = useState(false);
  const menuBtn = useRef<HTMLButtonElement>(null);
  const navRef = useRef<HTMLElement>(null);

  const toggleCollapsed = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, c ? "open" : "closed");
      } catch {
        /* preference only */
      }
      return !c;
    });

  const closeDrawer = useCallback(() => {
    setDrawer(false);
    menuBtn.current?.focus();
  }, []);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer, closeDrawer]);

  useEffect(() => {
    if (drawer)
      navRef.current?.querySelector<HTMLElement>("a.nav-link")?.focus();
  }, [drawer]);

  const go = (v: View) => {
    onNavigate(v);
    setDrawer(false);
  };

  const badge = (v: View) => {
    if (v === "conversations")
      return counts.active > 0
        ? { n: counts.active, tone: "live", label: `${counts.active} active` }
        : null;
    if (v === "followups")
      return counts.followups > 0
        ? {
            n: counts.followups,
            tone: "attention",
            label: `${counts.followups} open`,
          }
        : null;
    return null;
  };

  return (
    <div
      className={`appshell ${collapsed ? "is-collapsed" : ""} ${drawer ? "drawer-open" : ""}`}
    >
      <aside className="nav" id="primary-nav" ref={navRef} aria-label="Primary">
        <div className="nav-top">
          <a
            className="nav-brand"
            href={buildHash({ view: "overview", call: null })}
            onClick={(e) => {
              e.preventDefault();
              go("overview");
            }}
            aria-label="Care Line, go to Overview"
          >
            {collapsed ? <LogoMark size={34} /> : <Logo size={36} />}
          </a>
          <button
            type="button"
            className="nav-collapse nav-collapse-top"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-pressed={collapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleCollapsed}
          >
            {collapsed ? (
              <ChevronsRight size={18} />
            ) : (
              <ChevronsLeft size={18} />
            )}
          </button>
          <button
            type="button"
            className="nav-close"
            onClick={closeDrawer}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="nav-list" aria-label="Main">
          <p className="nav-section-label">WORKSPACE</p>
          {ITEMS.map((it) => {
            const b = badge(it.view);
            const active = view === it.view;
            return (
              <div className="nav-item-wrap" key={it.view}>
                {it.view === "architecture" && (
                  <p className="nav-section-label resources-label">PROJECT</p>
                )}
                <a
                  key={it.view}
                  href={buildHash({ view: it.view, call: null })}
                  className={`nav-link ${active ? "selected" : ""}`}
                  aria-current={active ? "page" : undefined}
                  aria-label={b ? `${it.label}, ${b.label}` : it.label}
                  data-tip={it.label}
                  onClick={(e) => {
                    e.preventDefault();
                    go(it.view);
                  }}
                >
                  {it.icon}
                  <span className="nav-text">{it.label}</span>
                  {b && (
                    <span className={`nav-badge ${b.tone}`} aria-hidden="true">
                      {b.n}
                    </span>
                  )}
                </a>
              </div>
            );
          })}
          {counts.attention > 0 && (
            <p className="nav-note" role="status">
              <span className="dot" /> {counts.attention}{" "}
              {counts.attention === 1 ? "call needs" : "calls need"} attention
            </p>
          )}
        </nav>

        <div className="nav-bottom">
          <button
            type="button"
            className="nav-link"
            data-tip={theme === "dark" ? "Light mode" : "Dark mode"}
            aria-label={
              theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
            }
            onClick={() => onTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            <span className="nav-text">
              {theme === "dark" ? "Light mode" : "Dark mode"}
            </span>
          </button>
          <button
            type="button"
            className={`nav-link ${view === "developer" ? "selected" : ""}`}
            data-tip="Developer view"
            onClick={() => {
              onDeveloper(true);
              go("developer");
            }}
          >
            <Code2 size={18} />
            <span className="nav-text">Developer view</span>
          </button>
          <div className="nav-workspace-card">
            <span className="workspace-icon">
              <ShieldCheck size={17} />
            </span>
            <div>
              <b>Member support</b>
              <small>Synthetic demo data</small>
            </div>
          </div>
        </div>
      </aside>

      {drawer && (
        <div className="nav-scrim" onClick={closeDrawer} aria-hidden="true" />
      )}

      <div className="appmain">
        <header className="topbar">
          <button
            type="button"
            ref={menuBtn}
            className="nav-open"
            aria-label="Open navigation"
            aria-expanded={drawer}
            aria-controls="primary-nav"
            onClick={() => setDrawer(true)}
          >
            <Menu size={19} />
          </button>
          <div className="topbar-breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={13} />
            <h1 className="topbar-title">{title}</h1>
          </div>
          <span className="topbar-spacer" />
          <div className="topbar-right">
            {right}
            <span className="topbar-divider" />
            <a
              className="topbar-help"
              href="https://github.com/theomthakur/care-line#readme"
              target="_blank"
              rel="noreferrer"
              aria-label="Project documentation"
            >
              <CircleHelp size={18} />
            </a>
            <span
              className="operator-avatar"
              title="Member support workspace"
              aria-label="Member support"
            >
              CL
            </span>
          </div>
        </header>
        <div className="appbody">{children}</div>
      </div>
    </div>
  );
}
