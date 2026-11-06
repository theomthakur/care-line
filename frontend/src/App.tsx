import { useEffect, useMemo, useState } from "react";
import { Activity, CloudOff, FlaskConical, MessageSquare, PhoneCall, PhoneOff, RefreshCw, WifiOff } from "lucide-react";
import { getLatest } from "./api";
import { ago, callStartedAt, lastTurn, mmss, shortClock } from "./format";
import { FIXTURE_STAGES } from "./fixtures";
import { useLatest, type Connection } from "./usePolling";
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
        <h1>Call <span className="mono">{s.call_id}</span></h1>
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

type Tab = "call" | "context" | "outcome";

function Workspace({ s, canAct, onChanged, stale }: { s: CallState; canAct: boolean; onChanged: () => void; stale: boolean }) {
  const [tab, setTab] = useState<Tab>("call");
  const cls = (t: Tab) => (tab === t ? "active" : "");
  const live = s.status === "live";
  return (
    <>
      <div className="tabs" role="tablist" aria-label="Sections">
        {(["call", "context", "outcome"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t === "call" ? "Call" : t === "context" ? "Context" : "Outcome"}
          </button>
        ))}
      </div>
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
          <SlotList s={s} />
          <ActivityTimeline s={s} />
          {s.tasks.length === 0 && <HandoffPanel s={s} canAct={canAct} onChanged={onChanged} />}
          <div className="span-all"><DemoControls s={s} canAct={canAct} onChanged={onChanged} /></div>
        </div>
      </main>
    </>
  );
}

export function App() {
  const live = useLatest(getLatest, 1000, !isFixture);
  const [stage, setStage] = useState("booked");
  const fixture = useMemo(() => FIXTURE_STAGES.find((f) => f.key === stage) ?? FIXTURE_STAGES[0], [stage]);

  const state = isFixture ? fixture.state : live.state;
  const connection: Connection = isFixture ? "connected" : live.connection;
  const lastOk = live.lastOk;
  const canAct = !isFixture;
  const down = !isFixture && (connection === "stale" || connection === "disconnected");
  const refresh = live.refresh;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><Activity size={16} strokeWidth={2.4} /></span>
          Care Line
        </div>
        <span className="crumb-sep" />
        <span className="crumb">Operator console</span>
        <span className="topbar-spacer" />
        <div className="topbar-right">
          <ConnectionBadge connection={connection} lastOk={lastOk} fixture={isFixture} onRetry={refresh} />
        </div>
      </header>

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

      {down && state && (
        <div className="notice error" role="alert">
          <WifiOff size={15} />
          <span className="grow">
            {connection === "disconnected" ? "Backend disconnected." : "Connection interrupted."} Showing the last state received{lastOk ? ` at ${shortClock(new Date(lastOk).toISOString())} ET` : ""}. Nothing below is updating.
          </span>
          <button onClick={refresh}>Retry now</button>
        </div>
      )}

      {!isFixture && connection === "loading" && !state ? (
        <Skeleton />
      ) : !isFixture && !state && down ? (
        <Unreachable error={live.error?.message ?? "The backend did not answer."} onRetry={refresh} />
      ) : !state ? (
        <Idle />
      ) : (
        <>
          <CallBar s={state} />
          <Workspace key={state.call_id} s={state} canAct={canAct} onChanged={refresh} stale={down} />
        </>
      )}
    </div>
  );
}
