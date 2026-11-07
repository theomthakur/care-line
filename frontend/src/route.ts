import { useCallback, useEffect, useState } from "react";

export type View = "overview" | "conversations" | "followups" | "providers" | "architecture" | "presentation" | "developer";

const VIEWS: View[] = ["overview", "conversations", "followups", "providers", "architecture", "presentation", "developer"];

export interface Route {
  view: View;
  call: string | null;
}

/** `#view=conversations&call=<id>`. A bare `#call=<id>` (older links) opens that conversation. */
export function parseHash(hash: string = window.location.hash): Route {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const call = params.get("call");
  const v = params.get("view") as View | null;
  if (v && VIEWS.includes(v)) return { view: v, call: v === "conversations" ? call : null };
  return { view: call ? "conversations" : "overview", call };
}

export function buildHash(r: Route): string {
  const p = new URLSearchParams();
  p.set("view", r.view);
  if (r.view === "conversations" && r.call) p.set("call", r.call);
  return "#" + p.toString();
}

/**
 * The page and the open conversation live in the URL hash so a refresh or a shared link
 * returns to the same place. The hash holds only ids, never names or transcript text.
 */
export function useRoute(enabled = true): { route: Route; go: (r: Partial<Route>) => void } {
  const [route, setRoute] = useState<Route>(() => (enabled ? parseHash() : { view: "conversations", call: null }));

  useEffect(() => {
    if (!enabled) return;
    const sync = () => setRoute(parseHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [enabled]);

  const go = useCallback(
    (next: Partial<Route>) => {
      setRoute((cur) => {
        const merged = { ...cur, ...next };
        if (enabled) window.history.replaceState(null, "", buildHash(merged));
        return merged;
      });
    },
    [enabled],
  );
  return { route, go };
}
