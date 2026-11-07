import { AlertTriangle, ArrowRight, CalendarCheck2, HandHeart, Inbox, PhoneCall } from "lucide-react";
import type { ReactNode } from "react";
import type { CallSummary } from "../types";
import { attentionReason, needsAttention, statusView } from "../derive";
import { shortId, sinceLabel } from "../format";
import { Chip } from "../components/ui";

function Kpi({ icon, label, value, tone, hint }: { icon: ReactNode; label: string; value: number | string; tone?: "attn" | "live" | "ok"; hint: string }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <span className="kpi-ico" aria-hidden="true">{icon}</span>
      <div>
        <div className="kpi-v num">{value}</div>
        <div className="kpi-k">{label}</div>
        <div className="kpi-h">{hint}</div>
      </div>
    </div>
  );
}

function Item({ c, onOpen, why }: { c: CallSummary; onOpen: (id: string) => void; why?: string }) {
  const st = statusView(c);
  const now = Date.now();
  return (
    <li>
      <button type="button" className="ov-item" onClick={() => onOpen(c.call_id)}>
        <span className="ov-name">
          <b>{c.member?.name ?? "Unverified caller"}</b>
          <small>
            <span className="mono">#{shortId(c.call_id)}</span> · {c.status === "live" ? `updated ${sinceLabel(c.last_activity_at, now)}` : `ended ${sinceLabel(c.finalized_at ?? c.last_activity_at, now)}`}
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

function Block({ title, count, empty, children, icon }: { title: string; count: number; empty: string; children: ReactNode; icon: ReactNode }) {
  return (
    <section className="ov-block card" aria-label={title}>
      <header className="card-head">
        <h2>{icon}{title}</h2>
        <span className="spacer" />
        <span className="card-meta num">{count}</span>
      </header>
      {count === 0 ? <p className="ov-empty">{empty}</p> : <ul className="ov-list">{children}</ul>}
    </section>
  );
}

/** A short, calm summary of the whole floor: who is on the phone, who needs a person, what finished. */
export function Overview({ calls, loading, onOpen, onNavigate }: { calls: CallSummary[] | undefined; loading: boolean; onOpen: (id: string) => void; onNavigate: (v: "conversations" | "followups") => void }) {
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
  const recent = calls.filter((c) => c.status !== "live" && !needsAttention(c)).slice(0, 6);
  const activeNow = active.filter((c) => !needsAttention(c));

  return (
    <div className="page-wrap overview">
      <div className="page-head">
        <div>
          <div className="page-kicker">TODAY</div>
          <h2 className="page-title">Overview</h2>
          <p>Who is on the phone, what needs your team, and what finished.</p>
        </div>
        <button type="button" className="btn primary" onClick={() => onNavigate("conversations")}>
          Open conversations <ArrowRight size={14} />
        </button>
      </div>

      <div className="kpis" role="group" aria-label="Summary">
        <Kpi icon={<PhoneCall size={18} />} label="Active calls" value={active.length} tone={active.length ? "live" : undefined} hint="On the phone now" />
        <Kpi icon={<AlertTriangle size={18} />} label="Need attention" value={attention.length} tone={attention.length ? "attn" : undefined} hint="A person has to act" />
        <Kpi icon={<CalendarCheck2 size={18} />} label="Appointments booked" value={booked.length} tone={booked.length ? "ok" : undefined} hint="In recent calls" />
        <Kpi icon={<HandHeart size={18} />} label="Open follow-ups" value={openTasks} tone={openTasks ? "attn" : undefined} hint="Waiting for the team" />
      </div>

      {calls.length === 0 ? (
        <div className="ov-block card ov-none">
          <Inbox size={22} aria-hidden="true" />
          <h3>No calls yet</h3>
          <p>When a member calls, the conversation appears here and in Conversations.</p>
        </div>
      ) : (
        <div className="ov-grid">
          <Block title="Needs attention" count={attention.length} icon={<AlertTriangle size={15} />} empty="Nothing needs attention right now.">
            {attention.map((c) => <Item key={c.call_id} c={c} onOpen={onOpen} why={attentionReason(c)} />)}
          </Block>
          <Block title="Active now" count={activeNow.length} icon={<PhoneCall size={15} />} empty="No other active calls.">
            {activeNow.map((c) => <Item key={c.call_id} c={c} onOpen={onOpen} />)}
          </Block>
          <Block title="Recently completed" count={recent.length} icon={<CalendarCheck2 size={15} />} empty="Completed calls appear here.">
            {recent.map((c) => <Item key={c.call_id} c={c} onOpen={onOpen} />)}
          </Block>
        </div>
      )}
    </div>
  );
}
