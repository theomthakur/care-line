import {
  AlertTriangle,
  ArrowRight,
  CalendarCheck2,
  CheckCircle2,
  Clock3,
  ShieldCheck,
  HandHeart,
  Inbox,
  PhoneCall,
} from "lucide-react";
import type { ReactNode } from "react";
import type { CallSummary } from "../types";
import { attentionReason, needsAttention, statusView } from "../derive";
import { shortId, sinceLabel } from "../format";
import { Chip } from "../components/ui";

function memberName(c: CallSummary) {
  return c.verification === "verified" ? c.member?.name : undefined;
}

function Kpi({
  icon,
  label,
  value,
  tone,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
  tone?: "attn" | "live" | "ok";
  hint: string;
}) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <span className="kpi-ico" aria-hidden="true">
        {icon}
      </span>
      <div>
        <div className="kpi-v num">{value}</div>
        <div className="kpi-k">{label}</div>
        <div className="kpi-h">{hint}</div>
      </div>
    </div>
  );
}

function Item({
  c,
  onOpen,
  why,
  fixture,
}: {
  c: CallSummary;
  onOpen: (id: string) => void;
  why?: string;
  fixture?: boolean;
}) {
  const st = statusView(c);
  const now = Date.now();
  return (
    <li>
      <button
        type="button"
        className="ov-item"
        onClick={() => onOpen(c.call_id)}
      >
        <span className="ov-name">
          <b>{memberName(c) ?? "Unverified caller"}</b>
          <small>
            <span className="mono">#{shortId(c.call_id)}</span> ·{" "}
            {fixture
              ? "Saved example"
              : c.status === "live"
                ? `updated ${sinceLabel(c.last_activity_at, now)}`
                : `ended ${sinceLabel(c.finalized_at ?? c.last_activity_at, now)}`}
          </small>
        </span>
        <span className="ov-state">
          <Chip tone={st.tone}>{st.label}</Chip>
          {why && <small>{why}</small>}
        </span>
        <ArrowRight size={15} aria-hidden="true" />
        <span className="sr-only">Open conversation</span>
      </button>
    </li>
  );
}

function Block({
  title,
  count,
  empty,
  children,
  icon,
}: {
  title: string;
  count: number;
  empty: string;
  children: ReactNode;
  icon: ReactNode;
}) {
  return (
    <section className="ov-block card" aria-label={title}>
      <header className="card-head">
        <h2>
          {icon}
          {title}
        </h2>
        <span className="spacer" />
        <span className="card-meta num">{count}</span>
      </header>
      {count === 0 ? (
        <p className="ov-empty">{empty}</p>
      ) : (
        <ul className="ov-list">{children}</ul>
      )}
    </section>
  );
}

/** A short, calm summary of the whole floor: who is on the phone, who needs a person, what finished. */
export function Overview({
  calls,
  loading,
  onOpen,
  onNavigate,
  fixture = false,
}: {
  calls: CallSummary[] | undefined;
  loading: boolean;
  onOpen: (id: string) => void;
  onNavigate: (v: "conversations" | "followups") => void;
  fixture?: boolean;
}) {
  if (!calls) {
    return (
      <div className="page-wrap" aria-busy={loading}>
        <div className="skel" style={{ height: 96, borderRadius: 14 }} />
      </div>
    );
  }
  const active = calls.filter((c) => c.status === "live");
  const attention = calls.filter(needsAttention);
  const booked = calls.filter((c) => c.confirmation);
  const openTasks = calls.reduce((n, c) => n + c.open_tasks, 0);
  const recent = calls
    .filter((c) => c.status !== "live" && !needsAttention(c))
    .slice(0, 6);
  const activeNow = active.filter((c) => !needsAttention(c));

  return (
    <div className="page-wrap overview">
      <div className="page-head">
        <div>
          <div className="page-kicker">YOUR SUPPORT WORKSPACE</div>
          <h2 className="page-title" aria-label="Overview">
            A little clarity. A lot of care.
          </h2>
          <p>
            Your conversations, appointments and next steps. All in one place.
          </p>
        </div>
        <button
          type="button"
          className="btn primary"
          onClick={() => onNavigate("conversations")}
        >
          Open conversations <ArrowRight size={14} />
        </button>
      </div>

      <div className="kpis" role="group" aria-label="Summary">
        <Kpi
          icon={<PhoneCall size={18} />}
          label="Active calls"
          value={active.length}
          tone={active.length ? "live" : undefined}
          hint="On the phone now"
        />
        <Kpi
          icon={<AlertTriangle size={18} />}
          label="Need attention"
          value={attention.length}
          tone={attention.length ? "attn" : undefined}
          hint="A person has to act"
        />
        <Kpi
          icon={<CalendarCheck2 size={18} />}
          label="Appointments booked"
          value={booked.length}
          tone={booked.length ? "ok" : undefined}
          hint="In recent calls"
        />
        <Kpi
          icon={<HandHeart size={18} />}
          label="Open follow-ups"
          value={openTasks}
          tone={openTasks ? "attn" : undefined}
          hint="Waiting for the team"
        />
      </div>

      <div className="workspace-summary">
        <div>
          <span
            className={`summary-signal ${attention.length ? "attention" : ""}`}
          >
            <ShieldCheck size={19} />
          </span>
          <div>
            <b>
              {attention.length
                ? `${attention.length} ${attention.length === 1 ? "conversation needs" : "conversations need"} a human touch`
                : "You’re all caught up on urgent calls"}
            </b>
            <p>
              {attention.length
                ? "Review the context below and help the member take their next step."
                : "Keep an eye on active calls. We’ll surface the context when your team is needed."}
            </p>
          </div>
        </div>
        <button className="btn ghost" onClick={() => onNavigate("followups")}>
          View follow-ups <ArrowRight size={14} />
        </button>
      </div>
      {calls.length === 0 ? (
        <div className="ov-block card ov-none">
          <Inbox size={22} aria-hidden="true" />
          <h3>No calls yet</h3>
          <p>
            When a member calls, the conversation appears here and in
            Conversations.
          </p>
        </div>
      ) : (
        <div className="ov-grid">
          <Block
            title="Needs attention"
            count={attention.length}
            icon={<AlertTriangle size={15} />}
            empty="Nothing needs attention right now."
          >
            {attention.map((c) => (
              <Item
                key={c.call_id}
                c={c}
                fixture={fixture}
                onOpen={onOpen}
                why={attentionReason(c)}
              />
            ))}
          </Block>
          <Block
            title="Active now"
            count={activeNow.length}
            icon={<PhoneCall size={15} />}
            empty="No other active calls."
          >
            {activeNow.map((c) => (
              <Item key={c.call_id} c={c} fixture={fixture} onOpen={onOpen} />
            ))}
          </Block>
          <Block
            title="Recently completed"
            count={recent.length}
            icon={<CalendarCheck2 size={15} />}
            empty="Completed calls appear here."
          >
            {recent.map((c) => (
              <Item key={c.call_id} c={c} fixture={fixture} onOpen={onOpen} />
            ))}
          </Block>
        </div>
      )}
      {calls.length > 0 && (
        <section
          className="recent-table card"
          aria-label="Conversation directory"
        >
          <header className="card-head">
            <h2>
              <Clock3 size={16} /> Conversation directory
            </h2>
            <span className="spacer" />
            <button
              className="btn ghost sm"
              onClick={() => onNavigate("conversations")}
            >
              View all <ArrowRight size={13} />
            </button>
          </header>
          <div
            className="table-scroll"
            role="region"
            aria-label="Conversation table"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>MEMBER</th>
                  <th>STATUS</th>
                  <th>APPOINTMENT</th>
                  <th>FOLLOW-UPS</th>
                  <th>
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {calls.slice(0, 8).map((c) => (
                  <tr key={c.call_id}>
                    <td>
                      <button
                        className="directory-member"
                        onClick={() => onOpen(c.call_id)}
                      >
                        <span className="directory-avatar">
                          {(memberName(c) ?? "Unknown")
                            .split(" ")
                            .map((n) => n[0])
                            .slice(0, 2)
                            .join("")}
                        </span>
                        <span>
                          <b>{memberName(c) ?? "Unverified caller"}</b>
                          <small>#{shortId(c.call_id)}</small>
                        </span>
                      </button>
                    </td>
                    <td>
                      <Chip tone={statusView(c).tone}>
                        {statusView(c).label}
                      </Chip>
                    </td>
                    <td>
                      {c.confirmation ? (
                        <span className="directory-booked">
                          <CheckCircle2 size={14} /> Confirmed
                        </span>
                      ) : (
                        <span className="muted">Not booked</span>
                      )}
                    </td>
                    <td>
                      {c.open_tasks ? (
                        <span className="directory-tasks">
                          {c.open_tasks} open
                        </span>
                      ) : (
                        <span className="muted">No open tasks</span>
                      )}
                    </td>
                    <td>
                      <button
                        className="btn ghost sm"
                        onClick={() => onOpen(c.call_id)}
                        aria-label={`Open ${memberName(c) ?? "unverified caller"} conversation`}
                      >
                        <ArrowRight size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="directory-footer">
            Showing {Math.min(calls.length, 8)} of {calls.length} conversations
            <span>Only verified member names are shown.</span>
          </footer>
        </section>
      )}
    </div>
  );
}
