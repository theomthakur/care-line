import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { CloudOff, FlaskConical, MessageSquare, PhoneCall, RefreshCw, SearchX, WifiOff } from "lucide-react";
import { getCallState, getCallSummary, getCalls } from "./api";
import { Providers } from "./Providers";
import { Architecture, Deck, Developer } from "./pages/Explore";
import { Overview } from "./pages/Overview";
import { Landing } from "./pages/Landing";
import { FollowUps } from "./pages/FollowUps";
import { ago, shortClock } from "./format";
import { FIXTURE_STAGES } from "./fixtures";
import { usePoll, type Connection } from "./usePolling";
import { needsAttention, summaryFromState } from "./derive";
import { useRoute, type View } from "./route";
import { useTheme } from "./theme";
import { AppShell } from "./components/AppShell";
import { ConversationList } from "./components/ConversationList";
import { CaseHeader } from "./components/CaseHeader";
import type { CallState, SummaryDetails } from "./types";
import { Transcript } from "./components/Transcript";
import { EvidencePanel, MemberPanel, ProviderPanel, RequestPanel } from "./components/ContextPanels";
import { ActivityTimeline, BookingCard, HandoffPanel, SlotList, SummaryPanel } from "./components/OutcomePanels";
import { DemoControls, DemoMemberCard } from "./components/DemoControls";
import { Card, Chip, SkeletonLines } from "./components/ui";

const isFixture = import.meta.env.VITE_FIXTURE_ONLY === "1" || new URLSearchParams(window.location.search).get("source") === "fixture";

const TITLES: Record<View, string> = {
  overview: "Overview",
  conversations: "Conversations",
  followups: "Follow-ups",
  providers: "Providers",
  architecture: "System design",
  presentation: "Presentation",
  developer: "Developer view",
};

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
    <div className="case-skel" aria-busy="true" aria-label="Loading">
      <Card title={<span className="skel" style={{ display: "inline-block", width: 120, height: 12 }} />}>
        <SkeletonLines rows={6} />
      </Card>
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
          <p>When a member calls, the conversation opens here: what they said, who they are, which doctors were offered, and what was booked.</p>
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
        <div className="halo bad"><CloudOff size={32} strokeWidth={1.75} /></div>
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

export type Tab = "calls" | "call" | "case";

/**
 * One complete case for ONE call. Re-keyed by call id by the caller, so nothing (scroll position,
 * open panels, drafts) can leak from one conversation into another.
 */
const Case = memo(function Case({ s, tab, canAct, onChanged, stale, details, developer }: { s: CallState; tab: Tab; canAct: boolean; onChanged: () => void; stale: boolean; details: SummaryDetails | null | undefined; developer: boolean }) {
  const live = s.status === "live";
  const summary = !live || s.summary ? <SummaryPanel s={s} details={details} /> : null;
  return (
    <main className={`case ${stale ? "is-stale" : ""}`}>
      <CaseHeader s={s} />
      <div className="case-body">
        <div className={`col col-fill col-call ${tab === "call" ? "active" : ""}`}>
          <Card className="fill" title="Conversation" icon={<MessageSquare size={15} />} meta={live ? <Chip tone="green"><span className="dot" /> Updating live</Chip> : "Full transcript"} bodyClass="card-body" label="Conversation">
            <Transcript turns={s.turns} live={live} callId={s.call_id} />
          </Card>
        </div>
        <div className={`col col-side ${tab === "case" ? "active" : ""}`}>
          {!live && summary}
          <BookingCard s={s} />
          {s.tasks.length > 0 && <HandoffPanel s={s} canAct={canAct} onChanged={onChanged} />}
          {live && summary}
          <MemberPanel s={s} />
          <RequestPanel s={s} />
          <ProviderPanel s={s} />
          <EvidencePanel s={s} />
          {s.tasks.length === 0 && <HandoffPanel s={s} canAct={canAct} onChanged={onChanged} />}
          <SlotList s={s} />
          <ActivityTimeline s={s} developer={developer} />
          <DemoControls s={s} canAct={canAct} onChanged={onChanged} />
        </div>
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

function readDeveloper(): boolean {
  try {
    return localStorage.getItem("careline-developer") === "on";
  } catch {
    return false;
  }
}

export function App() {
  const theme = useTheme();
  const { route, go } = useRoute(!isFixture);
  const [showLanding, setShowLanding] = useState(import.meta.env.VITE_FIXTURE_ONLY === "1");
  const [stage, setStage] = useState("booked");
  const fixtureStage = useMemo(() => FIXTURE_STAGES.find((f) => f.key === stage) ?? FIXTURE_STAGES[0], [stage]);
  const [tab, setTab] = useState<Tab>("call");
  const [developer, setDeveloperState] = useState(readDeveloper);

  const view: View = route.view;
  const inConv = view === "conversations";
  const selectedId = isFixture ? null : route.call;

  const setDeveloper = useCallback(
    (on: boolean) => {
      try {
        localStorage.setItem("careline-developer", on ? "on" : "off");
      } catch {
        /* preference only */
      }
      setDeveloperState(on);
      if (!on) go({ view: "overview" });
    },
    [go],
  );
  useEffect(() => {
    if (!developer && view === "developer") go({ view: "overview" });
  }, [developer, view, go]);

  // Two independent polls: every call (cheap rows), and the ONE selected call's full state.
  const list = usePoll(getCalls, "calls", 1000, !isFixture);
  const detail = usePoll((signal) => getCallState(selectedId!, signal), inConv && selectedId ? `call:${selectedId}` : null, 1000, !isFixture);

  const calls = isFixture ? (fixtureStage.state ? [summaryFromState(fixtureStage.state)] : []) : list.data;
  const effectiveId = isFixture ? (fixtureStage.state?.call_id ?? null) : selectedId;

  const select = useCallback(
    (id: string) => {
      setTab("call");
      go({ view: "conversations", call: id });
    },
    [go],
  );

  // Pick a call ONCE, only while nothing is selected: the most recent active call, else the most
  // recently finished one. After that new calls never move the selection.
  useEffect(() => {
    if (isFixture || !inConv || selectedId || !list.data || list.data.length === 0) return;
    select((list.data.find((c) => c.status === "live") ?? list.data[0]).call_id);
  }, [inConv, selectedId, list.data, select]);

  const state = isFixture ? fixtureStage.state : detail.data ?? null;
  // The post-call facts (verification, provider, problems, follow-ups) for a finished call.
  const sumDoc = usePoll((signal) => getCallSummary(state!.call_id, signal), !isFixture && inConv && state?.status === "finalized" ? `summary:${state.call_id}` : null, 2000, true);
  const gone = !isFixture && inConv && selectedId !== null && detail.data === null;
  const loadingDetail = !isFixture && inConv && selectedId !== null && detail.data === undefined;
  const lastOk = inConv && selectedId ? detail.lastOk : list.lastOk;
  const worst = (a: Connection, b: Connection): Connection => (a === "disconnected" || b === "disconnected" ? "disconnected" : a === "stale" || b === "stale" ? "stale" : a);
  const link: Connection = isFixture ? "connected" : inConv && selectedId ? worst(detail.connection, list.connection) : list.connection;
  const down = !isFixture && (link === "stale" || link === "disconnected");
  const refresh = useCallback(() => {
    list.refresh();
    detail.refresh();
    sumDoc.refresh();
  }, [list.refresh, detail.refresh, sumDoc.refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  const error = detail.error ?? list.error;
  const canAct = !isFixture;
  const noCalls = !isFixture && list.data !== undefined && list.data.length === 0 && !selectedId;

  let body;
  if (!isFixture && link === "loading" && !state && !calls) body = <Skeleton />;
  else if (!isFixture && down && !state && !calls) body = <Unreachable error={error?.message ?? "The backend did not answer."} onRetry={refresh} />;
  else if (gone) body = <NotFound hasCalls={!!calls?.length} onBack={() => select((calls!.find((c) => c.status === "live") ?? calls![0]).call_id)} />;
  else if (noCalls || (!state && !loadingDetail && !effectiveId)) body = <Idle />;
  else if (!state) body = <Skeleton />;
  else body = <Case key={state.call_id} s={state} tab={tab} canAct={canAct} onChanged={refresh} stale={down} details={sumDoc.data?.details} developer={developer} />;

  const counts = useMemo(
    () => ({
      active: (calls ?? []).filter((c) => c.status === "live").length,
      attention: (calls ?? []).filter(needsAttention).length,
      followups: (calls ?? []).reduce((n, c) => n + c.open_tasks, 0),
    }),
    [calls],
  );

  const page =
    view === "overview" ? (
      <Overview calls={calls} loading={list.connection === "loading"} onOpen={select} onNavigate={(v) => go({ view: v })} />
    ) : view === "followups" ? (
      <FollowUps calls={calls} onOpenCall={select} canAct={canAct} onChanged={refresh} />
    ) : view === "providers" ? (
      <Providers />
    ) : view === "architecture" ? (
      <Architecture />
    ) : view === "presentation" ? (
      <Deck />
    ) : view === "developer" ? (
      <Developer state={state} />
    ) : (
      <>
        {isFixture && (
          <div className="fixture-bar" role="region" aria-label="Demo preview">
            <div className="fixture-copy"><span className="fixture-icon"><FlaskConical size={17}/></span><div><strong>Explore a sample call</strong><p>Showing a saved example. Changes and bookings are disabled.</p></div></div>
            <label className="fixture-selector"><span>CALL STAGE</span><select value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Choose sample call stage">{FIXTURE_STAGES.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select></label>
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
          {(["calls", "call", "case"] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t === "calls" ? `Calls${counts.active ? ` · ${counts.active}` : ""}` : t === "call" ? "Transcript" : "Case details"}
            </button>
          ))}
        </div>

        <div className={`conv-shell tab-${tab}`}>
          <ConversationList calls={calls} selectedId={effectiveId} onSelect={select} loading={!isFixture && list.data === undefined && link === "loading"} fixture={isFixture} stale={down} />
          <div className="case-pane">{body}</div>
        </div>
      </>
    );

  if (showLanding) return <Landing onOpen={() => setShowLanding(false)} theme={theme.mode} onTheme={theme.setMode} />;

  return (
    <AppShell
      view={view}
      onNavigate={(v) => go({ view: v })}
      counts={counts}
      theme={theme.mode}
      onTheme={theme.setMode}
      onDeveloper={setDeveloper}
      title={TITLES[view]}
      right={view === "providers" ? undefined : <ConnectionBadge connection={link} lastOk={lastOk} fixture={isFixture} onRetry={refresh} />}
    >
      {page}
    </AppShell>
  );
}
