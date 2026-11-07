import { useCallback, useEffect, useState } from "react";

export type ThemeMode = "light" | "dark" | "system";

const KEY = "careline-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function read(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "light";
  } catch {
    return "light";
  }
}

const prefersDark = () => (typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY).matches : false);

export function resolveTheme(mode: ThemeMode): "light" | "dark" {
  return mode === "system" ? (prefersDark() ? "dark" : "light") : mode;
}

/** Applies the theme to <html>. The only thing persisted is the mode name, never case data. */
export function applyTheme(mode: ThemeMode) {
  const root = document.documentElement;
  root.dataset.theme = resolveTheme(mode);
  root.dataset.themeMode = mode;
}

/** Light, dark, or follow the operating system (live: a system change updates the page). */
export function useTheme(): { mode: ThemeMode; resolved: "light" | "dark"; setMode: (m: ThemeMode) => void } {
  const [mode, setModeState] = useState<ThemeMode>(read);
  const [resolved, setResolved] = useState<"light" | "dark">(() => resolveTheme(mode));

  useEffect(() => {
    applyTheme(mode);
    setResolved(resolveTheme(mode));
    if (mode !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => {
      applyTheme("system");
      setResolved(resolveTheme("system"));
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  const setMode = useCallback((m: ThemeMode) => {
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* private mode: the choice still applies for this session */
    }
    setModeState(m);
  }, []);

  return { mode, resolved, setMode };
}
