import { useEffect, useRef, useState } from "react";
import { useScope } from "../scope";
import { CompanyAvatar } from "./ui";

/** Top-bar client picker for DialDesk staff: "All clients" or one company; the pages that need a client follow it. */
export default function ClientSwitcher() {
  const { enabled, clients, client, clientId, setClientId } = useScope();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef(null);

  useEffect(() => {
    if (!open) return;
    const off = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);

  if (!enabled) return null;
  const list = clients.filter((c) => `${c.name} ${c.code}`.toLowerCase().includes(q.trim().toLowerCase()));
  const pick = (id) => { setClientId(id); setOpen(false); setQ(""); };

  return (
    <div className="switcher" ref={box}>
      <button className={`switch-btn ${client ? "on" : ""}`} onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}>
        {client ? <CompanyAvatar name={client.name} logo={client.logo_url} /> : <span className="switch-all">All</span>}
        <span className="switch-text"><small>Client</small>{client ? client.name : "All clients"}</span>
        <span className="switch-caret">▾</span>
      </button>
      {open && (
        <div className="switch-pop">
          <input autoFocus placeholder="Search client or code" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="switch-list" role="listbox">
            <button className={!clientId ? "sel" : ""} onClick={() => pick("")}><span className="switch-all">All</span> All clients</button>
            {list.map((c) => (
              <button key={c.id} className={String(c.id) === String(clientId) ? "sel" : ""} onClick={() => pick(c.id)}>
                <CompanyAvatar name={c.name} logo={c.logo_url} />
                <span><b>{c.name}</b><small>{c.code}</small></span>
              </button>
            ))}
            {list.length === 0 && <div className="muted small" style={{ padding: 10 }}>No client matches.</div>}
          </div>
        </div>
      )}
    </div>
  );
}
