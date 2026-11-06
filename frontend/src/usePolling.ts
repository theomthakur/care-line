import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import type { CallState } from "./types";

export type Connection = "loading" | "connected" | "stale" | "disconnected";

export interface PollResult<T> {
  /** `undefined` until the first response for the CURRENT key; never data fetched for a previous key. */
  data: T | undefined;
  connection: Connection;
  /** Epoch ms of the last successful response. */
  lastOk: number | null;
  error: ApiError | null;
  refresh: () => void;
}

/** After this many consecutive failures the backend is treated as down, not just slow. */
const DISCONNECT_AFTER = 3;

interface Snap<T> {
  key: string | null;
  data: T | undefined;
  connection: Connection;
  lastOk: number | null;
  error: ApiError | null;
}

const fresh = <T,>(key: string | null): Snap<T> => ({ key, data: undefined, connection: "loading", lastOk: null, error: null });

const sameJson = (a: unknown, b: unknown) => a === b || (a !== undefined && b !== undefined && JSON.stringify(a) === JSON.stringify(b));

/**
 * Polls `fetcher` back to back (the next request starts `interval` ms after the previous one
 * settles), so requests never overlap. Everything is scoped to `key`: when the key changes the
 * in-flight request is aborted, state resets, and a late response for the old key is dropped,
 * so a newly selected call can never be overwritten by the previous one. Pauses while the tab is
 * hidden. The last good data is kept on failure and flagged stale. Unchanged payloads keep their
 * object identity so memoised panels do not re-render.
 */
export function usePoll<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  key: string | null,
  interval = 1000,
  enabled = true,
): PollResult<T> {
  const [snap, setSnap] = useState<Snap<T>>(() => fresh<T>(key));
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const runRef = useRef<() => void>(() => {});
  const active = enabled && key !== null;

  useEffect(() => {
    setSnap(fresh<T>(key));
    if (!active) return;
    let cancelled = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ctl: AbortController | null = null;

    const schedule = () => {
      clearTimeout(timer);
      if (cancelled || document.hidden) return;
      timer = setTimeout(run, failures ? Math.min(interval * (1 + failures), 5000) : interval);
    };

    async function run() {
      if (cancelled || ctl) return; // one request at a time
      const mine = new AbortController();
      ctl = mine;
      try {
        const next = await fetcherRef.current(mine.signal);
        if (cancelled) return;
        failures = 0;
        setSnap((prev) => ({
          key,
          data: prev.key === key && sameJson(prev.data, next) ? prev.data : next,
          connection: "connected",
          lastOk: Date.now(),
          error: null,
        }));
      } catch (e) {
        if ((e as Error).name === "AbortError" || cancelled) return;
        failures += 1;
        const err = e instanceof ApiError ? e : new ApiError(0, "UNREACHABLE", "The backend could not be reached.");
        setSnap((prev) => ({
          ...(prev.key === key ? prev : fresh<T>(key)),
          key,
          error: err,
          connection: failures >= DISCONNECT_AFTER ? "disconnected" : "stale",
        }));
      } finally {
        if (ctl === mine) ctl = null;
        if (!cancelled) schedule();
      }
    }
    runRef.current = () => {
      clearTimeout(timer);
      void run();
    };

    const onVis = () => {
      if (!document.hidden) runRef.current();
    };
    document.addEventListener("visibilitychange", onVis);
    void run();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      ctl?.abort();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [key, active, interval]);

  const refresh = useCallback(() => runRef.current(), []);
  const mine = snap.key === key ? snap : fresh<T>(key);
  return { data: mine.data, connection: mine.connection, lastOk: mine.lastOk, error: mine.error, refresh };
}

export interface LatestResult {
  state: CallState | null;
  connection: Connection;
  lastOk: number | null;
  error: ApiError | null;
  refresh: () => void;
}

/** The original single-call poll (`GET /calls/latest`), kept for existing consumers and tests. */
export function useLatest(
  fetcher: (signal: AbortSignal) => Promise<CallState | null>,
  interval = 1000,
  enabled = true,
): LatestResult {
  const r = usePoll(fetcher, "latest", interval, enabled);
  return { state: r.data ?? null, connection: r.connection, lastOk: r.lastOk, error: r.error, refresh: r.refresh };
}
