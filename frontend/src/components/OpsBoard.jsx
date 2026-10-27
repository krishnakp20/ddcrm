import { Link } from "react-router-dom";
import { Badge, Empty, fmtDuration } from "./ui";

const OUTCOME = {
  connected: ["Connected", "#2f8f5b"], converted: ["Converted", "#779520"], callback: ["Call back", "#e0a800"],
  closed: ["Closed", "#64748b"], not_connected: ["Not connected", "#c4001f"], dnc: ["Do not call", "#7c2d3a"], none: ["No outcome", "#94a3b8"],
};
const PERIODS = [[1, "Today"], [7, "7 days"], [30, "30 days"]];

function Kpi({ label, value, sub, tone }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={tone ? { color: tone } : undefined}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

/** Vertical bars drawn with plain CSS: one bar per hour (today) or per day. */
function Bars({ items, height = 120 }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="bars" style={{ height }}>
      {items.map((i) => (
        <div key={i.label} className="bar-col" title={`${i.title || i.label}: ${i.value}`}>
          <div className="bar-track"><div className="bar" style={{ height: `${(i.value / max) * 100}%` }} /></div>
          <span className="bar-label">{i.label}</span>
        </div>
      ))}
    </div>
  );
}

function HBars({ rows, color = "var(--primary)" }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div key={r.label} className="hbar">
          <span className="hbar-name">{r.label}</span>
          <span className="hbar-track"><i style={{ width: `${(r.value / max) * 100}%`, background: r.color || color }} /></span>
          <b>{r.value}</b>
        </div>
      ))}
    </div>
  );
}

/** The call-centre part of the dashboard, shared by DialDesk staff (all clients) and client users (their own). */
export default function OpsBoard({ ops, period, setPeriod, showClients, activeCampaigns }) {
  const k = ops.kpi;
  const today = ops.days === 1;
  const trend = today
    ? ops.hourly.map((v, h) => ({ label: h % 3 === 0 ? String(h) : "", title: `${h}:00`, value: v }))
    : ops.daily.map((d) => ({ label: ops.days === 7 ? d.date.slice(8) : (Number(d.date.slice(8)) % 5 === 0 ? d.date.slice(8) : ""), title: d.date, value: d.calls }));
  const total = Math.max(1, k.inbound + k.pd + k.manual);

  return (
    <>
      <div className="row spread wrap" style={{ margin: "18px 0 10px" }}>
        <div className="section-title" style={{ margin: 0 }}>Call centre</div>
        <div className="seg">
          {PERIODS.map(([d, l]) => <button key={d} className={period === d ? "on" : ""} onClick={() => setPeriod(d)}>{l}</button>)}
        </div>
      </div>

      <div className="kpi-strip">
        <Kpi label="Calls" value={k.calls} sub={`${k.inbound} in · ${k.pd} PD${k.manual ? ` · ${k.manual} manual` : ""}`} />
        <Kpi label="Tagged" value={k.tagged} sub={`${k.tag_rate}% of calls`} tone="var(--success)" />
        <Kpi label="Avg handling" value={k.avg_secs ? fmtDuration(k.avg_secs) : "–"} sub="call to tag" />
        <Kpi label="Awaiting tag" value={k.open} sub="open right now" tone={k.open ? "var(--warn)" : undefined} />
        <Kpi label="Skipped" value={k.skipped} sub="not tagged" tone={k.skipped ? "var(--danger)" : undefined} />
        <Kpi label="Agents active" value={k.agents} sub={`${activeCampaigns} active campaign${activeCampaigns === 1 ? "" : "s"}`} />
      </div>

      <div className="dash-grid">
        <div className="card">
          <div className="card-head"><h3>{today ? "Calls by hour" : "Calls by day"}</h3><span className="small muted">{k.calls} total</span></div>
          <div className="card-body">{k.calls === 0 ? <Empty>No calls in this period yet.</Empty> : <Bars items={trend} />}</div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Call outcomes</h3><span className="small muted">tagged calls</span></div>
          <div className="card-body">
            {ops.outcomes.length === 0 ? <div className="muted small">Outcomes appear once calls are tagged.</div> : (
              <HBars rows={ops.outcomes.map((o) => ({ label: (OUTCOME[o.outcome] || [o.outcome])[0], value: o.count, color: (OUTCOME[o.outcome] || [])[1] }))} />
            )}
            <div className="split" title="Inbound / predictive / manual">
              <i style={{ width: `${(k.inbound / total) * 100}%`, background: "var(--primary)" }} />
              <i style={{ width: `${(k.pd / total) * 100}%`, background: "var(--brand-yellow)" }} />
              <i style={{ width: `${(k.manual / total) * 100}%`, background: "var(--brand-green)" }} />
            </div>
            <div className="row small muted" style={{ gap: 14, marginTop: 6 }}>
              <span><span className="dot" style={{ color: "var(--primary)" }} /> Inbound</span>
              <span><span className="dot" style={{ color: "var(--brand-yellow)" }} /> Predictive</span>
              <span><span className="dot" style={{ color: "var(--brand-green)" }} /> Manual</span>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Live: waiting to be tagged</h3><Badge tone={ops.live.length ? "warn" : ""}>{ops.live.length}</Badge></div>
          {ops.live.length === 0 ? <Empty>No open calls. Everything is tagged.</Empty> : ops.live.slice(0, 6).map((c) => (
            <div key={c.id} className="queue-item">
              <div className="grow"><b>{c.agent}</b><div className="small muted">{c.client} · {c.phone}</div></div>
              <span className="small muted">{c.mode === "pd" ? "PD" : c.mode}</span>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="card-head"><h3>Top agents</h3></div>
          {ops.top_agents.length === 0 ? <Empty>No agent activity yet.</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Agent</th><th>Calls</th><th>Tagged</th><th>Avg handling</th></tr></thead>
                <tbody>
                  {ops.top_agents.map((a) => (
                    <tr key={a.name}><td><b>{a.name}</b></td><td>{a.calls}</td><td>{a.tagged}</td><td>{a.avg_secs ? fmtDuration(a.avg_secs) : "–"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>{showClients ? "Calls by client" : "Calls by campaign"}</h3></div>
          <div className="card-body">
            {(() => {
              const rows = (showClients ? ops.by_client : ops.by_campaign);
              return rows.length === 0 ? <div className="muted small">Nothing yet.</div> : <HBars rows={rows.map((r) => ({ label: r.name, value: r.calls }))} />;
            })()}
          </div>
        </div>

        {showClients && (
          <div className="card">
            <div className="card-head"><h3>Calls by campaign</h3><Link to="/campaigns" className="small">Campaigns</Link></div>
            <div className="card-body">
              {ops.by_campaign.length === 0 ? <div className="muted small">No outbound calls yet.</div> : <HBars color="var(--brand-green)" rows={ops.by_campaign.map((r) => ({ label: r.name, value: r.calls }))} />}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
