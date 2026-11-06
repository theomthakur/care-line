import type { CallState, Turn } from "./types";

const TZ = "America/New_York";

export function clock(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit", timeZone: TZ }).format(d);
}

export function shortClock(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: TZ }).format(d);
}

export function slotTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: TZ }).format(d);
}

export function slotDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: TZ }).format(d);
}

export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ${s % 60}s ago`;
}

export function initials(name: string | undefined): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

export function humanize(s: string): string {
  const t = s.replace(/_/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function callStartedAt(state: CallState): string | null {
  const first = state.turns[0];
  if (!first) return null;
  const ms = new Date(first.received_at).getTime();
  if (Number.isNaN(ms)) return null;
  return new Date(ms - first.t * 1000).toISOString();
}

export function lastTurn(turns: Turn[]): Turn | null {
  return turns.length ? turns[turns.length - 1] : null;
}

export function isRedacted(text: string): boolean {
  return /^\[.*redacted.*\]$/i.test(text.trim());
}

/** Short, stable label for a call id: "call_269c9ab1336..." -> "269c9a"; "c_01" -> "01". */
export function shortId(id: string): string {
  return id.replace(/^(call|c)_/, "").slice(0, 6);
}

/** "12s", "3m 05s", "1h 02m" */
export function span(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

/** Elapsed time since the call started (live) or its final duration (finished). */
export function duration(createdAt: string, finishedAt: string | null, now: number): string {
  const start = new Date(createdAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : now;
  return Number.isNaN(start) || Number.isNaN(end) ? "—" : span(end - start);
}

export function sinceLabel(iso: string, now: number): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const d = now - t;
  return d < 4000 ? "just now" : `${span(d)} ago`;
}
