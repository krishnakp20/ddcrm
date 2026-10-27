import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, PageHead, Spinner, fmtDateTime } from "../components/ui";

/** The agent's home. Calls open here by themselves when the dialer connects them. */
export default function AgentHome() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [open, setOpen] = useState([]);
  const [error, setError] = useState("");

  const load = () => {
    api.get("/agent/home").then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
    api.get("/agent/calls/open").then((r) => setOpen(r.data)).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);

  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return <Spinner />;

  const nothing = data.clients.length === 0;
  return (
    <>
      <PageHead title={`Hello, ${user.name.split(" ")[0]}`} sub="Calls open here automatically when the dialer connects them to you." />

      {open.length > 0 && (
        <div className="alert warn" style={{ marginBottom: 16 }}>
          <b>You have {open.length} call{open.length === 1 ? "" : "s"} not tagged yet.</b> Finish {open.length === 1 ? "it" : "them"} before the next call.
          <div className="row wrap" style={{ marginTop: 8 }}>
            {open.map((c) => <Link key={c.id} className="btn btn-sm btn-primary" to={`/agent/call/${c.id}`}>{c.client_name} · {c.phone}</Link>)}
          </div>
        </div>
      )}

      <div className="grid cols-3" style={{ marginBottom: 16 }}>
        {[["Calls today", data.today.calls], ["Tagged", data.today.tagged], ["Waiting to be tagged", data.today.open]].map(([l, n]) => (
          <div key={l} className="card stat-card"><div><div className="num">{n}</div><div className="muted small">{l}</div></div></div>
        ))}
      </div>

      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <div className="card">
          <div className="card-head"><h3>Where you work</h3></div>
          {nothing ? <Empty>You are not allocated to any client yet. Ask your admin.</Empty> : (
            <div className="card-body stack">
              <div>
                <div className="section-title">Clients (inbound)</div>
                <div className="row wrap">{data.clients.map((c) => <Badge key={c.id} tone="primary">{c.name}</Badge>)}</div>
              </div>
              <div>
                <div className="row spread"><div className="section-title">Campaigns (outbound)</div><Link to="/agent/queue" className="small">Open work queue</Link></div>
                {data.campaigns.length === 0 ? <span className="muted small">No campaign allocated.</span> : data.campaigns.map((c) => (
                  <div key={c.id} className="row spread small" style={{ padding: "4px 0" }}>
                    <span>{c.name}</span>
                    <Badge tone={c.status === "active" ? "success" : "warn"}>{c.status}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>Recent calls</h3></div>
          {data.recent.length === 0 ? <Empty>No calls yet.</Empty> : data.recent.map((r) => (
            <Link key={r.id} to={`/agent/call/${r.id}`} className="queue-item" style={{ color: "inherit", textDecoration: "none" }}>
              <div className="grow">
                <b>{r.customer_name || r.phone}</b>
                <div className="small muted">{r.client_name} · {r.mode === "pd" ? "predictive" : r.mode} · {fmtDateTime(r.started_at)}</div>
              </div>
              <Badge tone={r.status === "tagged" ? "success" : r.status === "open" ? "warn" : ""}>{r.status === "open" ? "to tag" : r.status}</Badge>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
