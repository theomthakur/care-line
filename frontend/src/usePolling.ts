import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import type { CallState } from "./types";

export type Connection = "loading" | "connected" | "stale" | "disconnected";

export interface LatestResult {
  state: CallState | null;
  connection: Connection;
  /** Epoch ms of the last successful response. */
  lastOk: number | null;
  error: ApiError | null;
  refresh: () => void;
}

/** After this many consecutive failures the backend is treated as down, not just slow. */
const DISCONNECT_AFTER = 3;

/**
 * Polls `fetcher` back to back (the next request starts `interval` ms after the previous
 * one settles), so requests never overlap. Pauses while the tab is hidden. The last good
 * state is kept on failure and flagged stale rather than hidden or replaced.
 */
export function useLatest(
  fetcher: (signal: AbortSignal) => Promise<CallState | null>,
  interval = 1000,
  enabled = true,
): LatestResult {
  const [state, setState] = useState<CallState | null>(null);
  const [connection, setConnection] = useState<Connection>("loading");
  const [lastOk, setLastOk] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const failures = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const inflight = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const tickRef = useRef<() => void>(() => {});

  const tick = useCallback(async () => {
    if (!alive.current) return;
    if (inflight.current) return; // one request at a time
    const ctl = new AbortController();
    inflight.current = ctl;
    try {
      const next = await fetcherRef.current(ctl.signal);
      if (!alive.current) return;
      failures.current = 0;
      setState(next);
      setError(null);
      setLastOk(Date.now());
      setConnection("connected");
    } catch (e) {
      if ((e as Error).name === "AbortError" || !alive.current) return;
      failures.current += 1;
      setError(e instanceof ApiError ? e : new ApiError(0, "UNREACHABLE", "The backend could not be reached."));
      setConnection(failures.current >= DISCONNECT_AFTER ? "disconnected" : "stale");
    } finally {
      if (inflight.current === ctl) inflight.current = null;
      if (alive.current && enabled && !document.hidden) {
        clearTimeout(timer.current);
        // back off a little while the backend is failing
        timer.current = setTimeout(() => tickRef.current(), failures.current ? Math.min(interval * (1 + failures.current), 5000) : interval);
      }
    }
  }, [interval, enabled]);
  tickRef.current = tick;

  useEffect(() => {
    alive.current = true;
    if (!enabled) return;
    void tick();
    const onVis = () => {
      if (!document.hidden) {
        clearTimeout(timer.current);
        void tick();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      inflight.current?.abort();
      inflight.current = null;
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [tick, enabled]);

  const refresh = useCallback(() => {
    clearTimeout(timer.current);
    void tick();
  }, [tick]);

  return { state, connection, lastOk, error, refresh };
}
