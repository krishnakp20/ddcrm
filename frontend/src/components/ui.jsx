import { useEffect, useState } from "react";

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="alert error">{error}</div>;
}

export function Spinner({ label = "Loading…" }) {
  return <div className="center muted">{label}</div>;
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

export function PageHead({ title, sub, children }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      <div className="row wrap">{children}</div>
    </div>
  );
}

export function Badge({ tone = "", children }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Field({ label, hint, error, full, children }) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      {label}
      {children}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="err">{error}</span>}
    </label>
  );
}

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  return (
    <div className="pager">
      <span>{from}–{Math.min(page * pageSize, total)} of {total}</span>
      <div className="row">
        <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span>Page {page} of {pages}</span>
        <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}

export function Toast({ message, onDone }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [message, onDone]);
  return message ? <div className="toast">{message}</div> : null;
}

export function useToast() {
  const [message, setMessage] = useState("");
  return [message, setMessage, <Toast key="toast" message={message} onDone={() => setMessage("")} />];
}

export const initials = (name = "") =>
  name.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";

export function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtDuration(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export const STATUS_TONE = {
  new: "", attempted: "warn", contacted: "primary", callback: "warn", converted: "success", closed: "", dnc: "danger",
  connected: "success", dialing: "primary", wrapup: "warn", completed: "", missed: "danger", failed: "danger",
};

export function StatusBadge({ status }) {
  return <Badge tone={STATUS_TONE[status] || ""}>{status?.replace("_", " ")}</Badge>;
}

export function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export const CLIENT_STATUS = {
  draft: "Draft", submitted: "Submitted", under_review: "Under review", needs_info: "Needs info",
  active: "Active", rejected: "Rejected", suspended: "Suspended",
};

export function ClientStatus({ status }) {
  return <span className={`badge ${status}`}>{CLIENT_STATUS[status] || status}</span>;
}

/** Company logo, or the company's initials when there is no logo. */
export function CompanyAvatar({ name, logo, large }) {
  return (
    <span className={`avatar-co ${large ? "lg" : ""}`}>
      {logo ? <img src={logo} alt="" /> : initials(name || "?")}
    </span>
  );
}

export function CopyButton({ text, label = "Copy" }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const t = document.createElement("textarea");
      t.value = text;
      document.body.appendChild(t);
      t.select();
      document.execCommand("copy");
      t.remove();
    }
    setDone(true);
    setTimeout(() => setDone(false), 1800);
  }
  return <button type="button" className="btn btn-sm" onClick={copy}>{done ? "Copied ✓" : label}</button>;
}

export function Icon({ name }) {
  const paths = {
    dashboard: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
    clients: "M3 21V7l9-4 9 4v14M9 21v-6h6v6M8 10h.01M12 10h.01M16 10h.01",
    settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z",
    clock: "M12 6v6l4 2M12 21a9 9 0 100-18 9 9 0 000 18z",
    check: "M20 6L9 17l-5-5",
    plus: "M12 5v14M5 12h14",
    alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
    menu: "M3 6h18M3 12h18M3 18h18",
    users: "M17 21v-2a4 4 0 00-4-4H7a4 4 0 00-4 4v2M10 11a4 4 0 100-8 4 4 0 000 8zM21 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8",
    dept: "M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M15 9h.01M9 13h.01M15 13h.01M9 17h6",
    campaign: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
    forms: "M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4",
    plans: "M20 12V8a2 2 0 00-2-2h-4L12 4H6a2 2 0 00-2 2v12a2 2 0 002 2h8M16 19l2 2 4-4",
    spark: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name] || paths.dashboard} /></svg>
  );
}
