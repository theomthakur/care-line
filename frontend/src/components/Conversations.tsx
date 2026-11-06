import { memo, useEffect, useRef, useState } from "react";
import { Headset, Inbox, PhoneCall, PhoneOff, UserRoundCheck, UserRoundSearch } from "lucide-react";
import type { CallSummary } from "../types";
import { STAGE_VIEW } from "../derive";
import { duration, isRedacted, shortId, sinceLabel } from "../format";
import { Chip } from "./ui";

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

const Row = memo(function Row({ c, selected, now, onSelect }: { c: CallSummary; selected: boolean; now: number; onSelect: (id: string) => void }) {
  const live = c.status === "live";
  const stage = STAGE_VIEW[c.stage];
  const verified = c.verification === "verified" && c.member;
  const snippet = c.last_turn ? `${c.last_turn.role === "user" ? "Caller" : "Agent"}: ${isRedacted(c.last_turn.text) ? "Verification details hidden" : c.last_turn.text}` : live ? "Waiting for the first words" : "No transcript";
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-call={c.call_id}
      className={`conv ${selected ? "selected" : ""} ${live ? "live" : "done"}`}
      onClick={() => onSelect(c.call_id)}
    >
      <span className="conv-top">
        <span className={`conv-ico ${verified ? "ok" : ""}`} aria-hidden="true">
          {verified ? <UserRoundCheck size={14} /> : <UserRoundSearch size={14} />}
        </span>
        <span className="conv-name">{verified ? c.member!.name : "Unverified caller"}</span>
        {live && <span className="dot pulse conv-live" title="Live call" />}
        <span className="conv-time num">{duration(c.created_at, c.finalized_at, now)}</span>
      </span>
      <span className="conv-mid">
        <Chip tone={stage.tone}>{stage.label}</Chip>
        {c.open_tasks > 0 && (
          <Chip tone="amber" title={`${c.open_tasks} open handoff${c.open_tasks === 1 ? "" : "s"}`}>
            <Headset size={11} /> {c.open_tasks} handoff
          </Chip>
        )}
        {c.confirmation && <span className="conv-conf mono">{c.confirmation}</span>}
      </span>
      <span className="conv-snippet">{snippet}</span>
      <span className="conv-meta">
        <span className="mono">#{shortId(c.call_id)}</span>
        {verified && <span className="mono">{c.member!.id_masked}</span>}
        <span className="conv-spacer" />
        <span>{live ? sinceLabel(c.last_activity_at, now) : `ended ${sinceLabel(c.finalized_at ?? c.last_activity_at, now)}`}</span>
      </span>
    </button>
  );
});

export function Conversations({
  calls,
  selectedId,
  onSelect,
  loading,
  fixture,
  stale,
}: {
  calls: CallSummary[] | undefined;
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  fixture: boolean;
  stale: boolean;
}) {
  const now = useNow();
  const box = useRef<HTMLDivElement>(null);
  const active = (calls ?? []).filter((c) => c.status === "live");
  const recent = (calls ?? []).filter((c) => c.status !== "live");

  // Keep the selected conversation visible (matters in the horizontal rail layout).
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("button.conv.selected")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selectedId]);

  // Arrow keys move between conversations; Enter/Space (native button) opens one.
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...(box.current?.querySelectorAll<HTMLButtonElement>("button.conv") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0) return;
    e.preventDefault();
    items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
  };

  const group = (title: string, icon: React.ReactNode, list: CallSummary[], empty: string) => (
    <section className="conv-group" aria-label={title}>
      <h3 className="conv-group-h">
        {icon}
        {title}
        <span className="conv-count num">{list.length}</span>
      </h3>
      {list.length === 0 ? <p className="conv-empty">{empty}</p> : list.map((c) => <Row key={c.call_id} c={c} selected={c.call_id === selectedId} now={now} onSelect={onSelect} />)}
    </section>
  );

  return (
    <aside className={`sidebar ${stale ? "is-stale" : ""}`} aria-label="Conversations">
      <div className="sidebar-head">
        <h2>Conversations</h2>
        {fixture ? <Chip tone="amber">Fixture</Chip> : <span className="card-meta num">{active.length} live</span>}
      </div>
      <div className="conv-scroll" ref={box} role="listbox" aria-label="Calls" onKeyDown={onKey}>
        {loading && !calls ? (
          <div aria-busy="true" aria-label="Loading conversations" style={{ display: "grid", gap: 8 }}>
            {[0, 1, 2].map((i) => <div key={i} className="skel" style={{ height: 78, borderRadius: 10 }} />)}
          </div>
        ) : (
          <>
            {group("Active", <PhoneCall size={13} />, active, "No calls in progress. New calls appear here automatically.")}
            {group("Recent", <PhoneOff size={13} />, recent, "Finished calls appear here.")}
          </>
        )}
        {!loading && calls && calls.length === 0 && (
          <div className="conv-hint"><Inbox size={14} /> Nothing yet. Place a call to start.</div>
        )}
      </div>
    </aside>
  );
}
