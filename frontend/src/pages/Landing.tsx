import {
  ArrowDown,
  ArrowRight,
  AudioLines,
  CalendarCheck,
  Check,
  CheckCircle2,
  Headphones,
  Layers3,
  LockKeyhole,
  Moon,
  PhoneCall,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { Logo, LogoMark } from "../Logo";
import type { ThemeMode } from "../theme";

const steps = [
  {
    icon: Headphones,
    title: "A conversation, not a phone tree.",
    text: "The member explains what they need in their own words. The agent listens and guides the next step.",
  },
  {
    icon: ShieldCheck,
    title: "The right care, grounded in data.",
    text: "Member verification, provider eligibility and returned appointment slots keep the workflow on track.",
  },
  {
    icon: CalendarCheck,
    title: "A clear outcome. A complete handoff.",
    text: "Confirm the appointment, or give the support team the context to take it from here.",
  },
];

export function Landing({
  onOpen,
  theme,
  onTheme,
}: {
  onOpen: () => void;
  theme: ThemeMode;
  onTheme: (mode: ThemeMode) => void;
}) {
  return (
    <main className="landing">
      <header className="landing-nav">
        <Logo size={35} sub="CARE, CONNECTED" />
        <nav aria-label="Landing navigation">
          <a href="#how-it-works" className="landing-nav-link">
            How it works
          </a>
          <button
            className="btn icon-btn"
            aria-label={
              theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
            }
            onClick={() => onTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <button className="btn primary" onClick={onOpen}>
            Open workspace <ArrowRight size={15} />
          </button>
        </nav>
      </header>
      <section className="landing-hero">
        <div className="landing-hero-copy">
          <div className="eyebrow-pill">
            <span className="dot" /> A MORE HUMAN WAY TO FIND CARE
          </div>
          <h1>
            Good care starts
            <br />
            with a <span>conversation.</span>
          </h1>
          <p className="landing-intro">
            From “I need a doctor” to a clear next step. A voice assistant for
            members. A thoughtful workspace for the people who support them.
          </p>
          <div className="landing-actions">
            <button className="btn primary btn-large" onClick={onOpen}>
              Explore the workspace <ArrowRight size={17} />
            </button>
            <a href="#how-it-works">
              Meet CareLine <ArrowDown size={15} />
            </a>
          </div>
          <div className="landing-proof">
            <span>
              <Check size={14} /> Voice-led booking
            </span>
            <span>
              <Check size={14} /> Context-rich handoffs
            </span>
          </div>
          <p className="landing-note">
            Built for the Take2 voice agent hackathon. Synthetic data only.
          </p>
        </div>
        <div
          className="care-scene"
          aria-label="Illustration of a sample member journey"
        >
          <div className="scene-caption">
            <span>THE MEMBER JOURNEY</span>
            <span>01 — 03</span>
          </div>
          <div className="scene-voice">
            <div className="scene-agent">
              <LogoMark size={42} />
              <div>
                <strong>Your care, a call away.</strong>
                <span>CareLine voice assistant</span>
              </div>
              <span className="scene-phone">
                <PhoneCall size={18} />
              </span>
            </div>
            <div className="voice-wave" aria-hidden="true">
              {Array.from({ length: 37 }, (_, i) => (
                <i
                  key={i}
                  style={{
                    height: `${[10, 18, 28, 14, 38, 22, 46, 30, 18, 36, 50, 24][i % 12]}px`,
                  }}
                />
              ))}
            </div>
            <div className="scene-quote">
              “I’m looking for the earliest appointment
              <br />
              with a primary care doctor.”
            </div>
            <div className="scene-response">
              <AudioLines size={18} />
              <span>Let’s find the right next step.</span>
            </div>
          </div>
          <div className="scene-path" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="scene-result">
            <span className="scene-result-icon">
              <CalendarCheck size={22} />
            </span>
            <div>
              <span className="scene-overline">A CLEAR OUTCOME</span>
              <strong>Appointment details, ready to review.</strong>
              <p>Read back. Confirm. Keep everyone in the loop.</p>
            </div>
            <CheckCircle2 size={20} className="scene-check" />
          </div>
          <div className="scene-foot">
            <LockKeyhole size={13} />
            <span>Illustrative journey · no real patient information</span>
          </div>
        </div>
      </section>
      <section className="landing-value-strip" aria-label="Product principles">
        <span>
          <AudioLines size={19} /> Natural conversation
        </span>
        <span>
          <Layers3 size={19} /> One connected workflow
        </span>
        <span>
          <Headphones size={19} /> People in the loop
        </span>
      </section>
      <section className="landing-section" id="how-it-works">
        <div className="landing-section-heading">
          <div>
            <p className="landing-eyebrow">
              FROM FIRST HELLO TO FOLLOW-THROUGH
            </p>
            <h2>
              Less navigating.
              <br />
              More getting somewhere.
            </h2>
          </div>
          <p>
            A focused workflow that helps the member move forward, and gives the
            operator a clear picture of what happened.
          </p>
        </div>
        <div className="journey-cards">
          {steps.map(({ icon: Icon, title, text }, i) => (
            <article key={title}>
              <span className="journey-number">0{i + 1}</span>
              <span className="journey-icon">
                <Icon size={23} strokeWidth={1.6} />
              </span>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="workspace-invitation">
        <div>
          <p className="landing-eyebrow">BEHIND EVERY GOOD CALL</p>
          <h2>
            A workspace that sees
            <br />
            the whole conversation.
          </h2>
          <p>
            Browse sample conversations, review appointment details, and explore
            the follow-ups that need a human touch.
          </p>
          <button className="btn primary btn-large" onClick={onOpen}>
            Take a look inside <ArrowRight size={16} />
          </button>
        </div>
        <div className="invitation-stack">
          <div>
            <span className="mini-avatar">MT</span>
            <span>
              <b>Maya T.</b>
              <small>Sample member conversation</small>
            </span>
            <span className="chip green">Booked</span>
          </div>
          <div>
            <CheckCircle2 size={18} />
            <span>Appointment and provider details</span>
          </div>
          <div>
            <Headphones size={18} />
            <span>Conversation and handoff context</span>
          </div>
        </div>
      </section>
      <section className="landing-disclosure">
        <ShieldCheck size={20} />
        <div>
          <h2>A prototype with clear boundaries.</h2>
          <p>
            The hosted preview is read-only and uses fictional members,
            providers and schedules. It does not place calls or create real
            appointments. The phone agent and booking API run separately. This
            is not a production healthcare service.
          </p>
        </div>
      </section>
      <footer>
        <Logo size={26} sub="" />
        <span>Built with care. Designed for clarity.</span>
        <span>Take2 voice agent hackathon</span>
      </footer>
    </main>
  );
}
