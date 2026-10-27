import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { Badge, Empty, ErrorBox, Modal, PageHead, Pager, Spinner } from "../components/ui";
import { useScope } from "../scope";

const TABS = [["calls", "Calls"], ["tickets", "Tickets"], ["agents", "Agents"], ["campaigns", "Campaigns"]];
const OUTCOMES = [["connected", "Connected"], ["converted", "Converted"], ["callback", "Call back"], ["closed", "Closed"], ["not_connected", "Not connected"], ["dnc", "Do not call"]];
const STATUS = { calls: [["tagged", "Tagged"], ["skipped", "Skipped"], ["open", "Not tagged"]], tickets: [["open", "Open"], ["in_progress", "In progress"], ["pending", "Pending"], ["resolved", "Resolved"], ["closed", "Closed"]] };

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d; };
const PRESETS = [
  ["Today", () => [iso(new Date()), iso(new Date())]],
  ["Yesterday", () => [iso(daysAgo(1)), iso(daysAgo(1))]],
  ["Last 7 days", () => [iso(daysAgo(6)), iso(new Date())]],
  ["Last 30 days", () => [iso(daysAgo(29)), iso(new Date())]],
  ["This month", () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth(), 1)), iso(n)]; }],
];

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const name = TABS.some(([k]) => k === params.get("r")) ? params.get("r") : "calls";
  const { clientId } = useScope();
  const [range, setRange] = useState(PRESETS[2][1]());
  const [preset, setPreset] = useState("Last 7 days");
  const [f, setF] = useState({ mode: "", status: "", outcome: "", priority: "", campaign_id: "" });
  const [campaigns, setCampaigns] = useState([]);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [call, setCall] = useState(null);   // the call whose full record is open

  const query = () => ({ date_from: range[0], date_to: range[1], client_id: clientId || undefined, mode: f.mode || undefined, status: f.status || undefined,
    outcome: f.outcome || undefined, priority: f.priority || undefined, campaign_id: f.campaign_id || undefined });

  useEffect(() => { api.get("/campaigns", { params: { client_id: clientId || undefined } }).then((r) => setCampaigns(r.data.items || r.data)).catch(() => setCampaigns([])); setF((p) => ({ ...p, campaign_id: "" })); }, [clientId]);
  useEffect(() => { setPage(1); setF((p) => ({ ...p, mode: "", status: "", outcome: "", priority: "" })); }, [name]);
  useEffect(() => { setPage(1); }, [range, f, clientId]);

  const load = useCallback(() => {
    setData(null); setError("");
    api.get(`/reports/${name}`, { params: { ...query(), page } }).then((r) => setData({ ...r.data, forReport: name })).catch((e) => setError(errorMessage(e)));
  }, [name, range, f, clientId, page]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  async function openCall(id) {
    try { setCall((await api.get(`/reports/calls/${id}`)).data); } catch (e) { setError(errorMessage(e)); }
  }

  async function download() {
    setBusy(true);
    try {
      const r = await api.get(`/reports/${name}/export`, { params: query(), responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = `${name}_${range[0]}_${range[1]}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  const sel = (key, label, options) => (
    <select style={{ width: 150 }} value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })} aria-label={label}>
      <option value="">{label}</option>{options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );

  return (
    <>
      <PageHead title="Reports" sub="Calls, tickets, agents and campaigns for any date range. Download any table as a CSV file for Excel.">
        <button className="btn btn-primary" disabled={busy || !data} onClick={download}>{busy ? "Preparing…" : "Download CSV"}</button>
      </PageHead>

      <div className="tabs">{TABS.map(([k, l]) => <button key={k} className={`tab ${name === k ? "active" : ""}`} onClick={() => setParams({ r: k })}>{l}</button>)}</div>

      <div className="card card-pad row wrap" style={{ marginBottom: 12, gap: 8 }}>
        <div className="seg">
          {PRESETS.map(([l, fn]) => <button key={l} className={preset === l ? "on" : ""} onClick={() => { setPreset(l); setRange(fn()); }}>{l}</button>)}
        </div>
        <input type="date" style={{ width: 150 }} value={range[0]} max={range[1]} onChange={(e) => { setPreset(""); setRange([e.target.value, range[1]]); }} aria-label="From" />
        <span className="muted">to</span>
        <input type="date" style={{ width: 150 }} value={range[1]} min={range[0]} onChange={(e) => { setPreset(""); setRange([range[0], e.target.value]); }} aria-label="To" />
        {name === "calls" && <>{sel("mode", "All modes", [["inbound", "Inbound"], ["pd", "Predictive"], ["manual", "Manual"]])}{sel("status", "Any status", STATUS.calls)}{sel("outcome", "Any outcome", OUTCOMES)}</>}
        {name === "tickets" && <>{sel("status", "Any status", STATUS.tickets)}{sel("priority", "Any priority", [["urgent", "Urgent"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]])}</>}
        {(name === "calls" || name === "campaigns") && campaigns.length > 0 && sel("campaign_id", "All campaigns", campaigns.map((c) => [c.id, c.name]))}
      </div>

      <ErrorBox error={error} />
      {(!data || data.forReport !== name) && !error && <Spinner />}
      {data && data.forReport === name && (
        <>
          {name === "calls" && !data.form_columns && (
            <div className="alert info" style={{ marginBottom: 12 }}>Choose a client in the top bar to see that client's form questions (the old Field1, Field2 … with their names) as extra columns, here and in the CSV. Click any call to see all its details.</div>
          )}
          <Summary name={name} s={data.summary} />
          <div className="card">
            <div className="card-head"><h3>{TABS.find(([k]) => k === name)[1]}</h3><span className="small muted">{data.total} row(s) · {data.from} to {data.to}</span></div>
            {data.rows.length === 0 ? <Empty>No data for this range and filter.</Empty> : (
              <div className="table-wrap">
                <table>
                  <thead><tr>{data.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                  <tbody>{data.rows.map((r, i) => <tr key={i} className={name === "calls" ? "click" : ""} onClick={name === "calls" ? () => openCall(r.id) : undefined}>{data.columns.map((c) => <td key={c.key} className={["phone", "mobile", "number"].includes(c.key) ? "mono" : ""} style={["notes", "subject", "scenario"].includes(c.key) ? { maxWidth: 260 } : undefined}>{r[c.key] ?? ""}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
            <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </div>
        </>
      )}
      {call && <CallModal c={call} onClose={() => setCall(null)} />}
    </>
  );
}

function CallModal({ c, onClose }) {
  return (
    <Modal title={`Call ${c.id}${c.call_id ? ` · ${c.call_id}` : ""}`} onClose={onClose} wide footer={<button className="btn" onClick={onClose}>Close</button>}>
      <div className="stack">
        <dl className="kv" style={{ gridTemplateColumns: "130px minmax(0, 1fr)" }}>
          <dt>Client</dt><dd>{c.client}</dd>
          <dt>Type</dt><dd>{c.campaign ? `${c.mode === "pd" ? "Predictive" : "Manual"} · ${c.campaign}` : c.mode === "manual" ? "Manual" : "Inbound"}</dd>
          <dt>Agent</dt><dd>{c.agent}</dd>
          <dt>Number</dt><dd className="mono">{c.phone}</dd>
          <dt>Started</dt><dd>{c.started_at}{c.tagged_at ? ` · tagged ${c.tagged_at}${c.minutes ? ` (${c.minutes} min)` : ""}` : ""}</dd>
          <dt>Status</dt><dd>{c.status}{c.outcome ? ` · ${c.outcome.replace("_", " ")}` : ""}</dd>
          <dt>Scenario</dt><dd>{c.scenario.length ? c.scenario.join(" › ") : "—"}</dd>
          {c.customer && <><dt>Customer</dt><dd>{c.customer.name} · <span className="mono">{c.customer.mobile}</span>{c.customer.email ? ` · ${c.customer.email}` : ""}{c.customer.city ? ` · ${c.customer.city}` : ""}</dd></>}
          {(c.notes || c.skip_reason) && <><dt>Notes</dt><dd style={{ whiteSpace: "pre-wrap" }}>{c.notes || c.skip_reason}</dd></>}
        </dl>
        <div>
          <div className="section-title">Everything filled in on the form</div>
          {c.answers.length === 0 ? <div className="muted small">No form answers were saved for this call.</div> : (
            <dl className="kv" style={{ gridTemplateColumns: "200px minmax(0, 1fr)" }}>
              {c.answers.map((a) => <div key={a.label} style={{ display: "contents" }}><dt>{a.label}</dt><dd style={{ whiteSpace: "pre-wrap" }}>{a.value}</dd></div>)}
            </dl>
          )}
        </div>
        {c.tickets.length > 0 && (
          <div>
            <div className="section-title">Tickets of this customer</div>
            <div className="row wrap">{c.tickets.map((t) => <a key={t.id} className="btn btn-sm" href={`/tickets/${t.id}`}>{t.number} · {t.subject} <Badge>{t.status.replace("_", " ")}</Badge></a>)}</div>
          </div>
        )}
        {c.other_calls.length > 0 && (
          <div>
            <div className="section-title">Other calls from this customer</div>
            {c.other_calls.map((o) => <div key={o.id} className="small">{o.when} · {o.mode === "pd" ? "predictive" : o.mode} · {o.scenario || "no scenario"}</div>)}
          </div>
        )}
      </div>
    </Modal>
  );
}

function Tile({ label, value, sub, tone }) {
  return <div className="kpi"><div className="kpi-label">{label}</div><div className="kpi-value" style={tone ? { color: tone } : undefined}>{value}</div>{sub && <div className="kpi-sub">{sub}</div>}</div>;
}

function Summary({ name, s }) {
  if (!s) return null;
  if (name === "calls") {
    return (
      <div className="kpi-strip" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
        <Tile label="Calls" value={s.total} sub={`${s.inbound} in · ${s.pd} PD · ${s.manual} manual`} />
        <Tile label="Tagged" value={s.tagged} sub={`${s.tag_rate}% of calls`} tone="var(--success)" />
        <Tile label="Skipped" value={s.skipped} tone={s.skipped ? "var(--danger)" : undefined} />
        <Tile label="Not tagged" value={s.open} tone={s.open ? "var(--warn)" : undefined} />
        <Tile label="Avg per call" value={`${s.avg_minutes} min`} sub={s.outcomes[0] ? `top outcome: ${s.outcomes[0].outcome}` : "call to tag"} />
      </div>
    );
  }
  return (
    <div className="kpi-strip" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))" }}>
      <Tile label="Tickets" value={s.total} sub={s.by_priority.filter((p) => p.count).map((p) => `${p.count} ${p.label}`).join(" · ")} />
      <Tile label="Still open" value={s.open} tone={s.open ? "var(--warn)" : undefined} />
      <Tile label="Resolved" value={s.resolved} tone="var(--success)" />
      <Tile label="Overdue now" value={s.overdue} tone={s.overdue ? "var(--danger)" : undefined} />
      <Tile label="SLA met" value={s.sla_met_pct == null ? "–" : `${s.sla_met_pct}%`} sub={`avg ${s.avg_hours} h to resolve`} />
    </div>
  );
}
