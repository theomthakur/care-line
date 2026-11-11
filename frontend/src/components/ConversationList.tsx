import { memo, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Inbox, PhoneCall, PhoneOff, Search, UserRoundCheck, UserRoundSearch, X } from "lucide-react";
import type { CallSummary } from "../types";
import { attentionReason, needsAttention, statusView } from "../derive";
import { duration, shortId, sinceLabel } from "../format";
import { Chip } from "./ui";

type Filter = "all" | "active" | "attention" | "recent";

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

/**
 * One row. It deliberately shows no transcript text and no member number: only who (name once
 * verified), where the call stands, and whether a person has to act.
 */
const Row = memo(function Row({ c, selected, now, fixture, onSelect }: { c: CallSummary; selected: boolean; now: number; fixture: boolean; onSelect: (id: string) => void }) {
  const live = c.status === "live";
  const st = statusView(c);
  const attention = needsAttention(c);
  const verified = c.verification === "verified" && c.member;
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-call={c.call_id}
      className={`conv ${selected ? "selected" : ""} ${live ? "live" : "done"} ${attention ? "attn" : ""}`}
      onClick={() => onSelect(c.call_id)}
    >
      <span className="conv-top">
        <span className={`conv-ico ${verified ? "ok" : ""}`} aria-hidden="true">
          {verified ? <UserRoundCheck size={14} /> : <UserRoundSearch size={14} />}
        </span>
        <span className="conv-name">{verified ? c.member!.name : "Unverified caller"}</span>
        {live && <span className="dot pulse conv-live" title="Active call" />}
        <span className="conv-time num">{fixture ? "Sample" : duration(c.created_at, c.finalized_at, now)}</span>
      </span>
      <span className="conv-mid">
        <Chip tone={st.tone}>{st.label}</Chip>
        {attention && (
          <Chip tone="amber" title={attentionReason(c)}>
            <AlertTriangle size={11} /> Action needed
          </Chip>
        )}
      </span>
      <span className="conv-meta">
        <span className="mono" title={c.call_id}>#{shortId(c.call_id)}</span>
        {c.confirmation && <span className="mono conv-conf">{c.confirmation}</span>}
        <span className="conv-spacer" />
        <span>{fixture ? "Saved example" : live ? `updated ${sinceLabel(c.last_activity_at, now)}` : `ended ${sinceLabel(c.finalized_at ?? c.last_activity_at, now)}`}</span>
      </span>
    </button>
  );
});

function matches(c: CallSummary, q: string): boolean {
  if (!q) return true;
  const hay = [c.member?.name, statusView(c).label, shortId(c.call_id), c.call_id, c.confirmation, c.status === "live" ? "active" : "completed", needsAttention(c) ? "needs attention action" : ""]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
}

export function ConversationList({
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
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const all = calls ?? [];
  const found = useMemo(() => all.filter((c) => matches(c, query.trim())), [all, query]);
  const live = all.filter((c) => c.status === "live").length;
  const attn = all.filter(needsAttention).length;
  const done = all.length - live;

  const sections = useMemo(() => {
    const isAttn = found.filter(needsAttention);
    if (filter === "active") return [{ key: "Active", icon: <PhoneCall size={13} />, list: found.filter((c) => c.status === "live"), empty: "No active calls. New calls appear here automatically." }];
    if (filter === "attention") return [{ key: "Needs attention", icon: <AlertTriangle size={13} />, list: isAttn, empty: "Nothing needs attention right now." }];
    if (filter === "recent") return [{ key: "Recent", icon: <PhoneOff size={13} />, list: found.filter((c) => c.status !== "live"), empty: "Completed calls appear here." }];
    // All: every call appears once. Calls a person must act on rise to the top.
    return [
      ...(isAttn.length ? [{ key: "Needs attention", icon: <AlertTriangle size={13} />, list: isAttn, empty: "" }] : []),
      { key: "Active", icon: <PhoneCall size={13} />, list: found.filter((c) => c.status === "live" && !needsAttention(c)), empty: "No other active calls. New calls appear here automatically." },
      { key: "Recent", icon: <PhoneOff size={13} />, list: found.filter((c) => c.status !== "live" && !needsAttention(c)), empty: "Completed calls appear here." },
    ];
  }, [found, filter]);

  useEffect(() => {
    box.current?.querySelector<HTMLElement>("button.conv.selected")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selectedId]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...(box.current?.querySelectorAll<HTMLButtonElement>("button.conv") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0) return;
    e.preventDefault();
    items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
  };

  const tab = (f: Filter, label: string, n: number) => (
    <button key={f} type="button" role="tab" aria-selected={filter === f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
      {label} <span className="num">{n}</span>
    </button>
  );

  return (
    <aside className={`sidebar ${stale ? "is-stale" : ""}`} aria-label="Conversations">
      <div className="sidebar-head">
        <h2>Conversations</h2>
        {fixture ? <Chip tone="outline">Sample</Chip> : <span className="card-meta num">{live} active</span>}
      </div>
      <div className="conv-search">
        <Search size={14} aria-hidden="true" />
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name, call, or booking" aria-label="Search conversations" />
        {query && (
          <button type="button" aria-label="Clear search" onClick={() => setQuery("")}>
            <X size={13} />
          </button>
        )}
      </div>
      <div className="conv-tabs" role="tablist" aria-label="Filter conversations">
        {tab("all", "All", all.length)}
        {tab("active", "Active", live)}
        {tab("attention", "Needs attention", attn)}
        {tab("recent", "Recent", done)}
      </div>
      <div className="conv-scroll" ref={box} role="listbox" aria-label="Calls" onKeyDown={onKey}>
        {loading && !calls ? (
          <div aria-busy="true" aria-label="Loading conversations" style={{ display: "grid", gap: 8 }}>
            {[0, 1, 2].map((i) => <div key={i} className="skel" style={{ height: 74, borderRadius: 10 }} />)}
          </div>
        ) : (
          sections.map((sec) => (
            <section className="conv-group" aria-label={sec.key} key={sec.key}>
              <h3 className="conv-group-h">
                {sec.icon}
                {sec.key}
                <span className="conv-count num">{sec.list.length}</span>
              </h3>
              {sec.list.length === 0 ? (
                <p className="conv-empty">{query ? "No conversations match your search." : sec.empty}</p>
              ) : (
                sec.list.map((c) => <Row key={c.call_id} c={c} selected={c.call_id === selectedId} now={now} fixture={fixture} onSelect={onSelect} />)
              )}
            </section>
          ))
        )}
        {!loading && calls && calls.length === 0 && (
          <div className="conv-hint"><Inbox size={14} /> Nothing yet. Place a call to start.</div>
        )}
      </div>
    </aside>
  );
}
