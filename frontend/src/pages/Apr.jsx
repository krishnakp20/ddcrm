import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { Empty, ErrorBox, PageHead, Pager, Spinner } from "../components/ui";
import { useScope } from "../scope";

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const ago = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d; };
const PRESETS = [["Yesterday", () => [iso(ago(1)), iso(ago(1))]], ["Today", () => [iso(new Date()), iso(new Date())]], ["Last 7 days", () => [iso(ago(6)), iso(new Date())]], ["Last 30 days", () => [iso(ago(29)), iso(new Date())]],
  ["This month", () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth(), 1)), iso(n)]; }]];
const hms = (s) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

/** Agent performance: calls, handle time, login and breaks per agent per day, from the dialer's agent log. */
export default function Apr() {
  const { clientId } = useScope();
  const [range, setRange] = useState(PRESETS[2][1]());
  const [preset, setPreset] = useState("Last 7 days");
  const [group, setGroup] = useState("day");
  const [agent, setAgent] = useState("");
  const [serverId, setServerId] = useState("");
  const [servers, setServers] = useState([]);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const query = () => ({ date_from: range[0], date_to: range[1], client_id: clientId || undefined, agent: agent || undefined, server_id: serverId || undefined, group });
  useEffect(() => { api.get("/dialer/servers").then((r) => setServers(r.data)).catch(() => {}); }, []);
  useEffect(() => setPage(1), [range, group, agent, serverId, clientId]);
  const load = useCallback(() => {
    setData(null); setError("");
    api.get("/apr", { params: { ...query(), page } }).then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
  }, [range, group, agent, serverId, clientId, page]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  async function download() {
    setBusy(true);
    try {
      const r = await api.get("/apr/export", { params: query(), responseType: "blob" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = `apr_${range[0]}_${range[1]}.csv`; document.body.appendChild(a); a.click(); a.remove();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHead title="Agent performance (APR)" sub="From the dialer's agent log. Login is every second the agent was logged in; utilization is talk time divided by login.">
        <button className="btn btn-primary" disabled={busy || !data} onClick={download}>{busy ? "Preparing…" : "Download CSV"}</button>
      </PageHead>
      <div className="card card-pad row wrap" style={{ marginBottom: 12, gap: 8 }}>
        <div className="seg">{PRESETS.map(([l, fn]) => <button key={l} className={preset === l ? "on" : ""} onClick={() => { setPreset(l); setRange(fn()); }}>{l}</button>)}</div>
        <input type="date" style={{ width: 150 }} value={range[0]} max={range[1]} onChange={(e) => { setPreset(""); setRange([e.target.value, range[1]]); }} aria-label="From" />
        <span className="muted">to</span>
        <input type="date" style={{ width: 150 }} value={range[1]} min={range[0]} onChange={(e) => { setPreset(""); setRange([range[0], e.target.value]); }} aria-label="To" />
        <select style={{ width: 170 }} value={group} onChange={(e) => setGroup(e.target.value)}><option value="day">One row per agent per day</option><option value="agent">One row per agent (total)</option></select>
        <input style={{ width: 140 }} placeholder="Agent id" value={agent} onChange={(e) => setAgent(e.target.value)} />
        {servers.length > 1 && <select style={{ width: 150 }} value={serverId} onChange={(e) => setServerId(e.target.value)}><option value="">All servers</option>{servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="kpi-strip" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
            <div className="kpi"><div className="kpi-label">Agents</div><div className="kpi-value">{data.summary.agents}</div></div>
            <div className="kpi"><div className="kpi-label">Calls</div><div className="kpi-value">{data.summary.calls}</div></div>
            <div className="kpi"><div className="kpi-label">Talk time</div><div className="kpi-value">{hms(data.summary.talk)}</div></div>
            <div className="kpi"><div className="kpi-label">Utilization</div><div className="kpi-value">{data.summary.utilization}%</div></div>
          </div>
          <div className="card">
            {data.rows.length === 0 ? <Empty>No agent activity for this range.</Empty> : (
              <div className="table-wrap">
                <table>
                  <thead><tr>{data.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                  <tbody>{data.rows.map((r, i) => <tr key={i}>{data.columns.map((c) => <td key={c.key}>{data.time_keys.includes(c.key) ? hms(r[c.key]) : c.key === "agent" ? <b className="mono">{r.agent}</b> : r[c.key]}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
            <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </div>
        </>
      )}
    </>
  );
}
