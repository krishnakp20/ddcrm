import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Modal, PageHead, Pager, Spinner } from "../components/ui";
import { useScope } from "../scope";

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const ago = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d; };
const PRESETS = [["Today", () => [iso(new Date()), iso(new Date())]], ["Yesterday", () => [iso(ago(1)), iso(ago(1))]], ["Last 7 days", () => [iso(ago(6)), iso(new Date())]], ["Last 30 days", () => [iso(ago(29)), iso(new Date())]]];

/** Call records from the dialer (CDR), with the recording of each call. */
export default function Cdr() {
  const { user } = useAuth();
  const staff = user.user_type === "staff";
  const { clientId } = useScope();
  const [range, setRange] = useState(PRESETS[0][1]());
  const [preset, setPreset] = useState("Today");
  const [f, setF] = useState({ direction: "", status: "", agent: "", q: "", mapped: "", server_id: "", recording: "" });
  const [servers, setServers] = useState([]);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);

  const query = () => ({ date_from: range[0], date_to: range[1], client_id: clientId || undefined, direction: f.direction || undefined, status: f.status || undefined, agent: f.agent || undefined,
    q: f.q || undefined, mapped: f.mapped || undefined, server_id: f.server_id || undefined, recording: f.recording || undefined });
  useEffect(() => { if (staff) api.get("/dialer/servers").then((r) => setServers(r.data)).catch(() => {}); }, [staff]);
  useEffect(() => setPage(1), [range, f, clientId]);
  const load = useCallback(() => {
    setData(null); setError("");
    api.get("/cdr", { params: { ...query(), page } }).then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
  }, [range, f, clientId, page]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  async function download() {
    setBusy(true);
    try {
      const r = await api.get("/cdr/export", { params: query(), responseType: "blob" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = `cdr_${range[0]}_${range[1]}.csv`; document.body.appendChild(a); a.click(); a.remove();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  return (
    <>
      <PageHead title="Call records (CDR)" sub={staff ? "Every call from the dialer servers. Choose a client in the top bar to limit it." : "Calls of your company, with recordings."}>
        <button className="btn btn-primary" disabled={busy || !data} onClick={download}>{busy ? "Preparing…" : "Download CSV"}</button>
      </PageHead>
      <div className="card card-pad row wrap" style={{ marginBottom: 12, gap: 8 }}>
        <div className="seg">{PRESETS.map(([l, fn]) => <button key={l} className={preset === l ? "on" : ""} onClick={() => { setPreset(l); setRange(fn()); }}>{l}</button>)}</div>
        <input type="date" style={{ width: 150 }} value={range[0]} max={range[1]} onChange={(e) => { setPreset(""); setRange([e.target.value, range[1]]); }} aria-label="From" />
        <span className="muted">to</span>
        <input type="date" style={{ width: 150 }} value={range[1]} min={range[0]} onChange={(e) => { setPreset(""); setRange([range[0], e.target.value]); }} aria-label="To" />
        <select style={{ width: 130 }} value={f.direction} onChange={set("direction")}><option value="">In and out</option><option value="in">Inbound</option><option value="out">Outbound</option></select>
        <input style={{ width: 110 }} placeholder="Status" value={f.status} onChange={set("status")} />
        <input style={{ width: 120 }} placeholder="Agent" value={f.agent} onChange={set("agent")} />
        <input style={{ width: 150 }} placeholder="Phone number" value={f.q} onChange={set("q")} />
        <select style={{ width: 150 }} value={f.recording} onChange={set("recording")}><option value="">With or without recording</option><option value="yes">Only with recording</option></select>
        {staff && <select style={{ width: 150 }} value={f.mapped} onChange={set("mapped")}><option value="">Mapped or not</option><option value="no">Not matched to a client</option></select>}
        {staff && servers.length > 1 && <select style={{ width: 150 }} value={f.server_id} onChange={set("server_id")}><option value="">All servers</option>{servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="kpi-strip" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
            <div className="kpi"><div className="kpi-label">Calls</div><div className="kpi-value">{data.summary.calls}</div><div className="kpi-sub">{data.summary.inbound} in · {data.summary.outbound} out</div></div>
            <div className="kpi"><div className="kpi-label">With recording</div><div className="kpi-value">{data.summary.with_recording}</div></div>
            <div className="kpi"><div className="kpi-label">Abandoned</div><div className="kpi-value" style={data.summary.abandoned ? { color: "var(--danger)" } : undefined}>{data.summary.abandoned}</div></div>
            <div className="kpi"><div className="kpi-label">Avg talk</div><div className="kpi-value">{data.summary.avg_talk}s</div></div>
            <div className="kpi"><div className="kpi-label">Avg queue (in)</div><div className="kpi-value">{data.summary.avg_queue}s</div></div>
          </div>
          <div className="card">
            {data.rows.length === 0 ? <Empty>No calls for this range and filter.</Empty> : (
              <div className="table-wrap">
                <table>
                  <thead><tr>{data.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr key={r.id} className="click" onClick={() => setOpen(r.id)}>
                        {data.columns.map((c) => (
                          <td key={c.key} className={c.key === "phone" ? "mono" : ""}>
                            {c.key === "recording" ? (r.recording ? <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); setOpen(r.id); }}>▶ Play</button> : "") :
                              c.key === "agent" ? <>{r.agent}{r.agent_name && <div className="small muted">{r.agent_name}</div>}</> :
                              c.key === "status" ? <Badge tone={["DROP", "XDROP", "TIMEOT"].includes(r.status) ? "danger" : ""}>{r.status || "—"}</Badge> : r[c.key]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </div>
        </>
      )}
      {open && <CallModal id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function CallModal({ id, onClose }) {
  const [c, setC] = useState(null);
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api.get(`/cdr/${id}`).then((r) => setC(r.data)).catch((e) => setError(errorMessage(e))); }, [id]);
  async function play() {
    setError("");
    try { const { data } = await api.post(`/cdr/${id}/recording-link`); setSrc(data.url); } catch (e) { setError(errorMessage(e)); }
  }
  return (
    <Modal title={`Call ${id}`} onClose={onClose} footer={<button className="btn" onClick={onClose}>Close</button>}>
      <div className="stack">
        <ErrorBox error={error} />
        {!c ? <Spinner /> : (
          <>
            <dl className="kv" style={{ gridTemplateColumns: "120px minmax(0, 1fr)" }}>
              <dt>Start</dt><dd>{c.when}</dd><dt>Direction</dt><dd>{c.direction}</dd><dt>Client</dt><dd>{c.client}</dd>
              <dt>Campaign / ingroup</dt><dd className="mono">{c.campaign}</dd><dt>Phone</dt><dd className="mono">{c.phone}</dd>
              <dt>Agent</dt><dd>{c.agent}{c.agent_name ? ` · ${c.agent_name}` : ""}</dd><dt>Status</dt><dd>{c.status}</dd>
              <dt>Length</dt><dd>{c.talk}s{c.direction === "Inbound" ? ` (queue ${c.queue}s)` : ""}</dd><dt>Ended by</dt><dd>{c.term || "—"}</dd><dt>Dialer</dt><dd>{c.server} · {c.uniqueid}</dd>
              {c.crm_call && <><dt>Tagged in the CRM</dt><dd>{c.crm_call.scenario.join(" › ") || "tagged"} {c.crm_call.outcome && <Badge tone="primary">{c.crm_call.outcome.replace("_", " ")}</Badge>}</dd></>}
            </dl>
            {c.recording === "yes" ? (src ? <audio controls autoPlay src={src} style={{ width: "100%" }} /> : <div><button className="btn btn-primary" onClick={play}>▶ Play the recording</button></div>) : <div className="muted small">No recording for this call.</div>}
          </>
        )}
      </div>
    </Modal>
  );
}
