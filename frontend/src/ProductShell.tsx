import { useEffect, useState, type ReactNode } from 'react';
import { Activity, AudioLines, CalendarClock, ChevronLeft, ChevronRight, Code2, Headphones, LayoutDashboard, Maximize2, Minimize2, Moon, Presentation, ShieldCheck, Stethoscope, Sun, Workflow } from 'lucide-react';
import type { CallState } from './types';
import { Logo, LogoMark } from './Logo';
import type { CallListItem } from './api';

export type Section = 'workspace' | 'history' | 'providers' | 'architecture' | 'presentation' | 'developer';
type Props = { section: Section; setSection: (s: Section) => void; children: ReactNode; developer: boolean; setDeveloper: (x: boolean) => void };

export function ProductShell({section,setSection,children,developer,setDeveloper}: Props) {
 const [collapsed,setCollapsed] = useState(() => localStorage.getItem('careline-sidebar') === 'closed');
 const [dark,setDark] = useState(() => localStorage.getItem('careline-theme') === 'dark');
 useEffect(() => {document.documentElement.dataset.theme = dark ? 'dark' : 'light';localStorage.setItem('careline-theme',dark?'dark':'light');},[dark]);
 const collapse=()=>setCollapsed(x=>{localStorage.setItem('careline-sidebar',x?'open':'closed');return !x});
 const link=(s:Section,label:string,icon:ReactNode)=><button className={`shell-link ${section===s?'selected':''}`} onClick={()=>setSection(s)} title={label} aria-label={label} aria-current={section===s?'page':undefined}>{icon}<span>{label}</span></button>;
 return <div className={`product-shell ${collapsed?'shell-collapsed':''}`}>
  <aside className="shell-nav"><div className="shell-brand"><Logo size={38}/></div>
   <div className="shell-section">WORKSPACE</div>
   {link('workspace','Live workspace',<LayoutDashboard size={18}/>)}
   {link('history','Call history',<CalendarClock size={18}/>)}
   {link('providers','Providers',<Stethoscope size={18}/>)}
   <div className="shell-section">EXPLORE</div>
   {link('architecture','System design',<Workflow size={18}/>)}
   {link('presentation','Presentation',<Presentation size={18}/>)}
   {developer && link('developer','Developer view',<Code2 size={18}/>)}
   <div className="shell-push"/><div className="shell-bottom">
   <button className="shell-link" onClick={()=>setDeveloper(!developer)} title="Developer view" aria-pressed={developer}><Code2 size={18}/><span>Developer {developer?'on':'off'}</span></button>
   <button className="shell-link" onClick={()=>setDark(!dark)} title={dark?'Use light mode':'Use dark mode'}>{dark?<Sun size={18}/>:<Moon size={18}/>}<span>{dark?'Light mode':'Dark mode'}</span></button>
   <button className="shell-link" onClick={collapse} aria-label={collapsed?'Expand sidebar':'Collapse sidebar'}>{collapsed?<ChevronRight size={18}/>:<ChevronLeft size={18}/>}<span>Collapse sidebar</span></button>
   <div className="operator"><span className="operator-avatar">OP</span><span><b>Care team</b><small>Member services</small></span></div></div>
  </aside><div className="product-main">{children}</div></div>;
}

export function History({calls,loading,error,onSelect}:{calls:CallListItem[];loading:boolean;error:string;onSelect:(id:string)=>void}) {
 return <div className="page-wrap"><div className="page-head"><div><div className="page-kicker">YOUR WORKSPACE</div><h1>Call history</h1><p>Review previous calls, their conversations and outcomes.</p></div><span className="page-pill">Synthetic demo records</span></div>
 <div className="history-card"><div className="section-header"><div><h2>Recent calls</h2><p>Saved in the local demo database until you reset it.</p></div><span>{calls.length} shown</span></div>
 {error?<div className="history-empty" role="alert">Could not load calls. {error}</div>:loading?<div className="history-empty">Loading calls…</div>:calls.length===0?<div className="history-empty"><Headphones size={26}/><b>No calls yet</b><span>Completed and active demo calls will appear here.</span></div>:<div className="history-list">{calls.map(c=><button className="history-row" key={c.call_id} onClick={()=>onSelect(c.call_id)}><span className="history-icon"><AudioLines size={18}/></span><span className="history-name"><b>{c.member || 'Unverified caller'}</b><small>{new Date(c.created_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}</small></span><span className={`history-status ${c.status==='live'?'live':''}`}>{c.status==='live'?'Live':c.booked?'Booked':'Ended'}</span><ChevronRight size={17}/></button>)}</div>}</div></div>;
}

const steps=[['01','Incoming call','LiveKit connects the caller to the voice agent.'],['02','Listen & understand','Speech recognition transcribes; the model selects a supported action.'],['03','Verify & find care','The booking service checks the demo member, plan and provider schedule.'],['04','Confirm & record','A read-back and clear confirmation precede a simulated booking.'],['05','Support handoff','The workspace shows the conversation, result and follow-up.']];
export function Architecture() {return <div className="page-wrap"><div className="page-head"><div><div className="page-kicker">HOW IT WORKS</div><h1>From call to care</h1><p>One clear path from a member’s question to an operator-ready outcome.</p></div><span className="page-pill">Demo architecture</span></div><div className="architecture-card"><div className="arch-title"><div className="arch-icon"><Workflow size={23}/></div><div><h2>CareLine system flow</h2><p>Built for a focused, reliable phone conversation.</p></div></div><div className="arch-grid">{steps.map(([n,title,desc])=><div className="arch-step" key={n}><span>{n}</span><b>{title}</b><p>{desc}</p></div>)}</div><div className="arch-tech"><b>Built with</b><span>LiveKit</span><span>Python</span><span>FastAPI</span><span>SQLite</span><span>React</span><span>TypeScript</span></div><div className="arch-foot"><ShieldCheck size={18}/><span>Verification, provider eligibility and confirmation are checked by the backend. Provider data and appointments are simulated.</span></div></div></div>}

const slides=[{eyebrow:'THE PROBLEM',title:'Finding care should not be a maze.',body:'Members need a simple way to find an eligible doctor and understand what happens next.'},{eyebrow:'OUR APPROACH',title:'A helpful voice. A clear outcome.',body:'CareLine helps a member verify demo details, find in-network primary care and choose an appointment.'},{eyebrow:'THE WORKFLOW',title:'Listen. Check. Confirm.',body:'The agent offers only returned availability, reads the choice back and records a simulated booking after confirmation.'},{eyebrow:'THE OPERATOR',title:'The full conversation, in context.',body:'A support workspace brings the transcript, eligibility, appointment and handoff together.'},{eyebrow:'NEXT STEPS',title:'Build trust before expanding.',body:'Test difficult callers, connect verified data sources and develop the controls needed for a real deployment.'}];
export function Deck(){const [page,setPage]=useState(0);const [full,setFull]=useState(false);const slide=slides[page];useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')setFull(false);if(e.key==='ArrowRight')setPage(x=>Math.min(x+1,slides.length-1));if(e.key==='ArrowLeft')setPage(x=>Math.max(x-1,0));};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[]);return <div className={`deck-wrap ${full?'deck-full':''}`}><div className="deck-toolbar"><div><Presentation size={18}/> <b>CareLine story</b> <span>· {page+1} / {slides.length}</span></div><button className="btn" onClick={()=>setFull(!full)}>{full?<Minimize2 size={15}/>:<Maximize2 size={15}/>} {full?'Exit full screen':'Full screen'}</button></div><div className="deck-slide"><div className="deck-orb one"/><div className="deck-orb two"/><div className="deck-content"><div className="deck-wordmark"><LogoMark size={26}/> CARELINE</div><div className="deck-label">{slide.eyebrow}</div><h1>{slide.title}</h1><p>{slide.body}</p><div className="deck-small">FICTIONAL INSURER · SYNTHETIC DATA · SIMULATED APPOINTMENTS</div></div><div className="deck-footer"><span>MEMBER SERVICES, MADE SIMPLER.</span><div>{slides.map((_,i)=><button key={i} className={i===page?'current':''} onClick={()=>setPage(i)} aria-label={`Slide ${i+1}`}/>)}</div><span>0{page+1} / 0{slides.length}</span></div></div><div className="deck-controls"><button className="btn" disabled={page===0} onClick={()=>setPage(page-1)}>Previous</button><button className="btn primary" disabled={page===slides.length-1} onClick={()=>setPage(page+1)}>Next slide <ChevronRight size={15}/></button></div></div>}

export function Developer({state}:{state:CallState|null}){return <div className="page-wrap"><div className="page-head"><div><div className="page-kicker">DEVELOPER VIEW</div><h1>Inspect the demo</h1><p>Review the redacted operator state returned by the local API.</p></div><span className="page-pill">Read only</span></div><div className="developer-card"><div className="section-header"><div><h2>Current call state</h2><p>No credentials or internal booking tokens are shown.</p></div><span><Activity size={15}/> Local API</span></div><pre>{state?JSON.stringify(state,null,2):'Waiting for a call…'}</pre></div></div>}
