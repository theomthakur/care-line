import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { normalizeDetails } from "./api";
import { actionNeeded, needsAttention, statusView } from "./derive";
import { FIXTURE_STAGES } from "./fixtures";
import type { CallState, CallSummary, SummaryDetails } from "./types";

// A small fake backend that serves the list, one state and one summary per call, and the follow-up list.

const stage = (k: string) => FIXTURE_STAGES.find((f) => f.key === k)!.state!;
const withId = (s: CallState, id: string): CallState => ({ ...s, call_id: id });

function row(s: CallState, over: Partial<CallSummary> = {}): CallSummary {
  const finalized = s.status === "finalized";
  return {
    call_id: s.call_id,
    status: s.status,
    verification: s.verified ? "verified" : "unverified",
    member: s.member ? { name: s.member.name, id_masked: s.member.id_masked } : null,
    stage: s.appointment ? "booked" : finalized ? (s.tasks.length ? "followup" : "ended") : "verified",
    created_at: "2026-11-06T21:00:00Z",
    finalized_at: finalized ? "2026-11-06T21:02:00Z" : null,
    last_activity_at: "2026-11-06T21:01:00Z",
    turn_count: s.turns.length,
    task_count: s.tasks.length,
    open_tasks: s.tasks.filter((t) => t.status === "open").length,
    outcome: s.summary?.outcome ?? null,
    confirmation: s.appointment?.confirmation ?? null,
    ...over,
  };
}

function detailsFor(s: CallState): SummaryDetails {
  return {
    verification: s.verified ? "verified" : "not_attempted",
    provider: s.appointment ? { name: s.appointment.doctor, phone: s.appointment.phone } : null,
    appointment: s.appointment ? { confirmation: s.appointment.confirmation, when: s.appointment.when, doctor: s.appointment.doctor, phone: s.appointment.phone } : null,
    problems: s.events.includes("slot_taken") ? ["A time the caller chose was taken by someone else."] : [],
    follow_ups: s.tasks.map((t) => ({ reference: t.packet.reference, status: t.status, category: t.packet.category, next_action: t.packet.suggested_next_action })),
    next_action: s.appointment ? "No action needed. The appointment is booked." : s.tasks.length ? `${s.tasks[0].packet.reference}: ${s.tasks[0].packet.suggested_next_action}` : "Call the member back if they still need a visit.",
  };
}

class Backend {
  states = new Map<string, CallState>();
  rows: CallSummary[] = [];
  summaryRequests: string[] = [];
  put(s: CallState, over: Partial<CallSummary> = {}) {
    this.states.set(s.call_id, s);
    this.rows = [row(s, over), ...this.rows.filter((r) => r.call_id !== s.call_id)];
  }
  fetch = async (url: string) => {
    const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body }) as Response;
    if (url.startsWith("/calls?")) return json(200, { calls: this.rows, speak: "" });
    if (url.startsWith("/tasks")) return json(200, { tasks: [...this.states.values()].flatMap((s) => s.tasks), speak: "" });
    let m = /^\/calls\/([^/]+)\/state$/.exec(url);
    if (m) {
      const st = this.states.get(decodeURIComponent(m[1]));
      return st ? json(200, { state: st, speak: "" }) : json(404, { error: "CALL_NOT_FOUND", speak: "gone" });
    }
    m = /^\/calls\/([^/]+)\/summary$/.exec(url);
    if (m) {
      const id = decodeURIComponent(m[1]);
      this.summaryRequests.push(id);
      const st = this.states.get(id);
      return st ? json(200, { status: st.status, summary: st.summary, details: detailsFor(st), speak: "" }) : json(404, { error: "CALL_NOT_FOUND", speak: "gone" });
    }
    return json(404, { error: "NOT_FOUND" });
  };
}

let be: Backend;
const tick = async (ms = 1000) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const header = () => within(screen.getByRole("region", { name: "Selected conversation" }));
const option = (re: RegExp) => screen.getAllByRole("option").find((o) => re.test(o.textContent ?? ""))!;

function mockMatchMedia(initialDark: boolean) {
  let dark = initialDark;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (q: string) => ({
    media: q,
    get matches() {
      return q.includes("dark") ? dark : false;
    },
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }));
  return (next: boolean) => {
    dark = next;
    listeners.forEach((fn) => fn());
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  window.location.hash = "#view=conversations";
  be = new Backend();
  vi.stubGlobal("fetch", (url: string) => be.fetch(url));
  mockMatchMedia(false);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function open() {
  render(<App />);
  await tick(50);
}

describe("A/B. sidebar navigation", () => {
  it("shows the four primary destinations in a left navigation", async () => {
    await open();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const labels = within(nav).getAllByRole("link").map((a) => a.getAttribute("data-tip"));
    expect(labels).toEqual(["Overview", "Conversations", "Follow-ups", "Providers"]);
    expect(within(nav).getByRole("link", { name: "Conversations" })).toHaveAttribute("aria-current", "page");
  });

  it("collapses to an icon rail, remembers the choice, and stays operable by label", async () => {
    await open();
    const btn = screen.getByRole("button", { name: "Collapse sidebar" });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    await act(async () => btn.click());
    expect(document.querySelector(".appshell")).toHaveClass("is-collapsed");
    expect(localStorage.getItem("careline-sidebar")).toBe("closed");
    // every item keeps an accessible name and a tooltip label while collapsed
    expect(screen.getByRole("link", { name: "Providers" })).toHaveAttribute("data-tip", "Providers");
    cleanup();
    await open();
    expect(document.querySelector(".appshell")).toHaveClass("is-collapsed"); // preference survives a reload
    await act(async () => screen.getByRole("button", { name: "Expand sidebar" }).click());
    expect(localStorage.getItem("careline-sidebar")).toBe("open");
  });

  it("opens as a drawer from the menu button and closes with Escape or after navigating", async () => {
    await open();
    const menu = screen.getByRole("button", { name: "Open navigation" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    await act(async () => menu.click());
    expect(document.querySelector(".appshell")).toHaveClass("drawer-open");
    expect(menu).toHaveAttribute("aria-expanded", "true");
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(document.querySelector(".appshell")).not.toHaveClass("drawer-open");
    await act(async () => menu.click());
    await act(async () => screen.getByRole("link", { name: "Providers" }).click());
    expect(document.querySelector(".appshell")).not.toHaveClass("drawer-open");
  });

  it("navigates between pages and keeps the page in the URL", async () => {
    await open();
    await act(async () => screen.getByRole("link", { name: "Overview" }).click());
    expect(screen.getByRole("heading", { name: "Overview", level: 2 })).toBeInTheDocument();
    expect(window.location.hash).toBe("#view=overview");
    await act(async () => screen.getByRole("link", { name: "Follow-ups" }).click());
    await tick(50);
    expect(screen.getByRole("heading", { name: "Follow-ups", level: 2 })).toBeInTheDocument();
  });
});

describe("settings do not move the operator", () => {
  it("turning the developer view off keeps the open conversation and page", async () => {
    be.put(withId(stage("booked"), "call_A"));
    window.location.hash = "#view=conversations&call=call_A";
    await open();
    await act(async () => screen.getByRole("button", { name: "Settings and appearance" }).click());
    const box = screen.getByRole("checkbox", { name: "Show developer view" });
    await act(async () => box.click()); // on
    await act(async () => box.click()); // off again
    expect(window.location.hash).toBe("#view=conversations&call=call_A");
    expect(header().getByText("MG-APT-4821")).toBeInTheDocument();
  });

  it("falls back to Overview only when the developer view itself is switched off", async () => {
    window.location.hash = "#view=developer";
    localStorage.setItem("careline-developer", "off");
    await open();
    expect(window.location.hash).toBe("#view=overview");
  });
});

describe("C. appearance", () => {
  const openSettings = async () => {
    await act(async () => screen.getByRole("button", { name: "Settings and appearance" }).click());
  };
  const choose = async (name: string) => {
    await act(async () => within(screen.getByRole("radiogroup", { name: "Theme" })).getByRole("radio", { name }).click());
  };

  it("defaults to the system theme and offers light, dark and system", async () => {
    await open();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.dataset.themeMode).toBe("system");
    await openSettings();
    expect(within(screen.getByRole("radiogroup", { name: "Theme" })).getAllByRole("radio").map((r) => r.textContent?.trim())).toEqual(["Light", "Dark", "System"]);
    expect(screen.getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  });

  it("applies and persists an explicit choice", async () => {
    await open();
    await openSettings();
    await choose("Dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("careline-theme")).toBe("dark");
    cleanup();
    document.documentElement.removeAttribute("data-theme");
    await open();
    expect(document.documentElement.dataset.theme).toBe("dark"); // restored on reload
    await openSettings();
    await choose("Light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("follows the operating system while System is selected", async () => {
    cleanup();
    const setSystemDark = mockMatchMedia(false);
    await open();
    expect(document.documentElement.dataset.theme).toBe("light");
    await act(async () => setSystemDark(true));
    expect(document.documentElement.dataset.theme).toBe("dark");
    await openSettings();
    await choose("Light"); // an explicit choice stops following the system
    await act(async () => setSystemDark(true));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("F/G/H/I. a booked call stays in view and its summary is available", () => {
  it("keeps the confirmed booking visible while the call ends, then shows the saved summary", async () => {
    be.put(withId(stage("booked"), "call_A"));
    window.location.hash = "#view=conversations&call=call_A";
    await open();
    expect(header().getByText("MG-APT-4821")).toBeInTheDocument(); // the backend's own confirmation
    expect(header().getByText("Active call")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Call summary" })).toBeNull(); // no summary before the call ends

    be.put(withId(stage("finalized"), "call_A")); // the voice agent hangs up and finalizes
    await tick(2500);
    expect(window.location.hash).toContain("call=call_A"); // nothing navigated away
    expect(header().getByText("MG-APT-4821")).toBeInTheDocument(); // booking still visible
    expect(header().getByText("Call completed")).toBeInTheDocument();
    expect(screen.getAllByText("Maya T.").length).toBeGreaterThan(0);
    expect(document.querySelectorAll(".transcript .bubble").length).toBeGreaterThan(0); // transcript kept
    const sum = within(screen.getByRole("region", { name: "Call summary" }));
    expect(sum.getByText("Appointment booked")).toBeInTheDocument();
    expect(sum.getByText("Member verified")).toBeInTheDocument();
    expect(sum.getByText(/No action needed/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Recent" })).getByText("Maya T.")).toBeInTheDocument();
    expect(option(/Maya/)).toHaveAttribute("aria-selected", "true");
  });

  it("reopening a finished call shows its existing summary", async () => {
    be.put(withId(stage("followup"), "call_F"));
    be.put(withId(stage("booked"), "call_L"));
    window.location.hash = "#view=conversations&call=call_L";
    await open();
    expect(screen.queryByRole("region", { name: "Call summary" })).toBeNull();
    await act(async () => option(/#call_F|F\b|Needs follow-up/).click());
    await tick(2500);
    expect(be.summaryRequests).toContain("call_F");
    expect(within(screen.getByRole("region", { name: "Call summary" })).getAllByText("MG-4822", { exact: false }).length).toBeGreaterThan(0);
  });
});

describe("J. unsuccessful calls report an accurate outcome", () => {
  it("a follow-up call is not shown as booked and tells the operator what to do", async () => {
    be.put(withId(stage("followup"), "call_F"));
    window.location.hash = "#view=conversations&call=call_F";
    await open();
    await tick(2500);
    const sum = within(screen.getByRole("region", { name: "Call summary" }));
    expect(sum.getByText("Needs follow-up")).toBeInTheDocument();
    expect(sum.queryByText("Appointment booked")).toBeNull();
    expect(sum.getByText("No appointment booked")).toBeInTheDocument();
    expect(sum.getByText("Next step")).toBeInTheDocument();
    expect(header().getByText("Not booked")).toBeInTheDocument();
    expect(header().queryByText("Confirmed")).toBeNull();
    expect(screen.getByRole("alert", { name: "" })).toHaveTextContent(/follow up/i);
  });

  it("a call that ended with nothing done reads 'Ended without booking'", async () => {
    const s: CallState = { ...withId(stage("finalized"), "call_N"), appointment: null, summary: { outcome: "not_completed", reason: "Hello?", text: "The call ended without a booking or a follow-up request. Nothing was written to the schedule.", confirmation: null }, tasks: [], events: ["call_created", "finalized"] };
    be.put(s);
    window.location.hash = "#view=conversations&call=call_N";
    await open();
    await tick(2500);
    expect(within(screen.getByRole("region", { name: "Call summary" })).getByText("Ended without booking")).toBeInTheDocument();
    expect(header().getByText("Not booked")).toBeInTheDocument();
  });

  it("labels and attention rules are plain language", () => {
    const base = { status: "finalized" as const, stage: "ended" as const, outcome: null, open_tasks: 0 };
    expect(statusView({ ...base, outcome: "not_completed" }).label).toBe("Ended without booking");
    expect(statusView({ ...base, outcome: "unknown" }).label).toBe("Needs review");
    expect(statusView({ ...base, stage: "booked", outcome: "booked" }).label).toBe("Appointment booked");
    expect(statusView({ status: "live", stage: "awaiting_yes", outcome: null, open_tasks: 0 }).label).toBe("Awaiting confirmation");
    expect(statusView({ status: "live", stage: "searching", outcome: null, open_tasks: 0 }).label).toBe("Looking for provider");
    expect(statusView({ status: "live", stage: "unverified", outcome: null, open_tasks: 0 }).label).toBe("Active call");
    expect(needsAttention({ ...base, stage: "followup", open_tasks: 1 })).toBe(true);
    expect(needsAttention({ ...base, stage: "followup", open_tasks: 0 })).toBe(false);
    expect(needsAttention({ ...base, outcome: "not_completed" })).toBe(false);
    expect(actionNeeded(stage("followup"))?.detail).toMatch(/MG-4822/);
    expect(actionNeeded(stage("booked"))).toBeNull();
  });

  it("tolerates a partial summary document", () => {
    expect(normalizeDetails(null)).toBeNull();
    const d = normalizeDetails({ verification: "bogus", follow_ups: [{ nope: 1 }], problems: [3, "x"] })!;
    expect(d.verification).toBe("not_attempted");
    expect(d.follow_ups).toEqual([]);
    expect(d.problems).toEqual(["x"]);
  });
});

describe("K. refresh keeps the selected call", () => {
  it("restores the conversation named in the URL, and not the newest one", async () => {
    be.put(withId(stage("booked"), "call_A"));
    be.put({ ...withId(stage("verified"), "call_B"), member: { ...stage("verified").member!, name: "Riley C." } });
    window.location.hash = "#view=conversations&call=call_A";
    await open();
    expect(option(/Maya/)).toHaveAttribute("aria-selected", "true");
    expect(option(/Riley/)).toHaveAttribute("aria-selected", "false");
    expect(window.location.hash).toBe("#view=conversations&call=call_A");
  });

  it("opens a conversation from the older #call= link format", async () => {
    be.put(withId(stage("booked"), "call_A"));
    window.location.hash = "#call=call_A";
    render(<App />);
    await tick(50);
    expect(screen.getByRole("heading", { name: "Conversations", level: 1 })).toBeInTheDocument();
    expect(header().getByText("MG-APT-4821")).toBeInTheDocument();
  });
});

describe("L. privacy in navigation, lists and storage", () => {
  it("shows no transcript text or member numbers in list rows or on the overview", async () => {
    const s = withId(stage("booked"), "call_P");
    be.put(s);
    window.location.hash = "#view=conversations&call=call_P";
    await open();
    const rowText = option(/Maya/).textContent ?? "";
    for (const turn of s.turns) expect(rowText).not.toContain(turn.text.slice(0, 20));
    expect(rowText).not.toMatch(/\*\*\*\d{4}|\b\d{4}\b(?!\s*ago)/);
    await act(async () => screen.getByRole("link", { name: "Overview" }).click());
    const page = document.querySelector(".overview")?.textContent ?? "";
    for (const turn of s.turns) expect(page).not.toContain(turn.text.slice(0, 20));
    expect(page).not.toContain("***");
  });

  it("stores only harmless preferences in the browser", async () => {
    const s = withId(stage("booked"), "call_P");
    be.put(s);
    window.location.hash = "#view=conversations&call=call_P";
    await open();
    await act(async () => screen.getByRole("button", { name: "Collapse sidebar" }).click());
    await act(async () => screen.getByRole("button", { name: "Settings and appearance" }).click());
    await act(async () => within(screen.getByRole("radiogroup", { name: "Theme" })).getByRole("radio", { name: "Dark" }).click());
    await tick(2500);
    const keys = Object.keys(localStorage).sort();
    expect(keys.every((k) => ["careline-sidebar", "careline-theme", "careline-developer"].includes(k))).toBe(true);
    const everything = JSON.stringify({ ...localStorage });
    expect(everything).not.toContain("Maya");
    expect(everything).not.toContain("MG-APT");
    expect(everything).not.toContain(s.turns[0].text.slice(0, 20));
  });

  it("asks the browser never to cache API responses", async () => {
    const init: RequestInit[] = [];
    vi.stubGlobal("fetch", (url: string, i?: RequestInit) => {
      if (i) init.push(i);
      return be.fetch(url);
    });
    be.put(withId(stage("booked"), "call_A"));
    await open();
    expect(init.length).toBeGreaterThan(0);
    expect(init.every((i) => i.cache === "no-store")).toBe(true);
  });
});

describe("conversations: one workspace for active, needs attention and recent", () => {
  it("groups each call once and lets the operator search and filter", async () => {
    be.put(withId(stage("booked"), "call_A")); // active, booked
    be.put(withId(stage("followup"), "call_F")); // finished, open follow-up -> needs attention
    be.put({ ...withId(stage("finalized"), "call_Z"), member: { ...stage("finalized").member!, name: "Zed Z." } }); // finished, nothing open
    await open();
    expect(screen.getAllByRole("option")).toHaveLength(3); // never duplicated across groups
    expect(within(screen.getByRole("region", { name: "Needs attention" })).getAllByRole("option")).toHaveLength(1);
    expect(within(screen.getByRole("region", { name: "Active" })).getAllByRole("option")).toHaveLength(1);
    expect(within(screen.getByRole("region", { name: "Recent" })).getByText("Zed Z.")).toBeInTheDocument();

    await act(async () => screen.getByRole("tab", { name: /^Needs attention/ }).click());
    expect(screen.getAllByRole("option")).toHaveLength(1);
    await act(async () => screen.getByRole("tab", { name: /^All/ }).click());

    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(search, "zed");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("Zed Z.");
  });

  it("states what is happening and whether a human has to act, for the selected call", async () => {
    be.put(withId(stage("armed"), "call_R"));
    window.location.hash = "#view=conversations&call=call_R";
    await open();
    expect(header().getByText("What the AI is doing")).toBeInTheDocument();
    expect(header().getByText(/waiting for the caller to say yes/i)).toBeInTheDocument();
    expect(header().getByText("Awaiting the caller's yes")).toBeInTheDocument();
    expect(header().queryByText(/MG-APT/)).toBeNull(); // not booked until the backend says so
  });
});
