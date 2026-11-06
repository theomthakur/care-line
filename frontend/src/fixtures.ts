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
