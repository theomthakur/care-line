import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronsLeft, ChevronsRight, HandHeart, LayoutDashboard, MessagesSquare, Menu, Monitor, Moon, Presentation, Settings, Stethoscope, Sun, Workflow, X } from "lucide-react";
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
  { view: "conversations", label: "Conversations", icon: <MessagesSquare size={18} /> },
  { view: "followups", label: "Follow-ups", icon: <HandHeart size={18} /> },
  { view: "providers", label: "Providers", icon: <Stethoscope size={18} /> },
];

const THEMES: { mode: ThemeMode; label: string; icon: ReactNode }[] = [
  { mode: "light", label: "Light", icon: <Sun size={15} /> },
  { mode: "dark", label: "Dark", icon: <Moon size={15} /> },
  { mode: "system", label: "System", icon: <Monitor size={15} /> },
];

export function AppShell({
  view,
  onNavigate,
  counts,
  theme,
  onTheme,
  developer,
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
  developer: boolean;
  onDeveloper: (on: boolean) => void;
  title: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawer, setDrawer] = useState(false);
  const [settings, setSettings] = useState(false);
  const [explore, setExplore] = useState(false);
  const menuBtn = useRef<HTMLButtonElement>(null);
  const settingsBtn = useRef<HTMLButtonElement>(null);
  const settingsPop = useRef<HTMLDivElement>(null);
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

  // Escape closes the drawer and the settings panel; focus goes back to where it came from.
  useEffect(() => {
    if (!drawer && !settings) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (settings) {
        setSettings(false);
        settingsBtn.current?.focus();
      } else closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer, settings, closeDrawer]);

  useEffect(() => {
    if (!settings) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!settingsPop.current?.contains(t) && !settingsBtn.current?.contains(t)) setSettings(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [settings]);

  useEffect(() => {
    if (drawer) navRef.current?.querySelector<HTMLElement>("a.nav-link")?.focus();
  }, [drawer]);

  const go = (v: View) => {
    onNavigate(v);
    setDrawer(false);
    setSettings(false);
  };

  const badge = (v: View) => {
    if (v === "conversations") return counts.active > 0 ? { n: counts.active, tone: "live", label: `${counts.active} active` } : null;
    if (v === "followups") return counts.followups > 0 ? { n: counts.followups, tone: "attention", label: `${counts.followups} open` } : null;
    return null;
  };

  return (
    <div className={`appshell ${collapsed ? "is-collapsed" : ""} ${drawer ? "drawer-open" : ""}`}>
      <aside className="nav" id="primary-nav" ref={navRef} aria-label="Primary">
        <div className="nav-top">
          <a className="nav-brand" href={buildHash({ view: "overview", call: null })} onClick={(e) => { e.preventDefault(); go("overview"); }} aria-label="Care Line, go to Overview">
            {collapsed ? <LogoMark size={34} /> : <Logo size={36} />}
          </a>
          <button type="button" className="nav-close" onClick={closeDrawer} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>

        <nav className="nav-list" aria-label="Main">
          {ITEMS.map((it) => {
            const b = badge(it.view);
            const active = view === it.view;
            return (
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
                {b && <span className={`nav-badge ${b.tone}`} aria-hidden="true">{b.n}</span>}
              </a>
            );
          })}
          <button type="button" className="nav-link" aria-expanded={explore} aria-controls="explore-menu" data-tip="System design and presentation" onClick={() => setExplore((open) => !open)}>
            <Workflow size={18} /><span className="nav-text">Explore</span><ChevronDown size={15} className="nav-text" />
          </button>
          {explore && <div id="explore-menu">
            <button type="button" className="nav-link" onClick={() => go("architecture")} data-tip="System design"><Workflow size={17} /><span className="nav-text">System design</span></button>
            <button type="button" className="nav-link" onClick={() => go("presentation")} data-tip="Presentation"><Presentation size={17} /><span className="nav-text">Presentation</span></button>
          </div>}
          {counts.attention > 0 && (
            <p className="nav-note" role="status">
              <span className="dot" /> {counts.attention} {counts.attention === 1 ? "call needs" : "calls need"} attention
            </p>
          )}
        </nav>

        <div className="nav-bottom">
          <button
            type="button"
            ref={settingsBtn}
            className={`nav-link ${settings ? "selected" : ""}`}
            aria-expanded={settings}
            aria-controls="settings-panel"
            aria-label="Settings and appearance"
            data-tip="Settings"
            onClick={() => setSettings((o) => !o)}
          >
            <Settings size={18} />
            <span className="nav-text">Settings</span>
          </button>
          <button
            type="button"
            className="nav-link nav-collapse"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-pressed={collapsed}
            data-tip={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleCollapsed}
          >
            {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
            <span className="nav-text">Collapse sidebar</span>
          </button>
          <p className="nav-foot">Synthetic demo data</p>
        </div>

        {settings && (
          <div className="settings-pop" id="settings-panel" ref={settingsPop} role="dialog" aria-label="Settings and appearance">
            <h2>Appearance</h2>
            <div className="seg-control" role="radiogroup" aria-label="Theme">
              {THEMES.map((t) => (
                <button key={t.mode} type="button" role="radio" aria-checked={theme === t.mode} className={theme === t.mode ? "on" : ""} onClick={() => onTheme(t.mode)}>
                  {t.icon} {t.label}
                </button>
              ))}
            </div>
            <p className="settings-hint">System follows your device and changes with it.</p>
            <h2>More</h2>
            <label className="settings-switch">
              <input type="checkbox" checked={developer} onChange={(e) => onDeveloper(e.target.checked)} />
              <span>Show developer view</span>
            </label>
            {developer && <button type="button" className="settings-link" onClick={() => go("developer")}>Open developer view</button>}
          </div>
        )}
      </aside>

      {drawer && <div className="nav-scrim" onClick={closeDrawer} aria-hidden="true" />}

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
          <h1 className="topbar-title">{title}</h1>
          <span className="topbar-spacer" />
          <div className="topbar-right">{right}</div>
        </header>
        <div className="appbody">{children}</div>
      </div>
    </div>
  );
}
