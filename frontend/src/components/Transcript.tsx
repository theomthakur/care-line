import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowDown,
  AudioLines,
  LockKeyhole,
  MessageSquare,
  UserRound,
} from "lucide-react";
import type { Turn } from "../types";
import { isRedacted, shortClock } from "../format";
import { Empty } from "./ui";

const NEAR_BOTTOM = 56;
/** Long calls render only the newest turns; older ones load on demand. */
export const WINDOW = 200;

/**
 * Auto-scrolls to new turns only while the operator is already at the bottom. If they
 * have scrolled up to read, new turns raise a "jump to latest" chip instead of moving
 * the view.
 */
export function Transcript({
  turns,
  live,
  callId,
  followOnOpen = true,
}: {
  turns: Turn[];
  live: boolean;
  callId: string;
  followOnOpen?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastSeq = useRef(0);
  const lastCall = useRef(callId);
  const [unseen, setUnseen] = useState(0);
  const [all, setAll] = useState(false);
  const hidden = all ? 0 : Math.max(0, turns.length - WINDOW);
  const shown = hidden ? turns.slice(hidden) : turns;

  const toBottom = (smooth: boolean) => {
    const el = ref.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  };

  useLayoutEffect(() => {
    if (lastCall.current !== callId) {
      lastCall.current = callId;
      lastSeq.current = 0;
      pinned.current = true;
      setUnseen(0);
      setAll(false);
    }
    const newest = turns.length ? turns[turns.length - 1].seq : 0;
    const firstPaint = lastSeq.current === 0;
    const added = turns.filter((t) => t.seq > lastSeq.current).length;
    lastSeq.current = newest;
    if (!added || (firstPaint && !followOnOpen)) return;
    if (pinned.current) toBottom(lastSeq.current > 0 && added <= 2);
    else setUnseen((n) => n + added);
  }, [turns, callId, followOnOpen]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
      pinned.current = atBottom;
      if (atBottom) setUnseen(0);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  if (!turns.length) {
    return (
      <Empty
        icon={<MessageSquare size={18} />}
        title={live ? "Waiting for the first words" : "No transcript recorded"}
      >
        {live
          ? "The conversation appears here as soon as the caller and agent start talking."
          : "This call ended before any turn was stored."}
      </Empty>
    );
  }

  return (
    <>
      <div
        className="transcript"
        ref={ref}
        role="log"
        aria-live="polite"
        aria-label="Call transcript"
      >
        {hidden > 0 && (
          <div style={{ textAlign: "center", marginBottom: 12 }}>
            <button
              className="btn sm"
              onClick={() => {
                const el = ref.current;
                const before = el ? el.scrollHeight - el.scrollTop : 0;
                setAll(true);
                requestAnimationFrame(() => {
                  if (el) el.scrollTop = el.scrollHeight - before;
                });
              }}
            >
              Show {hidden} earlier {hidden === 1 ? "message" : "messages"}
            </button>
          </div>
        )}
        {shown.map((t) => (
          <div key={t.seq} className={`turn ${t.role}`}>
            <div className="who">
              <span
                className={`avatar ${t.role === "user" ? "caller" : "agent"}`}
                aria-hidden="true"
              >
                {t.role === "user" ? (
                  <UserRound size={13} />
                ) : (
                  <AudioLines size={13} />
                )}
              </span>
              <span className="turn-speaker">
                {t.role === "user" ? "Caller" : "CareLine"}
              </span>
              <time dateTime={t.received_at}>{shortClock(t.received_at)}</time>
            </div>
            <div className={`bubble ${isRedacted(t.text) ? "redacted" : ""}`}>
              {isRedacted(t.text) ? (
                <>
                  <LockKeyhole size={12} aria-hidden="true" />
                  Verification details hidden
                </>
              ) : (
                t.text
              )}
            </div>
          </div>
        ))}
      </div>
      {unseen > 0 && (
        <div className="jump">
          <button
            className="btn sm"
            onClick={() => {
              pinned.current = true;
              setUnseen(0);
              toBottom(true);
            }}
          >
            <ArrowDown size={14} /> {unseen} new{" "}
            {unseen === 1 ? "message" : "messages"}
          </button>
        </div>
      )}
    </>
  );
}
