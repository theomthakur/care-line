import { useState } from "react";
import { FlaskConical, RotateCcw, UserMinus } from "lucide-react";
import { ApiError, resetDemo, takeSlot } from "../api";
import { takeTarget } from "../derive";
import type { CallState } from "../types";
import { InlineError, Spinner } from "./ui";

export function DemoControls({ s, canAct, onChanged }: { s: CallState | null; canAct: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState<"take" | "reset" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);
  const target = s ? takeTarget(s) : null;

  async function run(kind: "take" | "reset") {
    setBusy(kind);
    setErr(null);
    try {
      if (kind === "take" && target) await takeSlot(target.slot_id);
      if (kind === "reset") await resetDemo();
      setArmed(false);
      onChanged();
    } catch (e) {
      setErr(
        e instanceof ApiError && e.code === "CALL_ACTIVE"
          ? "Reset refused: a call is still active. End the call first."
          : e instanceof ApiError && e.code === "SLOT_TAKEN"
            ? "That time is already occupied."
            : e instanceof ApiError
              ? e.message
              : "The action failed.",
      );
      setArmed(false);
    } finally {
      setBusy(null);
    }
  }

  const why = !canAct ? "Disabled in fixture mode" : undefined;
  return (
    <section className="card demo" aria-label="Demo controls">
      <header className="card-head" style={{ borderBottomStyle: "dashed" }}>
        <h2><FlaskConical size={15} /> Demo controls</h2>
        <span className="spacer" />
        <span className="card-meta">Simulation only</span>
      </header>
      <div className="card-body">
        <div className="demo-row">
          <div className="grow">
            <div className="t">Another caller takes this slot</div>
            <div className="d">{target ? `Blocks ${target.text} in the simulated schedule.` : "Available while an offered time is still open."}</div>
          </div>
          <button className="btn" onClick={() => run("take")} disabled={!canAct || !target || busy !== null} title={why}>
            {busy === "take" ? <Spinner /> : <UserMinus size={14} />} Take slot
          </button>
        </div>
        <div className="demo-row">
          <div className="grow">
            <div className="t">Reset demo</div>
            <div className="d">Clears calls, tasks and bookings. Refused while a call is live.</div>
          </div>
          {armed ? (
            <>
              <button className="btn sm ghost" onClick={() => setArmed(false)} disabled={busy !== null}>Cancel</button>
              <button className="btn danger solid" onClick={() => run("reset")} disabled={busy !== null}>
                {busy === "reset" ? <Spinner /> : <RotateCcw size={14} />} Confirm reset
              </button>
            </>
          ) : (
            <button className="btn danger" onClick={() => setArmed(true)} disabled={!canAct || busy !== null} title={why}>
              <RotateCcw size={14} /> Reset
            </button>
          )}
        </div>
        {err && <InlineError>{err}</InlineError>}
      </div>
    </section>
  );
}

/** The printed synthetic card a judge is handed. It is not verified state. */
export function DemoMemberCard() {
  return (
    <div className="member-card" aria-label="Demo member card">
      <div className="h">Demo member card · printed, synthetic</div>
      <span className="k">Name</span><span className="v">Maya Torres</span>
      <span className="k">Last 4 digits</span><span className="v">4417</span>
      <span className="k">Birth month</span><span className="v">April</span>
    </div>
  );
}
