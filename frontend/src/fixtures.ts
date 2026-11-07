// Development fixtures: verbatim copies of contracts/examples/state-*.json.
// Used ONLY when the URL has ?source=fixture. The live console never imports from here
// at runtime paths that read backend data (see App.tsx).
import { normalizeState } from "./api";
import type { CallState } from "./types";
import idle from "./fixtures/state-idle.json";
import unverified from "./fixtures/state-unverified.json";
import verified from "./fixtures/state-verified.json";
import offered from "./fixtures/state-offered.json";
import preview from "./fixtures/state-preview.json";
import armed from "./fixtures/state-armed.json";
import conflict from "./fixtures/state-conflict.json";
import booked from "./fixtures/state-booked.json";
import finalized from "./fixtures/state-finalized.json";
import followup from "./fixtures/state-followup.json";

export const FIXTURE_STAGES: { key: string; label: string; state: CallState | null }[] = [
  { key: "idle", label: "No call", raw: idle },
  { key: "unverified", label: "Unverified", raw: unverified },
  { key: "verified", label: "Verified", raw: verified },
  { key: "offered", label: "Times offered", raw: offered },
  { key: "preview", label: "Read-back", raw: preview },
  { key: "armed", label: "Awaiting yes", raw: armed },
  { key: "conflict", label: "Slot taken", raw: conflict },
  { key: "booked", label: "Booked", raw: booked },
  { key: "finalized", label: "Finalized", raw: finalized },
  { key: "followup", label: "Follow-up", raw: followup },
].map(({ raw, ...rest }) => ({ ...rest, state: normalizeState((raw as { state: unknown }).state) }));

/** Read-only synthetic cases for exploring the hosted workspace. */
function sampleCase(stage: string, id: string, name: string): CallState {
  const original = FIXTURE_STAGES.find((s) => s.key === stage)?.state;
  if (!original) throw new Error(`Missing sample stage: ${stage}`);
  const copy: CallState = JSON.parse(JSON.stringify(original));
  copy.call_id = id;
  if (copy.member) copy.member.name = name;
  copy.turns = copy.turns.map((t) => ({ ...t, text: t.text.replaceAll('Maya', name.split(' ')[0]) }));
  copy.tasks = copy.tasks.map((t, i) => ({ ...t, call_id: id, task_id: `${id}_task_${i + 1}` }));
  return copy;
}
export const DEMO_CASES = [
  sampleCase('booked', 'demo_booked', 'Maya T.'),
  sampleCase('offered', 'demo_searching', 'Jordan R.'),
  sampleCase('conflict', 'demo_conflict', 'Alex P.'),
  sampleCase('followup', 'demo_followup', 'Samira K.'),
  sampleCase('finalized', 'demo_finished', 'Daniel L.'),
];
export const DEMO_TASKS = DEMO_CASES.flatMap((c) => c.tasks);
