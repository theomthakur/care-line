// Mirrors contracts/api.md ("Console and handoff interfaces" and the State table).
// The contract is still "proposed": if a field changes, change it here and in api.ts only.

export type CallStatus = "live" | "finalized";
export type TurnRole = "user" | "assistant";
export type DraftStatus = "slot" | "preview" | "armed" | "booked";
export type SlotState = "open" | "booked" | "blocked";
export type TaskStatus = "open" | "completed";
export type SummaryOutcome = "booked" | "followup" | "not_completed" | "unknown";
export type TaskCategory =
  | "caller_requested"
  | "knowledge_gap"
  | "verification_failed"
  | "tool_failure"
  | "safety"
  | "policy_required"
  | "waitlist";

export interface Member {
  name: string;
  id_masked: string;
  plan: string;
  network: string;
  active: boolean;
}

export interface Provider {
  id: string;
  name: string;
  specialty: string;
  zip: string;
  phone: string;
  accepting_new_patients: boolean;
}

export interface Excluded {
  id: string;
  name: string;
  reason_code: string;
  reason: string;
}

export interface Evidence {
  id: string;
  title: string;
  text: string;
}

export interface Slot {
  slot_id: string;
  provider_id?: string;
  starts_at: string;
  ends_at: string;
  timezone?: string;
  text: string;
}

export interface DaySlot {
  slot_id: string;
  starts_at: string;
  ends_at: string;
  text: string;
  state: SlotState;
  offered: boolean;
  selected: boolean;
}

export interface Turn {
  seq: number;
  role: TurnRole;
  text: string;
  received_at: string;
  t: number;
}

export interface Draft {
  slot_id: string;
  revision: number;
  status: DraftStatus;
  armed_seq: number | null;
  expires_at: string | null;
}

export interface Appointment {
  appointment_id: string;
  status: "booked";
  confirmation: string;
  provider_id: string;
  slot_id: string;
  doctor: string;
  phone: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  when: string;
  simulated: boolean;
}

export interface Packet {
  reference: string;
  category: TaskCategory | string;
  summary: string;
  detail: string;
  caller_verified: boolean;
  plan: string | null;
  already_tried: string[];
  suggested_next_action: string;
}

export interface Task {
  task_id: string;
  call_id: string;
  status: TaskStatus;
  created_at: string;
  completed_at: string | null;
  packet: Packet;
}

export interface Summary {
  outcome: SummaryOutcome;
  reason: string;
  text: string;
  confirmation: string | null;
  /** "dropped" when the backend closed a call the voice agent never finalized. */
  ended_reason?: string;
}

/** Facts for the post-call summary, re-read from saved rows by GET /calls/{id}/summary. */
export interface SummaryDetails {
  verification: "verified" | "failed" | "locked" | "not_attempted";
  provider: { name: string; phone: string | null } | null;
  appointment: { confirmation: string; when: string; doctor: string; phone: string | null } | null;
  problems: string[];
  follow_ups: { reference: string; status: "open" | "completed"; category: string | null; next_action: string }[];
  next_action: string;
}

export interface CallSummaryDoc {
  status: CallStatus;
  summary: Summary | null;
  details: SummaryDetails;
}

export interface CallState {
  call_id: string;
  status: CallStatus;
  verified: boolean;
  member: Member | null;
  request: { version: number; specialty: string | null; zip: string | null };
  turns: Turn[];
  providers: Provider[];
  excluded: Excluded[];
  selected: string | null;
  evidence: Evidence[];
  offered_slots: Slot[];
  draft: Draft | null;
  appointment: Appointment | null;
  day_slots: DaySlot[];
  tasks: Task[];
  summary: Summary | null;
  events: string[];
}

export interface ApiErrorBody {
  error: string;
  speak?: string;
}

// ---- multi-call console (GET /calls, GET /calls/{id}/state) ------------------------------

export type CallStage =
  | "unverified"
  | "locked"
  | "verified"
  | "searching"
  | "offering"
  | "readback"
  | "awaiting_yes"
  | "conflict"
  | "booked"
  | "followup"
  | "ended";

/** One row of the call list. Built by the backend from stored rows; never contains secrets. */
export interface CallSummary {
  call_id: string;
  status: CallStatus;
  verification: "unverified" | "verified" | "locked";
  member: { name: string; id_masked: string } | null;
  stage: CallStage;
  created_at: string;
  finalized_at: string | null;
  last_activity_at: string;
  turn_count: number;
  task_count: number;
  open_tasks: number;
  outcome: SummaryOutcome | null;
  confirmation: string | null;
}
