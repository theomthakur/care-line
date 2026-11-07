import { AlertTriangle, CalendarCheck2, CalendarClock, CheckCircle2, Hourglass, PhoneCall, PhoneOff } from "lucide-react";
import type { CallState } from "../types";
import { actionNeeded, bookingPhase, narration, statusView, summaryFromState } from "../derive";
import { callStartedAt, initials, lastTurn, mmss, shortClock, shortId } from "../format";
import { Chip } from "./ui";

/**
 * The top of a case: who this is, where the call stands, what the AI is doing (or what happened),
 * whether an appointment is confirmed, and whether a person has to act. Every line is read from
 * the call's own backend state.
 */
export function CaseHeader({ s }: { s: CallState }) {
  const live = s.status === "live";
  const phase = bookingPhase(s);
  const last = lastTurn(s.turns);
  const started = callStartedAt(s);
  const st = statusView(summaryFromState(s));
  const action = actionNeeded(s);
  const name = s.member?.name ?? "Unverified caller";

  return (
    <section className="case-head" aria-label="Selected conversation">
      <div className="case-id">
        <span className={`case-avatar ${s.member ? "" : "empty"}`} aria-hidden="true">{s.member ? initials(s.member.name) : "?"}</span>
        <div className="case-title">
          <h2 title={s.call_id}>
            {name} <span className="case-num mono">#{shortId(s.call_id)}</span>
          </h2>
          <div className="case-meta">
            <span>Started <b>{started ? `${shortClock(started)} ET` : "—"}</b></span>
            <span className="sep" />
            <span>{live ? "Latest turn at" : "Length"} <b className="num">{last ? mmss(last.t) : "—"}</b></span>
            <span className="sep" />
            <span><b className="num">{s.turns.length}</b> {s.turns.length === 1 ? "message" : "messages"}</span>
          </div>
        </div>
        <span className="case-spacer" />
        <div className="case-chips">
          {live ? <Chip tone="green" lg><PhoneCall size={12} /> Active call</Chip> : <Chip lg><PhoneOff size={12} /> Call completed</Chip>}
          <Chip tone={st.tone} lg>{st.label}</Chip>
        </div>
      </div>

      <div className="case-facts">
        <div className="fact">
          <div className="fact-k">{live ? "What the AI is doing" : "What happened"}</div>
          <p className="fact-v">{narration(s)}</p>
        </div>
        <div className={`fact fact-appt ${phase}`}>
          <div className="fact-k">Appointment</div>
          <p className="fact-v">
            {s.appointment ? (
              <>
                <CheckCircle2 size={15} aria-hidden="true" /> <b>Confirmed</b> · <span className="mono">{s.appointment.confirmation}</span>
              </>
            ) : phase === "awaiting_yes" ? (
              <>
                <Hourglass size={15} aria-hidden="true" /> Awaiting the caller's yes
              </>
            ) : phase === "proposed" ? (
              <>
                <CalendarClock size={15} aria-hidden="true" /> A time is chosen, not booked
              </>
            ) : phase === "conflict" ? (
              <>
                <AlertTriangle size={15} aria-hidden="true" /> The chosen time was taken
              </>
            ) : (
              <>
                <CalendarCheck2 size={15} aria-hidden="true" /> {live ? "Not booked yet" : "Not booked"}
              </>
            )}
          </p>
        </div>
      </div>

      {action && (
        <div className="case-action" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <b>{action.title}</b>
            <span>{action.detail}</span>
          </div>
        </div>
      )}
    </section>
  );
}
