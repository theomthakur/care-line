// Everything the UI claims is derived here, strictly from backend state.
// Nothing is optimistic: an action only reads "confirmed" if `appointment` is present.
import type { CallStage, CallState, CallSummary } from "./types";
import { humanize } from "./format";

export type Tone = "good" | "warn" | "bad" | "info" | "neutral";
export type SegState = "done" | "current" | "failed" | "todo";

export interface Segment { key: string; label: string; state: SegState }

export function hasConflict(s: CallState): boolean {
  // The chosen time is no longer open (e.g. another caller took it) while the draft still points at it.
  if (!s.appointment && s.draft) {
    const d = s.day_slots.find((x) => x.slot_id === s.draft!.slot_id);
    if (d && d.state !== "open") return true;
  }
  // A taken slot is "live" trouble only while nothing is booked and no draft is held.
  return !s.appointment && s.events.includes("slot_taken") && lastIndex(s.events, "slot_taken") > lastIndex(s.events, "slot_selected");
}

function lastIndex(events: string[], name: string) {
  return events.lastIndexOf(name);
}

export type BookingPhase = "none" | "proposed" | "awaiting_yes" | "confirmed" | "conflict";

export function bookingPhase(s: CallState): BookingPhase {
  if (s.appointment) return "confirmed";
  if (hasConflict(s)) return "conflict";
  if (s.draft?.status === "armed") return "awaiting_yes";
  if (s.draft && (s.draft.status === "slot" || s.draft.status === "preview")) return "proposed";
  if (hasConflict(s)) return "conflict";
  return "none";
}

export function progress(s: CallState): Segment[] {
  const conflict = bookingPhase(s) === "conflict";
  const verified = s.verified;
  const provider = !!s.selected;
  const time = !!s.draft || !!s.appointment;
  const readback = s.draft ? ["preview", "armed", "booked"].includes(s.draft.status) : !!s.appointment;
  const booked = !!s.appointment;
  const flags = [verified, provider, time, readback, booked];
  const firstTodo = flags.findIndex((f) => !f);
  const labels = ["Verified", "Provider", "Time", "Read-back", "Booked"];
  return labels.map((label, i) => {
    let state: SegState = flags[i] ? "done" : i === firstTodo ? "current" : "todo";
    if (conflict && (i === 2 || i === 3)) state = i === 2 ? "failed" : "todo";
    if (conflict && i === 4) state = "todo";
    if (s.status === "finalized" && state === "current") state = "todo";
    return { key: label.toLowerCase(), label, state };
  });
}

const EVENT_LABELS: Record<string, { label: string; tone: Tone }> = {
  call_created: { label: "Call connected", tone: "neutral" },
  verified: { label: "Member verified against synthetic records", tone: "good" },
  verification_failed: { label: "Verification did not match", tone: "bad" },
  verification_locked: { label: "Verification locked after 3 attempts", tone: "bad" },
  providers_searched: { label: "In-network providers searched", tone: "info" },
  provider_selected: { label: "Provider selected", tone: "info" },
  availability_offered: { label: "Open times offered", tone: "info" },
  slot_selected: { label: "Caller chose a time", tone: "info" },
  preview_created: { label: "Read-back prepared", tone: "info" },
  confirmation_armed: { label: "Read-back finished. Awaiting the caller's yes", tone: "warn" },
  slot_taken: { label: "Slot taken by another caller", tone: "bad" },
  preview_invalidated: { label: "Read-back voided. A new one is needed", tone: "warn" },
  booked: { label: "Appointment committed to the schedule", tone: "good" },
  appointment_booked: { label: "Appointment committed to the schedule", tone: "good" }, // core's event name
  followup_created: { label: "Follow-up handoff saved", tone: "info" },
  finalized: { label: "Call ended and summarized", tone: "neutral" },
  zip_changed: { label: "Caller corrected the ZIP", tone: "info" },
};

export function eventView(name: string): { label: string; tone: Tone } {
  return EVENT_LABELS[name] ?? { label: humanize(name), tone: "neutral" };
}

export function verificationLabel(s: CallState): { text: string; tone: "green" | "red" | "amber" } {
  if (s.verified) return { text: "Verified", tone: "green" };
  if (s.tasks.some((t) => t.packet.category === "verification_failed")) return { text: "Locked", tone: "red" };
  return { text: "Not verified", tone: "amber" };
}

/** A slot the "Another caller takes this slot" button may target: open and relevant to the call. */
export function takeTarget(s: CallState): { slot_id: string; text: string } | null {
  const open = s.day_slots.filter((d) => d.state === "open");
  const pick =
    open.find((d) => d.slot_id === s.draft?.slot_id) ?? open.find((d) => d.selected) ?? open.find((d) => d.offered);
  return pick ? { slot_id: pick.slot_id, text: pick.text } : null;
}

// ---- conversation list ------------------------------------------------------------------------

export const STAGE_VIEW: Record<CallStage, { label: string; tone: "slate" | "amber" | "red" | "blue" | "teal" | "green" }> = {
  unverified: { label: "Verifying", tone: "amber" },
  locked: { label: "Locked", tone: "red" },
  verified: { label: "Verified", tone: "blue" },
  searching: { label: "Finding doctors", tone: "blue" },
  offering: { label: "Choosing a time", tone: "blue" },
  readback: { label: "Read-back", tone: "teal" },
  awaiting_yes: { label: "Awaiting yes", tone: "amber" },
  conflict: { label: "Slot taken", tone: "red" },
  booked: { label: "Booked", tone: "green" },
  followup: { label: "Follow-up", tone: "blue" },
  ended: { label: "Ended", tone: "slate" },
};

/** Fixture mode only: derive a list row from a saved state. Live mode always uses GET /calls. */
export function summaryFromState(s: CallState): CallSummary {
  const phase = bookingPhase(s);
  const stage: CallStage = s.appointment
    ? "booked"
    : s.status === "finalized"
      ? s.tasks.length || s.summary?.outcome === "followup" ? "followup" : "ended"
      : !s.verified
        ? s.tasks.some((t) => t.packet.category === "verification_failed") ? "locked" : "unverified"
        : phase === "awaiting_yes" ? "awaiting_yes"
        : phase === "proposed" ? "readback"
        : phase === "conflict" ? "conflict"
        : s.selected || s.offered_slots.length ? "offering"
        : s.providers.length || s.excluded.length ? "searching"
        : "verified";
  const last = s.turns[s.turns.length - 1];
  const first = s.turns[0];
  const created = first ? new Date(new Date(first.received_at).getTime() - first.t * 1000).toISOString() : new Date().toISOString();
  return {
    call_id: s.call_id,
    status: s.status,
    verification: s.verified ? "verified" : s.tasks.some((t) => t.packet.category === "verification_failed") ? "locked" : "unverified",
    member: s.member ? { name: s.member.name, id_masked: s.member.id_masked } : null,
    stage,
    created_at: created,
    finalized_at: s.status === "finalized" ? (last?.received_at ?? created) : null,
    last_activity_at: last?.received_at ?? created,
    turn_count: s.turns.length,
    task_count: s.tasks.length,
    open_tasks: s.tasks.filter((t) => t.status === "open").length,
    outcome: s.summary?.outcome ?? null,
    confirmation: s.appointment?.confirmation ?? null,
    last_turn: last ? { role: last.role, text: last.text } : null,
  };
}
