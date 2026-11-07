import { act, cleanup, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { normalizeSummary } from "./api";
import { Transcript, WINDOW } from "./components/Transcript";
import { FIXTURE_STAGES } from "./fixtures";
import { usePoll } from "./usePolling";
import type { CallState, CallSummary, Turn } from "./types";

// ---- a tiny fake backend that serves many calls --------------------------------------------

const base = FIXTURE_STAGES.find((f) => f.key === "verified")!.state!;

function turns(...texts: string[]): Turn[] {
  return texts.map((text, i) => ({ seq: i + 1, role: i % 2 ? "assistant" : "user", text, received_at: "2026-11-06T21:00:05Z", t: i }));
}
function mkState(id: string, name: string | null, ...texts: string[]): CallState {
  return {
    ...base,
    call_id: id,
    verified: !!name,
    member: name ? { ...base.member!, name, id_masked: "***" + id.slice(-4) } : null,
    turns: turns(...texts),
  };
}
function mkSummary(id: string, name: string | null, over: Partial<CallSummary> = {}): CallSummary {
  return {
    call_id: id, status: "live", verification: name ? "verified" : "unverified",
    member: name ? { name, id_masked: "***" + id.slice(-4) } : null, stage: name ? "verified" : "unverified",
    created_at: "2026-11-06T21:00:00Z", finalized_at: null, last_activity_at: "2026-11-06T21:00:05Z",
    turn_count: 1, task_count: 0, open_tasks: 0, outcome: null, confirmation: null, ...over,
  };
}

class Backend {
  summaries: CallSummary[] = [];
  states = new Map<string, CallState>();
  down = false;
  gate = new Map<string, Promise<void>>(); // hold a call's state response until released
  stateRequests: string[] = [];
  inflight = 0;
  maxInflight = 0;

  add(s: CallSummary, st: CallState) { this.summaries.unshift(s); this.states.set(s.call_id, st); }
  setState(id: string, st: CallState) { this.states.set(id, st); }

  fetch = async (url: string) => {
    if (this.down) throw new TypeError("network down");
    const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body }) as Response;
    if (url.startsWith("/calls?")) return json(200, { calls: this.summaries, speak: "" });
    const m = /^\/calls\/([^/]+)\/state$/.exec(url);
    if (m) {
      const id = decodeURIComponent(m[1]);
      this.stateRequests.push(id);
      this.inflight++; this.maxInflight = Math.max(this.maxInflight, this.inflight);
      try {
        await this.gate.get(id);
        const st = this.states.get(id);
        return st ? json(200, { state: st, speak: "" }) : json(404, { error: "CALL_NOT_FOUND", speak: "gone" });
      } finally { this.inflight--; }
    }
    return json(404, { error: "NOT_FOUND" });
  };
}

let be: Backend;
const tick = async (ms = 1000) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
const selectedName = () => within(screen.getByRole("listbox")).getAllByRole("option").find((o) => o.getAttribute("aria-selected") === "true")?.textContent ?? "";
const bubbles = () => [...document.querySelectorAll(".transcript .bubble")].map((b) => b.textContent);
const row = (label: RegExp) => screen.getAllByRole("option").find((o) => label.test(o.textContent ?? ""))!;

beforeEach(() => {
  vi.useFakeTimers();
  window.location.hash = "#view=conversations";
  be = new Backend();
  vi.stubGlobal("fetch", (url: string) => be.fetch(url));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

async function open(...calls: [string, string | null, string[]][]) {
  for (const [id, name, t] of calls.reverse()) be.add(mkSummary(id, name), mkState(id, name, ...t));
  render(<App />);
  await tick(50);
}

describe("multi-call console", () => {
  it("lists every active call and opens one, without mixing transcripts", async () => {
    await open(["call_A", "Maya T.", ["A-ONLY one"]], ["call_B", "Riley C.", ["B-ONLY one"]], ["call_C", null, ["C-ONLY one"]]);
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(selectedName()).toContain("Maya T."); // first (most recent) live call, picked once
    expect(bubbles()).toEqual(["A-ONLY one"]);
    await act(async () => row(/Riley/).click());
    await tick(50);
    expect(selectedName()).toContain("Riley C.");
    expect(bubbles()).toEqual(["B-ONLY one"]);
    expect(within(screen.getByRole("region", { name: "Selected conversation" })).getByTitle("call_B")).toBeInTheDocument(); // the case header names the opened call
  });

  it("keeps the selected call while other calls update and new calls arrive (scenarios B and E)", async () => {
    await open(["call_A", "Maya T.", ["A-ONLY one"]], ["call_B", "Riley C.", ["B-ONLY one"]]);
    expect(selectedName()).toContain("Maya T.");
    be.setState("call_B", mkState("call_B", "Riley C.", "B-ONLY one", "B reply", "B-ONLY two"));
    be.summaries.find((s) => s.call_id === "call_B")!.turn_count = 3;
    be.add(mkSummary("call_NEW", null), mkState("call_NEW", null, "NEW-ONLY hello"));
    await tick(1000);
    expect(screen.getAllByRole("option")).toHaveLength(3); // the new call appeared by itself
    expect(selectedName()).toContain("Maya T."); // and the selection did not move
    expect(bubbles()).toEqual(["A-ONLY one"]);
    expect(new Set(be.stateRequests.slice(-3))).toEqual(new Set(["call_A"])); // only A is polled in detail
    await act(async () => row(/Riley/).click());
    await tick(50);
    expect(bubbles()).toEqual(["B-ONLY one", "B reply", "B-ONLY two"]); // B's latest, nothing from A
  });

  it("drops a late response for a previously selected call", async () => {
    await open(["call_A", "Maya T.", ["A-ONLY one"]], ["call_B", "Riley C.", ["B-ONLY one"]]);
    // A's NEXT state response will be held back; meanwhile the operator opens B
    let release!: () => void;
    be.gate.set("call_A", new Promise<void>((r) => (release = r)));
    be.setState("call_A", mkState("call_A", "Maya T.", "A-ONLY one", "A-ONLY late"));
    await tick(1000);
    await act(async () => row(/Riley/).click());
    await tick(50);
    expect(bubbles()).toEqual(["B-ONLY one"]);
    be.gate.delete("call_A");
    release();
    await tick(50);
    expect(bubbles()).toEqual(["B-ONLY one"]); // the late A response never reaches the screen
    expect(selectedName()).toContain("Riley C.");
  });

  it("moves a finished call to Recent without changing the selection (scenario D)", async () => {
    await open(["call_A", "Maya T.", ["A-ONLY one"]], ["call_B", "Riley C.", ["B-ONLY one"]]);
    const a = be.summaries.find((s) => s.call_id === "call_A")!;
    Object.assign(a, { status: "finalized", stage: "ended", finalized_at: "2026-11-06T21:01:00Z" });
    be.setState("call_A", { ...mkState("call_A", "Maya T.", "A-ONLY one"), status: "finalized" });
    await tick(1000);
    expect(selectedName()).toContain("Maya T.");
    expect(within(screen.getByRole("region", { name: "Recent" })).getByText("Maya T.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Active" })).getByText("Riley C.")).toBeInTheDocument();
    expect(screen.getByText("Full transcript")).toBeInTheDocument();
  });

  it("survives a backend interruption on the same call and recovers (scenario F)", async () => {
    await open(["call_A", "Maya T.", ["A-ONLY one"]], ["call_B", "Riley C.", ["B-ONLY one"]]);
    await act(async () => row(/Riley/).click());
    await tick(50);
    be.down = true;
    await tick(20000);
    expect(screen.getByText(/Backend disconnected/)).toBeInTheDocument();
    expect(selectedName()).toContain("Riley C.");
    expect(bubbles()).toEqual(["B-ONLY one"]); // last good data kept, not blanked or swapped
    be.setState("call_B", mkState("call_B", "Riley C.", "B-ONLY one", "after recovery"));
    be.down = false;
    await tick(8000);
    expect(screen.queryByText(/Backend disconnected/)).toBeNull();
    expect(selectedName()).toContain("Riley C.");
    expect(bubbles()).toEqual(["B-ONLY one", "after recovery"]);
  });

  it("shows a clear state for an unknown call id and never falls back to another call", async () => {
    be.add(mkSummary("call_A", "Maya T."), mkState("call_A", "Maya T.", "A-ONLY one"));
    window.location.hash = "#call=call_missing";
    render(<App />);
    await tick(50);
    expect(screen.getByText("This call is no longer available")).toBeInTheDocument();
    expect(bubbles()).toEqual([]);
  });

  it("shows the empty state when there are no calls", async () => {
    render(<App />);
    await tick(50);
    expect(screen.getByText("Waiting for the next call")).toBeInTheDocument();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
  });

  it("handles five simultaneous calls with one in-flight detail request", async () => {
    const calls: [string, string | null, string[]][] = ["A", "B", "C", "D", "E"].map((k) => [`call_${k}`, `Member ${k}`, [`${k}-ONLY`]]);
    await open(...calls);
    expect(screen.getAllByRole("option")).toHaveLength(5);
    await tick(5000);
    expect(be.maxInflight).toBe(1);
  });

  it("normalizes a partial summary without crashing", () => {
    expect(normalizeSummary(null)).toBeNull();
    const s = normalizeSummary({ call_id: "x", stage: "bogus", member: 3, open_tasks: "many" })!;
    expect(s.stage).toBe("ended");
    expect(s.member).toBeNull();
    expect(s.open_tasks).toBe(0);
  });
});

describe("usePoll", () => {
  it("aborts on key change and ignores the old key's late result", async () => {
    let resolveOld!: (v: string) => void;
    const fetcher = vi.fn((_s: AbortSignal) => new Promise<string>((r) => { if (!resolveOld) resolveOld = r; else r("new"); }));
    const { result, rerender } = renderHook(({ k }) => usePoll(fetcher, k, 1000), { initialProps: { k: "a" } });
    rerender({ k: "b" });
    await tick(10);
    resolveOld("OLD");
    await tick(10);
    expect(result.current.data).toBe("new");
  });

  it("stops polling on unmount", async () => {
    const fetcher = vi.fn(async () => "x");
    const { unmount } = renderHook(() => usePoll(fetcher, "k", 1000));
    await tick(2500);
    const n = fetcher.mock.calls.length;
    unmount();
    await tick(5000);
    expect(fetcher.mock.calls.length).toBe(n);
  });
});

describe("long transcripts", () => {
  it("renders only the newest window and reveals earlier turns on demand", async () => {
    const many: Turn[] = Array.from({ length: 1000 }, (_, i) => ({ seq: i + 1, role: i % 2 ? "assistant" : "user", text: `m${i + 1}`, received_at: "2026-11-06T21:00:05Z", t: i }));
    render(<Transcript turns={many} live={false} callId="c" />);
    expect(document.querySelectorAll(".turn")).toHaveLength(WINDOW);
    expect(screen.getByText("m1000")).toBeInTheDocument();
    expect(screen.queryByText("m1")).toBeNull();
    await act(async () => screen.getByText(/Show 800 earlier messages/).click());
    expect(document.querySelectorAll(".turn")).toHaveLength(1000);
  });
});
