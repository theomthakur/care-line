import { useMemo, useState } from "react";
import { ArrowRight, CheckCheck, HandHeart } from "lucide-react";
import { getTasks } from "../api";
import { usePoll } from "../usePolling";
import type { CallSummary } from "../types";
import { Packet } from "../components/OutcomePanels";
import { Chip } from "../components/ui";

type F = "open" | "completed" | "all";

/** Every follow-up the AI saved for the team, across all calls. Completing one marks only that task. */
export function FollowUps({ calls, onOpenCall, canAct, onChanged }: { calls: CallSummary[] | undefined; onOpenCall: (id: string) => void; canAct: boolean; onChanged: () => void }) {
  const tasks = usePoll((signal) => getTasks(undefined, signal), "tasks", 2000, true);
  const [filter, setFilter] = useState<F>("open");
  const names = useMemo(() => new Map((calls ?? []).map((c) => [c.call_id, c.member?.name ?? null])), [calls]);

  const all = tasks.data ?? [];
  const open = all.filter((t) => t.status === "open").length;
  const shown = all
    .filter((t) => filter === "all" || t.status === filter)
    .sort((a, b) => (a.status === b.status ? b.created_at.localeCompare(a.created_at) : a.status === "open" ? -1 : 1));

  const seg = (f: F, label: string, n: number) => (
    <button key={f} type="button" role="radio" aria-checked={filter === f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
      {label} <span className="num">{n}</span>
    </button>
  );

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-kicker">FOR THE TEAM</div>
          <h2 className="page-title">Follow-ups</h2>
          <p>Requests the AI saved because a person needs to help. Mark one complete when you have handled it.</p>
        </div>
        <div className="seg-control" role="radiogroup" aria-label="Show follow-ups">
          {seg("open", "Open", open)}
          {seg("completed", "Completed", all.length - open)}
          {seg("all", "All", all.length)}
        </div>
      </div>

      {tasks.data === undefined ? (
        tasks.error ? <p className="ov-empty" role="alert">The follow-up list could not be loaded. {tasks.error.message}</p> : <div className="skel" style={{ height: 120, borderRadius: 14 }} />
      ) : shown.length === 0 ? (
        <div className="ov-block card ov-none">
          <HandHeart size={22} aria-hidden="true" />
          <h3>{filter === "open" ? "No open follow-ups" : "Nothing here yet"}</h3>
          <p>{filter === "open" ? "Everything the AI could not finish has been handled." : "Follow-ups appear here when a call needs a person."}</p>
        </div>
      ) : (
        <ul className="fu-list">
          {shown.map((t) => {
            const who = names.get(t.call_id);
            return (
              <li key={t.task_id}>
                <div className="fu-who">
                  <b>{who ?? "Caller"}</b>
                  {!who && <Chip>Not verified or older call</Chip>}
                </div>
                <Packet
                  t={t}
                  canAct={canAct}
                  onChanged={() => {
                    tasks.refresh();
                    onChanged();
                  }}
                  extra={
                    <button type="button" className="btn sm ghost" onClick={() => onOpenCall(t.call_id)}>
                      Open conversation <ArrowRight size={13} />
                    </button>
                  }
                />
              </li>
            );
          })}
        </ul>
      )}
      {tasks.data !== undefined && open === 0 && all.length > 0 && filter === "open" && (
        <p className="fu-clear"><CheckCheck size={14} /> All follow-ups are complete.</p>
      )}
    </div>
  );
}
