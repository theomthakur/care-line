import type {
  Appointment,
  CallState,
  DaySlot,
  Draft,
  Evidence,
  Excluded,
  Member,
  Packet,
  Provider,
  Slot,
  Summary,
  Task,
  Turn,
} from "./types";

export class ApiError extends Error {
  /** HTTP status, or 0 when the backend could not be reached at all. */
  status: number;
  /** Machine-readable code from contracts/errors.md; "UNREACHABLE" when no response. */
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
  get unreachable() {
    return this.status === 0 || this.status >= 502;
  }
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "UNREACHABLE", "The backend could not be reached.");
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // fall through: non-JSON body (e.g. a proxy error page)
  }
  if (!res.ok) {
    const b = (body ?? {}) as { error?: unknown; speak?: unknown };
    const code = typeof b.error === "string" ? b.error : "HTTP_" + res.status;
    const msg = typeof b.speak === "string" && b.speak ? b.speak : `Request failed (${res.status}).`;
    throw new ApiError(res.status, code, msg);
  }
  if (body === null || typeof body !== "object") {
    throw new ApiError(res.status, "BAD_RESPONSE", "The backend returned an unreadable response.");
  }
  return body as T;
}

// ---------- defensive normalizer -------------------------------------------------
// The console must never crash on a partial payload, so every field is coerced to its
// documented empty value. Absence is rendered as "not available", never as success.

const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const obj = <T>(v: unknown): T | null =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as T) : null;

export function normalizeTask(raw: unknown): Task | null {
  const t = obj<Record<string, unknown>>(raw);
  if (!t) return null;
  const p = obj<Record<string, unknown>>(t.packet) ?? {};
  const packet: Packet = {
    reference: str(p.reference, "—"),
    category: str(p.category, "unknown"),
    summary: str(p.summary),
    detail: str(p.detail),
    caller_verified: p.caller_verified === true,
    plan: typeof p.plan === "string" ? p.plan : null,
    already_tried: arr<string>(p.already_tried).filter((x) => typeof x === "string"),
    suggested_next_action: str(p.suggested_next_action),
  };
  return {
    task_id: str(t.task_id),
    call_id: str(t.call_id),
    status: t.status === "completed" ? "completed" : "open",
    created_at: str(t.created_at),
    completed_at: typeof t.completed_at === "string" ? t.completed_at : null,
    packet,
  };
}

export function normalizeState(raw: unknown): CallState | null {
  const s = obj<Record<string, unknown>>(raw);
  if (!s || typeof s.call_id !== "string" || !s.call_id) return null;
  const req = obj<Record<string, unknown>>(s.request) ?? {};
  const turns = arr<Turn>(s.turns)
    .filter((t) => t && typeof t.seq === "number" && typeof t.text === "string")
    .sort((a, b) => a.seq - b.seq);
  const summary = obj<Summary>(s.summary);
  return {
    call_id: s.call_id,
    status: s.status === "finalized" ? "finalized" : "live",
    verified: s.verified === true,
    member: obj<Member>(s.member),
    request: {
      version: typeof req.version === "number" ? req.version : 0,
      specialty: typeof req.specialty === "string" ? req.specialty : null,
      zip: typeof req.zip === "string" ? req.zip : null,
    },
    turns,
    providers: arr<Provider>(s.providers),
    excluded: arr<Excluded>(s.excluded),
    selected: typeof s.selected === "string" ? s.selected : null,
    evidence: arr<Evidence>(s.evidence),
    offered_slots: arr<Slot>(s.offered_slots),
    draft: obj<Draft>(s.draft),
    appointment: obj<Appointment>(s.appointment),
    day_slots: arr<DaySlot>(s.day_slots),
    tasks: arr<unknown>(s.tasks).map(normalizeTask).filter((t): t is Task => t !== null),
    summary: summary && typeof summary.outcome === "string" ? summary : null,
    events: arr<string>(s.events).filter((e) => typeof e === "string"),
  };
}

// ---------- endpoints ---------------------------------------------------------------

/** GET /calls/latest -> null before any call. */
export async function getLatest(signal?: AbortSignal): Promise<CallState | null> {
  const body = await request<{ state?: unknown }>("/calls/latest", undefined, signal);
  if (body.state === null || body.state === undefined) return null;
  const state = normalizeState(body.state);
  if (!state) throw new ApiError(200, "BAD_RESPONSE", "The backend returned an unreadable call state.");
  return state;
}

export async function getTasks(status?: "open" | "completed", signal?: AbortSignal): Promise<Task[]> {
  const q = status ? `?status=${status}` : "";
  const body = await request<{ tasks?: unknown }>("/tasks" + q, undefined, signal);
  return arr<unknown>(body.tasks).map(normalizeTask).filter((t): t is Task => t !== null);
}

export async function completeTask(taskId: string): Promise<Task> {
  const body = await request<{ task?: unknown }>(`/tasks/${encodeURIComponent(taskId)}/complete`, {
    method: "POST",
    body: "{}",
  });
  const t = normalizeTask(body.task);
  if (!t) throw new ApiError(200, "BAD_RESPONSE", "The backend returned an unreadable task.");
  return t;
}

export async function takeSlot(slotId: string): Promise<void> {
  await request("/admin/take-slot", { method: "POST", body: JSON.stringify({ slot_id: slotId }) });
}

export async function resetDemo(): Promise<void> {
  await request("/admin/reset", { method: "POST", body: "{}" });
}

export interface CallListItem {
  call_id: string;
  status: 'live' | 'finalized';
  created_at: string;
  member: string | null;
  booked: boolean;
}

export async function getCallHistory(signal?: AbortSignal): Promise<CallListItem[]> {
  const body = await request<{ calls?: CallListItem[] }>('/calls/history', undefined, signal);
  return Array.isArray(body.calls) ? body.calls : [];
}

export async function getCallById(id: string, signal?: AbortSignal): Promise<CallState | null> {
  const body = await request<{ state?: unknown }>(`/calls/${encodeURIComponent(id)}/state`, undefined, signal);
  return normalizeState(body.state);
}
