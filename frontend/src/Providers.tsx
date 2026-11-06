import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, MapPin, Phone, Search } from "lucide-react";

export type DirectoryProvider = {
  id: string;
  name: string;
  specialty: string;
  zip: string;
  phone: string;
  accepting_new_patients: boolean;
  networks: string[];
  open_slots: number;
  next_open: string[];
  days: { date: string; open: number; total: number }[];
};

const NETWORK_LABEL: Record<string, string> = { METRO: "Metro network", VALUE: "Value network" };

export async function getProviderDirectory(signal?: AbortSignal): Promise<DirectoryProvider[]> {
  const res = await fetch("/providers/directory", { signal, headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(String(res.status));
  const body = (await res.json()) as { providers?: DirectoryProvider[] };
  return Array.isArray(body.providers) ? body.providers : [];
}

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });

function dayLabel(date: string) {
  const d = new Date(date + "T12:00:00");
  return { dow: d.toLocaleDateString("en-US", { weekday: "short" }), dom: d.getDate() };
}

function Availability({ days }: { days: DirectoryProvider["days"] }) {
  if (!days.length) return <div className="avail-empty">No schedule loaded.</div>;
  return (
    <div className="avail" role="list" aria-label="Open times by day">
      {days.map((d) => {
        const { dow, dom } = dayLabel(d.date);
        const level = d.open === 0 ? "none" : d.open < 4 ? "low" : d.open < 8 ? "mid" : "high";
        return (
          <div className={`avail-day ${level}`} role="listitem" key={d.date} title={`${d.open} of ${d.total} times open`}>
            <small>{dow}</small>
            <b>{dom}</b>
            <span>{d.open} open</span>
          </div>
        );
      })}
    </div>
  );
}

export function Providers() {
  const [items, setItems] = useState<DirectoryProvider[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [network, setNetwork] = useState("all");
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    const load = () =>
      getProviderDirectory(ctl.signal)
        .then((x) => {
          setItems(x);
          setError("");
        })
        .catch((e) => {
          if ((e as Error).name !== "AbortError") setError("Could not load the provider directory. Check the backend connection.");
        });
    void load();
    const id = setInterval(load, 10000);
    return () => {
      ctl.abort();
      clearInterval(id);
    };
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter(
      (p) =>
        (network === "all" || p.networks.includes(network)) &&
        (!q || p.name.toLowerCase().includes(q) || p.zip.includes(q) || p.specialty.includes(q)),
    );
  }, [items, query, network]);

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-kicker">PROVIDER DIRECTORY</div>
          <h1>Providers and availability</h1>
          <p>Every doctor the assistant can offer, with live open times for the next two weeks.</p>
        </div>
        <span className="page-pill">{items ? `${items.length} providers` : "Loading"}</span>
      </div>
      <div className="history-card">
        <div className="dir-tools">
          <label className="dir-search">
            <Search size={16} aria-hidden="true" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name or ZIP" aria-label="Search providers" />
          </label>
          <div className="dir-filter" role="group" aria-label="Network filter">
            {["all", "METRO", "VALUE"].map((n) => (
              <button key={n} className={network === n ? "on" : ""} onClick={() => setNetwork(n)}>
                {n === "all" ? "All networks" : NETWORK_LABEL[n]}
              </button>
            ))}
          </div>
        </div>
        {error ? (
          <div className="history-empty" role="alert">{error}</div>
        ) : !items ? (
          <div className="history-empty">Loading providers…</div>
        ) : shown.length === 0 ? (
          <div className="history-empty"><b>No providers match</b><span>Try a different name, ZIP or network.</span></div>
        ) : (
          <div className="dir-list">
            {shown.map((p) => {
              const open = openId === p.id;
              return (
                <div className="dir-item" key={p.id}>
                  <button className="dir-row" onClick={() => setOpenId(open ? null : p.id)} aria-expanded={open}>
                    <span className="dir-avatar" aria-hidden="true">{p.name.replace(/^Dr\. /, "").slice(0, 1)}</span>
                    <span className="dir-name">
                      <b>{p.name}</b>
                      <small><MapPin size={12} /> {p.zip} · {p.specialty}</small>
                    </span>
                    <span className="dir-tags">
                      {p.networks.map((n) => <i key={n} className="tag">{NETWORK_LABEL[n] ?? n}</i>)}
                      <i className={`tag ${p.accepting_new_patients ? "good" : "warn"}`}>
                        {p.accepting_new_patients ? "New patients" : "Existing patients only"}
                      </i>
                    </span>
                    <span className="dir-open"><b>{p.open_slots}</b><small>open times</small></span>
                    {open ? <ChevronDown size={17} /> : <ChevronRight size={17} />}
                  </button>
                  {open && (
                    <div className="dir-detail">
                      <div className="dir-meta"><Phone size={14} /> Office {p.phone}</div>
                      <Availability days={p.days} />
                      <div className="dir-next">
                        <b>Next openings</b>
                        {p.next_open.length ? p.next_open.map((t) => <span key={t} className="chip-time">{when(t)}</span>) : <span className="avail-empty">No open times in the next two weeks.</span>}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
