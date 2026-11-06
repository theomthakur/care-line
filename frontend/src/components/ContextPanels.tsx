import { BadgeCheck, Building2, CircleSlash, FileText, MapPin, Phone, Search, ShieldCheck, UserRound } from "lucide-react";
import type { CallState } from "../types";
import { initials } from "../format";
import { verificationLabel } from "../derive";
import { Card, Chip, Empty, Na } from "./ui";

export function MemberPanel({ s }: { s: CallState }) {
  const v = verificationLabel(s);
  const m = s.member;
  return (
    <Card title="Member" icon={<UserRound size={15} />} meta={<Chip tone={v.tone === "green" ? "green" : v.tone === "red" ? "red" : "amber"}>{v.tone === "green" ? <BadgeCheck size={12} /> : <ShieldCheck size={12} />}{v.text}</Chip>}>
      <div className="member-head">
        <div className={`member-avatar ${m ? "" : "empty"}`} aria-hidden="true">{m ? initials(m.name) : "?"}</div>
        <div>
          <div className="name">{m ? m.name : "Unverified caller"}</div>
          <div className="sub">{m ? "Verified against synthetic records" : v.text === "Locked" ? "Verification locked. No member data is shown." : "No member data is shown until verification succeeds."}</div>
        </div>
      </div>
      <dl className="kv">
        <dt>Member ID</dt>
        <dd>{m ? <span className="mono num">{m.id_masked}</span> : <Na>Hidden</Na>}</dd>
        <dt>Plan</dt>
        <dd>{m?.plan ?? <Na />}</dd>
        <dt>Network</dt>
        <dd>{m?.network ?? <Na />}</dd>
        <dt>Coverage</dt>
        <dd>{m ? m.active ? <Chip tone="green">Active</Chip> : <Chip tone="red">Ended</Chip> : <Na />}</dd>
      </dl>
    </Card>
  );
}

export function RequestPanel({ s }: { s: CallState }) {
  const r = s.request;
  const empty = r.version === 0 && !r.specialty && !r.zip;
  return (
    <Card title="Current request" icon={<Search size={15} />} meta={r.version > 1 ? <Chip tone="blue">Revised · v{r.version}</Chip> : r.version === 1 ? <Chip>v1</Chip> : undefined}>
      {empty ? (
        <span className="muted">No search yet. The agent records the specialty and ZIP once the caller states them.</span>
      ) : (
        <dl className="kv">
          <dt>Visit</dt>
          <dd>{r.specialty ? <>New patient · {r.specialty}</> : <Na />}</dd>
          <dt>Near ZIP</dt>
          <dd>{r.zip ? <span className="num">{r.zip}</span> : <Na />}</dd>
          <dt>Corrections</dt>
          <dd>{r.version > 1 ? `${r.version - 1} earlier ${r.version - 1 === 1 ? "version" : "versions"} replaced. Only the latest is used.` : <span className="muted">None</span>}</dd>
        </dl>
      )}
    </Card>
  );
}

export function ProviderPanel({ s }: { s: CallState }) {
  const has = s.providers.length > 0 || s.excluded.length > 0;
  return (
    <Card
      title="Providers"
      icon={<Building2 size={15} />}
      meta={has ? <span>{s.providers.length} eligible{s.excluded.length ? ` · ${s.excluded.length} excluded` : ""}</span> : undefined}
    >
      {!has ? (
        <Empty icon={<Search size={18} />} title="No provider search yet">In-network options and any excluded doctors, with reasons, appear here.</Empty>
      ) : (
        <>
          {s.providers.length === 0 ? (
            <span className="muted">No eligible provider found for this request.</span>
          ) : (
            <>
              <div className="section-label">In network · accepting new patients</div>
              <ul>
                {s.providers.map((p, i) => {
                  const sel = s.selected === p.id;
                  return (
                    <li key={p.id} className={`provider ${sel ? "selected" : ""}`}>
                      <span className="rank num" aria-label={`Rank ${i + 1}`}>{i + 1}</span>
                      <div className="grow">
                        <div className="pname">{p.name}</div>
                        <div className="pmeta">
                          <span><MapPin size={12} /> {p.zip}</span>
                          <span><Phone size={12} /> <span className="num">{p.phone}</span></span>
                        </div>
                      </div>
                      {sel && <Chip tone="teal">Selected</Chip>}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          {s.excluded.length > 0 && (
            <>
              <div className="section-label">Not offered</div>
              <ul>
                {s.excluded.map((e) => (
                  <li key={e.id} className="excluded">
                    <CircleSlash size={16} color="var(--ink-400)" style={{ marginTop: 2, flex: "none" }} />
                    <div>
                      <div className="ename">{e.name}</div>
                      <div className="ereason">
                        <Chip tone="amber">{e.reason}</Chip>
                        <span className="faint mono" title="Contract reason code">{e.reason_code}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Card>
  );
}

export function EvidencePanel({ s }: { s: CallState }) {
  return (
    <Card title="Plan evidence" icon={<FileText size={15} />} meta={s.evidence.length ? <Chip tone="teal"><ShieldCheck size={12} />From system data</Chip> : undefined}>
      {s.evidence.length === 0 ? (
        <span className="muted">No plan passage has been returned for this call yet. Nothing here is written by the model.</span>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {s.evidence.map((e) => (
            <figure key={e.id} className="evidence" style={{ margin: 0 }}>
              <div className="section-label" style={{ margin: "0 0 8px" }}>{e.title}</div>
              <blockquote style={{ margin: 0 }}><q>{e.text}</q></blockquote>
              <figcaption className="src">
                <span>Source</span> <Chip tone="outline"><span className="mono">{e.id}</span></Chip>
                <span>Synthetic plan record</span>
              </figcaption>
            </figure>
          ))}
          <p className="evidence-note">Reference text only. It is not a cost guarantee or a claim decision.</p>
        </div>
      )}
    </Card>
  );
}
