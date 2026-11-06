import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { CloudOff, FlaskConical, MessageSquare, PhoneCall, PhoneOff, RefreshCw, SearchX, WifiOff } from "lucide-react";
import { getCallHistory, getCallState, getCalls, type CallListItem } from "./api";
import { Providers } from "./Providers";
import { ProductShell, History, Architecture, Deck, Developer, type Section } from "./ProductShell";
import { ago, callStartedAt, lastTurn, mmss, shortClock, shortId } from "./format";
import { FIXTURE_STAGES } from "./fixtures";
import { usePoll, type Connection } from "./usePolling";
import { summaryFromState } from "./derive";
import { Conversations } from "./components/Conversations";
import type { CallState } from "./types";
import { Transcript } from "./components/Transcript";
import { EvidencePanel, MemberPanel, ProviderPanel, RequestPanel } from "./components/ContextPanels";
import { ActivityTimeline, BookingCard, HandoffPanel, SlotList, SummaryPanel } from "./components/OutcomePanels";
import { DemoControls, DemoMemberCard } from "./components/DemoControls";
import { Card, Chip, SkeletonLines } from "./components/ui";

const isFixture = new URLSearchParams(window.location.search).get("source") === "fixture";

function useTick(ms: number) {
  const [, set] = useState(0);
  useEffect(() => {
    const id = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
}

function ConnectionBadge({ connection, lastOk, fixture, onRetry }: { connection: Connection; lastOk: number | null; fixture: boolean; onRetry: () => void }) {
  useTick(1000);
  if (fixture) return <Chip tone="amber" lg><FlaskConical size={12} /> Fixture data</Chip>;
  if (connection === "loading") return <Chip lg><span className="spinner" style={{ width: 11, height: 11, borderWidth: 1.5 }} /> Connecting</Chip>;
  if (connection === "connected") return <Chip tone="green" lg title={lastOk ? `Updated ${shortClock(new Date(lastOk).toISOString())}` : undefined}><span className="dot pulse" /> Connected</Chip>;
  return (
    <button className="chip lg red" style={{ cursor: "pointer", border: 0 }} onClick={onRetry} title="Retry now">
      <WifiOff size={12} /> {connection === "stale" ? "Reconnecting" : "Disconnected"}
      {lastOk ? ` · last data ${ago(Date.now() - lastOk)}` : ""}
    </button>
  );
}

function Skeleton() {
  return (
    <div className="workspace" aria-busy="true" aria-label="Loading">
      {[0, 1, 2].map((c) => (
        <div className="col" key={c}>
          {[0, 1, 2].slice(0, c === 0 ? 1 : 3).map((i) => (
            <Card key={i} title={<span className="skel" style={{ display: "inline-block", width: 96, height: 12 }} />} bodyClass="card-body">
              <SkeletonLines rows={c === 0 ? 7 : 4} />
            </Card>
          ))}
        </div>
      ))}
    </div>
  );
}

function Idle() {
  return (
    <div className="hero">
      <div className="hero-inner">
        <div className="halo"><PhoneCall size={32} strokeWidth={1.75} /></div>
        <div>
          <h2>Waiting for the next call</h2>
          <p>The console follows the latest call from the moment it connects: the transcript, who the caller is, which doctors were offered and why, and what was actually booked.</p>
        </div>
        <DemoMemberCard />
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>Hand this card to the caller. It is a printed synthetic card, not a verified state.</p>
      </div>
    </div>
  );
}

function Unreachable({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="hero">
      <div className="hero-inner">
        <div className="halo" style={{ background: "var(--red-50)", color: "var(--red-700)", boxShadow: "inset 0 0 0 1px var(--red-100), 0 0 0 10px rgba(163,40,28,.05)" }}><CloudOff size={32} strokeWidth={1.75} /></div>
        <div>
          <h2>Can't reach the backend</h2>
          <p>{error} Nothing on this screen is a guess: the console shows backend state only, so it shows nothing until the connection is back.</p>
        </div>
        <div className="card" style={{ padding: "10px 14px", textAlign: "left", maxWidth: "100%" }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Start the local backend</div>
          <code className="mono" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>uv run uvicorn backend.ops.dev_app:app --port 8000</code>
        </div>
        <button className="btn primary" onClick={onRetry}><RefreshCw size={14} /> Retry now</button>
      </div>
    </div>
  );
}

function CallBar({ s }: { s: CallState }) {
  const live = s.status === "live";
  const last = lastTurn(s.turns);
  const started = callStartedAt(s);
  return (
    <div className="callbar">
      <div className="callbar-title">
        <h1 title={s.call_id}>Call <span className="mono">#{shortId(s.call_id)}</span></h1>
        {live ? <Chip tone="green" lg><span className="dot pulse" /> Live</Chip> : <Chip lg><PhoneOff size={12} /> Ended</Chip>}
      </div>
      <div className="callbar-meta">
        <span>Started <b>{started ? `${shortClock(started)} ET` : "—"}</b></span>
        <span className="sep" />
        <span>{live ? "Latest turn at" : "Length"} <b className="num">{last ? mmss(last.t) : "—"}</b></span>
        <span className="sep" />
        <span><b className="num">{s.turns.length}</b> {s.turns.length === 1 ? "turn" : "turns"}</span>
      </div>
      <span className="callbar-spacer" />
      <Chip tone="outline">Synthetic demo data</Chip>
      <Chip tone="outline">Simulated provider schedule</Chip>
    </div>
  );
}

export type Tab = "calls" | "call" | "context" | "outcome";

const Workspace = memo(function Workspace({ s, tab, canAct, onChanged, stale }: { s: CallState; tab: Tab; canAct: boolean; onChanged: () => void; stale: boolean }) {
  const cls = (t: Tab) => (tab === t ? "active" : "");
  const live = s.status === "live";
  return (
    <main className={`workspace ${stale ? "is-stale" : ""}`}>
      <div className={`col col-fill col-call ${cls("call")}`}>
        <Card className="fill" title="Conversation" icon={<MessageSquare size={15} />} meta={live ? <Chip tone="green"><span className="dot" /> Updating live</Chip> : "Final transcript"} bodyClass="card-body" label="Conversation">
          <Transcript turns={s.turns} live={live} callId={s.call_id} />
        </Card>
      </div>
      <div className={`col col-context ${cls("context")}`}>
        <MemberPanel s={s} />
        <RequestPanel s={s} />
        <ProviderPanel s={s} />
        <EvidencePanel s={s} />
      </div>
      <div className={`col col-outcome ${cls("outcome")}`}>
        <div className="span-all"><BookingCard s={s} /></div>
        {s.tasks.length > 0 && <div className="span-all"><HandoffPanel s={s} canAct={canAct} onChanged={onChanged} /></div>}
        <SummaryPanel s={s} />
        {s.tasks.length === 0 && <HandoffPanel s={s} canAct={canAct} onChanged={onChanged} />}
        {/* Kept near the top: the presenter taps this mid-call, so it must not sit below the fold. */}
        <div className="span-all"><DemoControls s={s} canAct={canAct} onChanged={onChanged} /></div>
        <SlotList s={s} />
        <ActivityTimeline s={s} />
      </div>
    </main>
  );
});

function NotFound({ onBack, hasCalls }: { onBack: () => void; hasCalls: boolean }) {
  return (
    <div className="hero">
      <div className="hero-inner">
        <div className="halo"><SearchX size={30} strokeWidth={1.75} /></div>
        <div>
          <h2>This call is no longer available</h2>
          <p>The backend has no record of it. This usually means the demo was reset. Nothing from another call is shown in its place.</p>
        </div>
        {hasCalls && <button className="btn primary" onClick={onBack}>Open the latest conversation</button>}
      </div>
    </div>
  );
}

function hashId(): string | null {
  const m = /[#&]call=([^&]+)/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]) : null;
}

export function App() {
  const [stage, setStage] = useState("booked");
  const fixtureStage = useMemo(() => FIXTURE_STAGES.find((f) => f.key === stage) ?? FIXTURE_STAGES[0], [stage]);
  const [selectedId, setSelectedId] = useState<string | null>(() => (isFixture ? null : hashId()));
  const [tab, setTab] = useState<Tab>("call");
  const [section, setSection] = useState<Section>("workspace");
  const [developer, setDeveloper] = useState(() => localStorage.getItem("careline-developer") === "on");
  const [history, setHistory] = useState<CallListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  useEffect(() => {
    localStorage.setItem("careline-developer", developer ? "on" : "off");
    if (!developer && section === "developer") setSection("workspace");
  }, [developer, section]);
  // Call history page (read-only list). Opening a call there selects it in the live workspace.
  useEffect(() => {
    if (section !== "history" || isFixture) return;
    let active = true;
    const load = async () => {
      try { const items = await getCallHistory(); if (active) { setHistory(items); setHistoryError(""); } }
      catch { if (active) setHistoryError("Check the backend connection and try again."); }
      finally { if (active) setHistoryLoading(false); }
    };
    setHistoryLoading(true);
    void load();
    const id = setInterval(load, 5000);
    return () => { active = false; clearInterval(id); };
  }, [section]);

  // Two independent 1 s polls: the call list, and the ONE selected call's full state.
  const list = usePoll(getCalls, "calls", 1000, !isFixture);
  const detail = usePoll((signal) => getCallState(selectedId!, signal), selectedId ? `call:${selectedId}` : null, 1000, !isFixture);

  const calls = isFixture ? (fixtureStage.state ? [summaryFromState(fixtureStage.state)] : []) : list.data;
  const effectiveId = isFixture ? (fixtureStage.state?.call_id ?? null) : selectedId;

  const select = useCallback((id: string) => {
    setSelectedId(id);
    setTab("call");
    if (!isFixture) window.history.replaceState(null, "", `#call=${encodeURIComponent(id)}`);
  }, []);

  // Pick a call ONCE, only while nothing is selected: the most recent live call, else the most
  // recently finished one. After that new calls never move the selection.
  useEffect(() => {
    if (isFixture || selectedId || !list.data || list.data.length === 0) return;
    select((list.data.find((c) => c.status === "live") ?? list.data[0]).call_id);
  }, [selectedId, list.data, select]);

  useEffect(() => {
    const sync = () => setSelectedId(hashId());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const state = isFixture ? fixtureStage.state : detail.data ?? null;
  const gone = !isFixture && selectedId !== null && detail.data === null;
  const loadingDetail = !isFixture && selectedId !== null && detail.data === undefined;
  const lastOk = selectedId ? detail.lastOk : list.lastOk;
  const worst = (a: Connection, b: Connection): Connection => (a === "disconnected" || b === "disconnected" ? "disconnected" : a === "stale" || b === "stale" ? "stale" : a);
  const link: Connection = isFixture ? "connected" : selectedId ? worst(detail.connection, list.connection) : list.connection;
  const down = !isFixture && (link === "stale" || link === "disconnected");
  const refresh = useCallback(() => {
    list.refresh();
    detail.refresh();
  }, [list.refresh, detail.refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  const error = detail.error ?? list.error;
  const canAct = !isFixture;
  const noCalls = !isFixture && list.data !== undefined && list.data.length === 0 && !selectedId;

  let body;
  if (!isFixture && link === "loading" && !state && !calls) body = <Skeleton />;
  else if (!isFixture && down && !state && !calls) body = <Unreachable error={error?.message ?? "The backend did not answer."} onRetry={refresh} />;
  else if (gone) body = <NotFound hasCalls={!!calls?.length} onBack={() => { window.history.replaceState(null, "", window.location.pathname); setSelectedId(null); }} />;
  else if (noCalls || (!state && !loadingDetail && !effectiveId)) body = <Idle />;
  else if (!state) body = <Skeleton />;
  else
    body = (
      <>
        <CallBar s={state} />
        <Workspace key={state.call_id} s={state} tab={tab} canAct={canAct} onChanged={refresh} stale={down} />
      </>
    );

  const crumb = section === "workspace" ? "Live workspace" : section === "history" ? "Call history" : section === "providers" ? "Providers" : section === "architecture" ? "System design" : section === "presentation" ? "Presentation" : "Developer view";
  const openCall = (id: string) => { select(id); setSection("workspace"); };

  return (
    <ProductShell section={section} setSection={setSection} developer={developer} setDeveloper={setDeveloper}>
    <div className="app">
      <header className="topbar">
        <span className="crumb">Workspace / {crumb}</span>
        <span className="topbar-spacer" />
        <div className="topbar-right">
          <ConnectionBadge connection={link} lastOk={lastOk} fixture={isFixture} onRetry={refresh} />
        </div>
      </header>

      {section === "providers" ? <Providers /> : section === "history" ? <History calls={history} loading={historyLoading} error={historyError} onSelect={openCall} /> : section === "architecture" ? <Architecture /> : section === "presentation" ? <Deck /> : section === "developer" ? <Developer state={state} /> : <>
      {isFixture && (
        <div className="fixture-bar" role="region" aria-label="Fixture mode">
          <b>Fixture mode · not a live call</b>
          <span style={{ color: "var(--ink-300)" }}>Showing a saved example from contracts/examples. Actions are disabled.</span>
          <div className="stages">
            {FIXTURE_STAGES.map((f) => (
              <button key={f.key} aria-pressed={stage === f.key} onClick={() => setStage(f.key)}>{f.label}</button>
            ))}
          </div>
        </div>
      )}

      {down && (state || calls) && (
        <div className="notice error" role="alert">
          <WifiOff size={15} />
          <span className="grow">
            {link === "disconnected" ? "Backend disconnected." : "Connection interrupted."} Showing the last data received{lastOk ? ` at ${shortClock(new Date(lastOk).toISOString())} ET` : ""}. Nothing below is updating, and the selected call has not changed.
          </span>
          <button onClick={refresh}>Retry now</button>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Sections">
        {(["calls", "call", "context", "outcome"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t === "calls" ? `Calls${calls?.filter((c) => c.status === "live").length ? ` · ${calls.filter((c) => c.status === "live").length}` : ""}` : t === "call" ? "Call" : t === "context" ? "Context" : "Outcome"}
          </button>
        ))}
      </div>

      <div className={`shell tab-${tab}`}>
        <Conversations calls={calls} selectedId={effectiveId} onSelect={select} loading={!isFixture && list.data === undefined && link === "loading"} fixture={isFixture} stale={down} />
        <div className="shell-main">{body}</div>
      </div>
      </>}
    </div>
    </ProductShell>
  );
}
