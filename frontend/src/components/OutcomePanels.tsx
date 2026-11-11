import { useEffect, useRef, useState, type ReactNode } from "react";
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
  UserRound,

  Hourglass,
  X,
} from "lucide-react";
import { ApiError, completeTask } from "../api";
import { bookingPhase, eventView, progress } from "../derive";
import { shortClock, slotDay, slotTime } from "../format";
import type { CallState, DaySlot, SummaryDetails, Task } from "../types";
import { Card, Chip, InlineError, Na, Spinner } from "./ui";

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
    <section className={`card booking appointment-card ${phase}`} aria-label="Appointment outcome">
      <div className="booking-top">
        <span className="appointment-heading-icon"><CalendarCheck2 size={17} /></span>
        <h2>Appointment</h2>
        <span style={{ flex: 1 }} />
        {phase === "confirmed" && <Chip tone="green">Confirmed</Chip>}
        {phase === "awaiting_yes" && <Chip tone="amber"><Hourglass size={12} /> Awaiting caller's yes</Chip>}
        {phase === "proposed" && <Chip tone="blue">Proposed · not booked</Chip>}
        {phase === "conflict" && <Chip tone="red"><AlertTriangle size={12} /> Slot taken</Chip>}
        {phase === "none" && <Chip>{s.status === "finalized" ? "Not booked" : "No appointment yet"}</Chip>}
      </div>
      <div className="booking-state">


        {a ? (
          <div className="appointment-details">
            <div className="appointment-outcome"><span className="appointment-seal"><Check size={20} strokeWidth={2}/></span><div><h3>Appointment confirmed</h3><p>{a.simulated ? "Saved to the demo schedule" : "Saved to the provider schedule"}</p></div></div>
            <div className="appointment-when"><span className="appointment-detail-icon"><CalendarClock size={18}/></span><div><span className="appointment-label">DATE & TIME</span><p>{a.when}</p></div></div>
            <div className="appointment-provider"><span className="appointment-detail-icon"><UserRound size={18}/></span><div><span className="appointment-label">YOUR PROVIDER</span><p>{a.doctor}</p><span className="appointment-phone"><Phone size={11}/>{a.phone}</span></div></div>
            <div className="appointment-reference"><div><span className="appointment-label">CONFIRMATION NUMBER</span><div className="confirm-num" aria-label={`Confirmation ${a.confirmation}`}>{a.confirmation}</div></div><CheckCircle2 size={17} aria-hidden="true"/></div>
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
        <div className="appointment-workflow"><div className="appointment-label">BOOKING CHECKLIST</div>
        <div className="progress" role="list" aria-label="Booking progress">
          {segs.map((g) => (
            <div key={g.key} role="listitem" className={`seg ${g.state}`} aria-label={`${g.label}: ${g.state === "done" ? "complete" : g.state === "current" ? "in progress" : g.state === "failed" ? "failed" : "not started"}`}>
              <span className="step-marker" aria-hidden="true">{g.state === "done" ? <Check size={10} strokeWidth={2.5}/> : <span/>}</span>
              {g.label}
            </div>
          ))}
        </div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- timeline

export function ActivityTimeline({ s, developer = false }: { s: CallState; developer?: boolean }) {
  return (
    <Card title="Call timeline" icon={<History size={15} />} collapsible defaultOpen={false} meta={s.events.length ? `${s.events.length} steps` : undefined}>
      {s.events.length === 0 ? (
        <span className="muted">Steps appear here in order as the call goes on.</span>
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
                  {developer && <div className="tl-sub mono">{name}</div>}
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
  const box = useRef<HTMLDivElement>(null);
  const focusId = s.day_slots.find((d) => d.selected)?.slot_id ?? s.day_slots.find((d) => d.offered)?.slot_id;
  // Long days scroll inside the card; bring the chosen or first offered time into view when it changes.
  useEffect(() => {
    const el = focusId ? box.current?.querySelector<HTMLElement>(`[data-slot="${focusId}"]`) : null;
    if (el && box.current) box.current.scrollTop = Math.max(0, el.offsetTop - 56);
  }, [focusId]);
  return (
    <Card title="Doctor schedule" icon={<CalendarClock size={15} />} collapsible defaultOpen={false} meta={provider ? provider.name : "Simulated provider schedule"}>
      <div ref={box} className="slot-scroll">
      {s.day_slots.length === 0 ? (
        <span className="muted">Slots for the selected doctor appear once times are offered.</span>
      ) : (
        [...days.entries()].map(([day, list]) => (
          <div key={day}>
            <div className="section-label">{day}</div>
            <ul>
              {list.map((d) => (
                <li key={d.slot_id} data-slot={d.slot_id} className={`slot ${d.state} ${d.selected ? "selected" : ""}`}>
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
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- handoff

export const CATEGORY: Record<string, string> = {
  caller_requested: "Caller asked for a person",
  knowledge_gap: "Question to answer",
  verification_failed: "Verification failed",
  tool_failure: "System problem",
  safety: "Safety concern",
  policy_required: "Needs policy review",
  waitlist: "No open times",
};

export function Packet({ t, canAct, onChanged, extra }: { t: Task; canAct: boolean; onChanged: () => void; extra?: ReactNode }) {
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
        {extra}
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
    <Card title="Follow-ups for the team" icon={<HandHeart size={15} />} meta={s.tasks.length ? (open ? `${open} open` : "All complete") : undefined}>
      {s.tasks.length === 0 ? (
        <span className="muted">No follow-up needed. A request is saved here when the call needs a person: a requested callback, failed verification or no open times.</span>
      ) : (
        s.tasks.map((t) => <Packet key={t.task_id} t={t} canAct={canAct} onChanged={onChanged} />)
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- summary

const OUTCOME_TONE = { booked: "green", followup: "amber", not_completed: "slate", unknown: "red" } as const;

const VERIFICATION: Record<SummaryDetails["verification"], { label: string; tone: "green" | "red" | "amber" | "slate" }> = {
  verified: { label: "Member verified", tone: "green" },
  failed: { label: "Verification failed", tone: "red" },
  locked: { label: "Verification locked", tone: "red" },
  not_attempted: { label: "Not attempted", tone: "slate" },
};

function outcomeLabel(outcome: string, details?: SummaryDetails | null): string {
  if (outcome === "booked") return "Appointment booked";
  if (outcome === "followup") return details && details.follow_ups.length && details.follow_ups.every((f) => f.status === "completed") ? "Follow-up completed" : "Needs follow-up";
  if (outcome === "not_completed") return "Ended without booking";
  return "Needs review";
}

/** The post-call summary. Everything is read from saved records; nothing is written by a model. */
export function SummaryPanel({ s, details }: { s: CallState; details?: SummaryDetails | null }) {
  const sum = s.summary;
  const live = s.status === "live";
  if (live && !sum) {
    return (
      <Card title="Call summary" icon={<ClipboardList size={15} />} meta="After the call ends">
        <span className="muted">A summary is put together from the saved call record when the call ends. Until then, follow the case on this page.</span>
      </Card>
    );
  }
  const verification = details ? VERIFICATION[details.verification] : null;
  const appt = details?.appointment;
  return (
    <Card title="Call summary" icon={<ClipboardList size={15} />} meta="Built from saved records" label="Call summary">
      {sum ? (
        <>
          <div className="summary-outcome">
            <Chip lg tone={OUTCOME_TONE[sum.outcome] ?? "red"}>{outcomeLabel(sum.outcome, details)}</Chip>
            {(appt?.confirmation ?? sum.confirmation) && <Chip lg tone="outline"><span className="mono">{appt?.confirmation ?? sum.confirmation}</span></Chip>}
          </div>
          <p className="summary-text">{sum.text}</p>
          {sum.outcome === "unknown" && (
            <div className="pending-note red"><AlertTriangle size={16} /><span>The booking result could not be confirmed. Check the schedule before telling the caller anything.</span></div>
          )}
          {sum.ended_reason === "dropped" && (
            <div className="pending-note neutral"><Phone size={16} /><span>The call ended without a normal hang-up. This summary was put together from what was saved during the call.</span></div>
          )}
        </>
      ) : (
        <span className="muted">No outcome was stored for this call.</span>
      )}
      <dl className="kv summary-kv">
        <dt>Verification</dt>
        <dd>{verification ? <Chip tone={verification.tone}>{verification.label}</Chip> : <Na>Loading…</Na>}</dd>
        <dt>Original request</dt>
        <dd>{sum?.reason || <Na />}</dd>
        <dt>Provider</dt>
        <dd>{details ? details.provider ? <>{details.provider.name}{details.provider.phone ? <span className="muted num"> · {details.provider.phone}</span> : null}</> : <span className="muted">None chosen</span> : <Na>Loading…</Na>}</dd>
        <dt>Appointment</dt>
        <dd>{details ? appt ? <>{appt.when}</> : <span className="muted">No appointment booked</span> : <Na>Loading…</Na>}</dd>
        <dt>Problems</dt>
        <dd>
          {details ? (
            details.problems.length ? (
              <ul className="plain-list">{details.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
            ) : (
              <span className="muted">None</span>
            )
          ) : (
            <Na>Loading…</Na>
          )}
        </dd>
        <dt>Follow-ups</dt>
        <dd>
          {details ? (
            details.follow_ups.length ? (
              <ul className="plain-list">
                {details.follow_ups.map((f) => (
                  <li key={f.reference}>
                    <b className="mono">{f.reference}</b> · {f.status === "open" ? <span className="open-tag">Open</span> : <span className="muted">Completed</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="muted">None</span>
            )
          ) : (
            <Na>Loading…</Na>
          )}
        </dd>
      </dl>
      {details?.next_action && (
        <div className="next-step">
          <h4>Next step</h4>
          <div className="next-action"><Flag size={15} />{details.next_action}</div>
        </div>
      )}
    </Card>
  );
}
