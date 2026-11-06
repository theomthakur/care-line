import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { normalizeState } from "./api";
import { bookingPhase } from "./derive";
import { FIXTURE_STAGES } from "./fixtures";
import { useLatest } from "./usePolling";
import { BookingCard } from "./components/OutcomePanels";
import { ApiError } from "./api";

const stage = (k: string) => FIXTURE_STAGES.find((f) => f.key === k)!.state!;

describe("normalizeState", () => {
  it("returns null for a missing call and survives partial payloads", () => {
    expect(normalizeState(null)).toBeNull();
    const s = normalizeState({ call_id: "c_9", turns: "nope", member: 5, draft: [] })!;
    expect(s.turns).toEqual([]);
    expect(s.member).toBeNull();
    expect(s.draft).toBeNull();
    expect(s.appointment).toBeNull();
    expect(s.tasks).toEqual([]);
  });
});

describe("booking honesty", () => {
  it("never reads as booked unless the backend returned an appointment", () => {
    for (const k of ["unverified", "verified", "offered", "preview", "armed", "conflict", "followup"]) {
      const s = stage(k);
      expect(s.appointment, k).toBeNull();
      expect(bookingPhase(s), k).not.toBe("confirmed");
    }
    expect(bookingPhase(stage("booked"))).toBe("confirmed");
  });

  it("shows the confirmation number only for a committed appointment", () => {
    const { unmount } = render(<BookingCard s={stage("armed")} />);
    expect(screen.queryByText(/MG-APT/)).toBeNull();
    expect(screen.getByText(/Awaiting caller's yes/)).toBeInTheDocument();
    unmount();
    render(<BookingCard s={stage("booked")} />);
    expect(screen.getByText("MG-APT-4821")).toBeInTheDocument();
  });

  it("flags a taken slot as a conflict, not a booking", () => {
    expect(bookingPhase(stage("conflict"))).toBe("conflict");
  });
});

describe("useLatest", () => {
  it("keeps the last good state and marks it stale, then disconnected", async () => {
    vi.useFakeTimers();
    const good = stage("verified");
    let calls = 0;
    const fetcher = vi.fn(async () => {
      calls += 1;
      if (calls === 1) return good;
      throw new ApiError(0, "UNREACHABLE", "down");
    });
    const { result } = renderHook(() => useLatest(fetcher, 100));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(result.current.connection).toBe("connected");
    await act(async () => { await vi.advanceTimersByTimeAsync(150); });
    expect(result.current.connection).toBe("stale");
    expect(result.current.state).toEqual(good);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(result.current.connection).toBe("disconnected");
    expect(result.current.state).toEqual(good);
    vi.useRealTimers();
  });

  it("never has two requests in flight", async () => {
    vi.useFakeTimers();
    let inflight = 0, max = 0;
    const fetcher = vi.fn(async () => {
      inflight += 1; max = Math.max(max, inflight);
      await new Promise((r) => setTimeout(r, 500));
      inflight -= 1;
      return null;
    });
    renderHook(() => useLatest(fetcher, 100));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(max).toBe(1);
    expect(fetcher).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
