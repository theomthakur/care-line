import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarCheck2,
  CalendarClock,
  Check,
  CheckCircle2,
  ClipboardList,
  Clock,
  Flag,
  HandHeart,
  History,
  Phone,
  Hourglass,
  X,
} from "lucide-react";
import { ApiError, completeTask } from "../api";
import { bookingPhase, eventView, progress } from "../derive";
import { shortClock, slotDay, slotTime } from "../format";
import type { CallState, DaySlot, SummaryOutcome, Task } from "../types";
import { Card, Chip, Empty, InlineError, Na, Spinner } from "./ui";

function useCountdown(iso: string | null | undefined, on: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [on]);
  if (!iso || !on) return null;
  const end = new Date(iso).getTime();
  return Number.isNaN(end) ? null : Math.max(0, Math.ceil((end - now) / 1000));
}

// ---------------------------------------------------------------- booking

export function BookingCard({ s }: { s: CallState }) {
  const phase = bookingPhase(s);
  const segs = progress(s);
  const left = useCountdown(s.draft?.expires_at, phase === "awaiting_yes");
  const a = s.appointment;
  const draftSlot = s.draft ? s.day_slots.find((d) => d.slot_id === s.draft!.slot_id) ?? s.offered_slots.find((o) => o.slot_id === s.draft!.slot_id) : undefined;
  const provider = s.providers.find((p) => p.id === s.selected);

  return (
    <section className={`card booking ${phase === "confirmed" ? "confirmed" : ""}`} aria-label="Appointment outcome">
      <div className="booking-top">
        <CalendarCheck2 size={15} color={phase === "confirmed" ? "var(--green-700)" : "var(--ink-400)"} />
        <h2 style={{ fontSize: 13, fontWeight: 620, color: phase === "confirmed" ? "var(--green-700)" : undefined }}>Appointment</h2>
        <span style={{ flex: 1 }} />
        {phase === "confirmed" && <Chip tone="green"><CheckCircle2 size={12} /> Confirmed by backend</Chip>}
        {phase === "awaiting_yes" && <Chip tone="amber"><Hourglass size={12} /> Awaiting caller's yes</Chip>}
        {phase === "proposed" && <Chip tone="blue">Proposed · not booked</Chip>}
        {phase === "conflict" && <Chip tone="red"><AlertTriangle size={12} /> Slot taken</Chip>}
        {phase === "none" && <Chip>{s.status === "finalized" ? "Not booked" : "No appointment yet"}</Chip>}
      </div>
      <div className="booking-state">
        <div className="progress" role="list" aria-label="Booking progress">
          {segs.map((g) => (
            <div key={g.key} role="listitem" className={`seg ${g.state}`} aria-label={`${g.label}: ${g.state === "done" ? "complete" : g.state === "current" ? "in progress" : g.state === "failed" ? "failed" : "not started"}`}>
              <div className="bar" />
              {g.label}
            </div>
          ))}
        </div>

        {a ? (
          <div style={{ marginTop: 18 }}>
            <div className="confirm-label">Confirmation number</div>
            <div className="confirm-num" aria-label={`Confirmation ${a.confirmation}`}>{a.confirmation}</div>
            <div className="muted" style={{ fontSize: 12.5 }}>Stored as appointment <span className="mono">{a.appointment_id}</span>{a.simulated ? " · simulated schedule" : ""}</div>
            <div className="booking-grid">
              <div className="wide"><div className="lbl">When</div><div className="val">{a.when}</div></div>
              <div><div className="lbl">Doctor</div><div className="val">{a.doctor}</div></div>
              <div><div className="lbl">Office phone</div><div className="val num">{a.phone}</div></div>
            </div>
          </div>
        ) : (
          <>
            {phase === "none" && (
              <div className="pending-note neutral">
                <Clock size={16} />
                <span>{s.status === "finalized" ? "The call ended without a booking. Nothing was written to the schedule." : "Nothing booked. A confirmation number appears here only after the backend commits the appointment."}</span>
              </div>
            )}
            {(phase === "proposed" || phase === "awaiting_yes") && (
              <div className={`pending-note ${phase === "awaiting_yes" ? "amber" : "neutral"}`}>
                {phase === "awaiting_yes" ? <Hourglass size={16} /> : <CalendarClock size={16} />}
                <div>
                  <b>{draftSlot ? draftSlot.text : "A time is selected"}</b>
                  {provider ? <> with {provider.name}</> : null}
                  <div style={{ marginTop: 3 }}>
                    {phase === "proposed" ? "Draft only. The agent still has to read the details back, and the caller has to say yes." : "Read-back finished. Not booked until the caller says a clear yes."}
                    {phase === "awaiting_yes" && left !== null && (
                      <> {left > 0 ? <span className="countdown">Window closes in {left}s.</span> : <span>Window has closed. Waiting for the backend to void it.</span>}</>
                    )}
                  </div>
                </div>
              </div>
            )}
            {phase === "conflict" && (
              <div className="pending-note red">
                <AlertTriangle size={16} />
                <div>
                  <b>Another caller took the chosen time.</b>
                  <div style={{ marginTop: 3 }}>The read-back is void and nothing was booked. The agent has to offer new times and read back again.</div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- timeline

export function ActivityTimeline({ s }: { s: CallState }) {
  return (
    <Card title="Activity" icon={<History size={15} />} meta={s.events.length ? `${s.events.length} events` : undefined}>
      {s.events.length === 0 ? (
        <span className="muted">Backend events appear here in order.</span>
      ) : (
        <ol className="timeline" style={{ margin: 0, padding: 0, listStyle: "none" }}>
          {s.events.map((name, i) => {
            const v = eventView(name);
            return (
              <li key={`${i}-${name}`} className={`tl-item ${v.tone === "neutral" ? "" : v.tone}`}>
                <span className="tl-mark" aria-hidden="true">
                  {v.tone === "bad" ? <X size={10} strokeWidth={3} /> : v.tone === "warn" ? <Hourglass size={9} strokeWidth={3} /> : v.tone === "neutral" ? null : <Check size={10} strokeWidth={3} />}
                </span>
                <div>
                  <div className="tl-label">{v.label}</div>
                  <div className="tl-sub mono">{name}</div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- slots

function slotChip(d: DaySlot) {
  if (d.state === "open") return <Chip tone="green">Open</Chip>;
  if (d.state === "blocked") return <Chip tone="red">Taken · simulated caller</Chip>;
  return <Chip>Booked</Chip>;
}

export function SlotList({ s }: { s: CallState }) {
  const days = new Map<string, DaySlot[]>();
  for (const d of s.day_slots) {
    const k = slotDay(d.starts_at);
    days.set(k, [...(days.get(k) ?? []), d]);
  }
  const provider = s.providers.find((p) => p.id === s.selected);
  return (
    <Card title="Schedule" icon={<CalendarClock size={15} />} meta={provider ? provider.name : "Simulated provider schedule"}>
      {s.day_slots.length === 0 ? (
        <span className="muted">Slots for the selected doctor appear once times are offered.</span>
      ) : (
        [...days.entries()].map(([day, list]) => (
          <div key={day}>
            <div className="section-label">{day}</div>
            <ul>
              {list.map((d) => (
                <li key={d.slot_id} className={`slot ${d.state} ${d.selected ? "selected" : ""}`}>
                  <span className="slot-ico" aria-hidden="true" />
                  <span className="time">{slotTime(d.starts_at)}</span>
                  <span className="tags">
                    {d.selected && <Chip tone="teal">Chosen</Chip>}
                    {d.offered && !d.selected && <Chip tone="outline">Offered</Chip>}
                    {slotChip(d)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- handoff

const CATEGORY: Record<string, string> = {
  caller_requested: "Caller requested a person",
  knowledge_gap: "Knowledge gap",
  verification_failed: "Verification failed",
  tool_failure: "System problem",
  safety: "Safety",
  policy_required: "Policy review",
  waitlist: "Waitlist",
};

function Packet({ t, canAct, onChanged }: { t: Task; canAct: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const p = t.packet;
  const done = t.status === "completed";
  async function complete() {
    setBusy(true);
    setErr(null);
    try {
      await completeTask(t.task_id);
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not complete this handoff.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className={`packet ${done ? "done" : ""}`}>
      <div className="packet-head">
        <span className="mono" style={{ fontWeight: 650 }}>{p.reference}</span>
        <Chip tone={p.category === "safety" || p.category === "verification_failed" ? "red" : "blue"}>{CATEGORY[p.category] ?? p.category}</Chip>
        <span style={{ flex: 1 }} />
        {done ? <Chip tone="green"><Check size={12} /> Completed</Chip> : <Chip tone="amber">Open</Chip>}
      </div>
      <div className="packet-body">
        <div>
          <h4>Summary</h4>
          <p>{p.summary || <Na />}</p>
          {p.detail && <p className="muted" style={{ marginTop: 4, fontSize: 13 }}>{p.detail}</p>}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Chip tone={p.caller_verified ? "green" : "amber"}>{p.caller_verified ? "Caller verified" : "Caller not verified"}</Chip>
          {p.plan && <Chip tone="outline">{p.plan}</Chip>}
        </div>
        {p.already_tried.length > 0 && (
          <div>
            <h4>Already tried</h4>
            <ul className="tried">
              {p.already_tried.map((x, i) => (
                <li key={i}><Check size={13} strokeWidth={3} />{x}</li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <h4>Next step for the operator</h4>
          <div className="next-action"><Flag size={15} />{p.suggested_next_action || <Na />}</div>
        </div>
        {err && <InlineError>{err}</InlineError>}
      </div>
      <div className="packet-foot">
        <span className="muted" style={{ fontSize: 12 }}>{done ? `Completed ${shortClock(t.completed_at)} ET` : `Saved ${shortClock(t.created_at)} ET`}</span>
        <span style={{ flex: 1 }} />
        {!done && (
          <button className="btn primary sm" onClick={complete} disabled={busy || !canAct} title={canAct ? undefined : "Disabled in fixture mode"}>
            {busy ? <Spinner /> : <Check size={14} />} Mark complete
          </button>
        )}
      </div>
    </article>
  );
}

export function HandoffPanel({ s, canAct, onChanged }: { s: CallState; canAct: boolean; onChanged: () => void }) {
  const open = s.tasks.filter((t) => t.status === "open").length;
  return (
    <Card title="Handoff" icon={<HandHeart size={15} />} meta={s.tasks.length ? (open ? `${open} open` : "All complete") : undefined}>
      {s.tasks.length === 0 ? (
        <Empty icon={<ClipboardList size={18} />} title="No handoff needed">A packet is saved here when the call needs a person, such as a requested callback, failed verification or no open times.</Empty>
      ) : (
        s.tasks.map((t) => <Packet key={t.task_id} t={t} canAct={canAct} onChanged={onChanged} />)
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- summary

const OUTCOME: Record<SummaryOutcome, { label: string; tone: "green" | "blue" | "amber" | "red" }> = {
  booked: { label: "Booked", tone: "green" },
  followup: { label: "Follow-up needed", tone: "blue" },
  not_completed: { label: "Not completed", tone: "amber" },
  unknown: { label: "Outcome unknown", tone: "red" },
};

export function SummaryPanel({ s }: { s: CallState }) {
  const sum = s.summary;
  const openTasks = s.tasks.filter((t) => t.status === "open");
  return (
    <Card title="Call summary" icon={<ClipboardList size={15} />} meta={s.status === "finalized" ? "Built from stored records" : undefined}>
      {!sum ? (
        <span className="muted">{s.status === "live" ? "The summary is built from stored records after the call ends." : "No summary was stored for this call."}</span>
      ) : (
        <>
          <div className="summary-outcome">
            <Chip lg tone={(OUTCOME[sum.outcome] ?? OUTCOME.unknown).tone}>{(OUTCOME[sum.outcome] ?? OUTCOME.unknown).label}</Chip>
            {sum.confirmation && <Chip lg tone="outline"><span className="mono">{sum.confirmation}</span></Chip>}
          </div>
          <p className="summary-text">{sum.text}</p>
          {sum.outcome === "unknown" && (
            <div className="pending-note red"><AlertTriangle size={16} /><span>The booking result could not be confirmed. Check the schedule before telling the caller anything.</span></div>
          )}
          <dl className="kv" style={{ marginTop: 14 }}>
            <dt>First request</dt>
            <dd>{sum.reason || <Na />}</dd>
            <dt>Outstanding</dt>
            <dd>{openTasks.length ? `${openTasks.length} open handoff${openTasks.length === 1 ? "" : "s"}` : <span className="muted">None</span>}</dd>
          </dl>
          {openTasks.length > 0 && (
            <ul className="summary-list">
              {openTasks.map((t) => (
                <li key={t.task_id} className="next-action"><Phone size={15} /><span><b className="mono">{t.packet.reference}</b> · {t.packet.suggested_next_action}</span></li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
