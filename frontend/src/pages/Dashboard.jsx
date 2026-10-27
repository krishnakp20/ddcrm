import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import api from "../api";
import { useAuth } from "../auth";
import { useScope } from "../scope";
import OpsBoard from "../components/OpsBoard";
import { ClientStatus, CompanyAvatar, Empty, Icon, PageHead, Spinner, fmtDateTime } from "../components/ui";

export default function Dashboard() {
  const { user, can } = useAuth();
  const [data, setData] = useState(null);
  const { clientId, client: scoped } = useScope();
  const [period, setPeriod] = useState(1);
  const goAgent = user.user_type === "agent" && can("calls.work");

  useEffect(() => { if (!goAgent) api.get("/dashboard", { params: { days: period, client_id: clientId || undefined } }).then((r) => setData(r.data)); }, [goAgent, period, clientId]);
  if (goAgent) return <Navigate to="/agent" replace />;
  if (!data) return <Spinner />;

  if (data.scope === "client") {
    const p = can("profile.manage") ? data.profile : null;
    return (
      <>
        <PageHead title={`Welcome, ${user.name.split(" ")[0]}`} sub={user.client?.name || "DialDesk"}>
          {p && !p.complete && <Link className="btn btn-primary" to="/profile">Complete your profile</Link>}
        </PageHead>
        {data.ops && <OpsBoard ops={data.ops} period={period} setPeriod={setPeriod} showClients={false} activeCampaigns={data.active_campaigns} />}
        <div className="card card-pad row" style={{ gap: 18, alignItems: "flex-start", marginTop: 16 }}>
          <CompanyAvatar name={user.client?.name || "DialDesk"} logo={user.client?.logo_url} large />
          <div className="grow">
            <h3>Your DialDesk account is active</h3>
            <p className="muted" style={{ margin: "4px 0 14px" }}>
              {user.client ? `Client code ${user.client.code}. ` : ""}{user.role_name} · {user.department || "no department"}. Campaigns, calls and reports will appear here as your account is set up.
            </p>
            {p && (
              <>
                <div className="row spread small" style={{ marginBottom: 6 }}><b>Company profile</b><span>{p.percent}% complete</span></div>
                <div style={{ height: 8, borderRadius: 6, background: "#eef2f7" }}>
                  <div style={{ height: 8, borderRadius: 6, background: "var(--brand-green)", width: `${p.percent}%` }} />
                </div>
                <div className="stack" style={{ marginTop: 14, gap: 6 }}>
                  {p.items.map((i) => (
                    <div key={i.label} className="row small" style={{ color: i.done ? "var(--success)" : "var(--muted)" }}>
                      <span>{i.done ? "✓" : "○"}</span> {i.label}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </>
    );
  }

  const c = data.counts;
  const cards = [
    { label: "Waiting for review", value: data.pending_review, icon: "clock", tone: "tone-yellow", to: "/clients?status=submitted" },
    { label: "Active clients", value: c.active, icon: "check", tone: "tone-green", to: "/clients?status=active" },
    { label: "Documents to review", value: data.docs_to_review, icon: "alert", tone: "tone-red", to: "/clients?status=active" },
    { label: "Plans to approve", value: data.plans_to_approve, icon: "plans", tone: "tone-teal", to: "/plans?status=pending" },
  ];

  return (
    <>
      <PageHead title={scoped ? scoped.name : `Welcome, ${user.name.split(" ")[0]}`} sub={scoped ? `Showing ${scoped.name} only · ${scoped.code}` : "Here is what needs your attention today"}>
        {scoped && <Link className="btn" to={`/clients/${scoped.id}`}>Open client page</Link>}
        <Link className="btn btn-primary" to="/clients?add=1"><span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add client</Link>
      </PageHead>

      {!scoped && <div className="grid cols-4">
        {cards.map((s) => (
          <Link key={s.label} to={s.to} className="card stat-card" style={{ color: "inherit", textDecoration: "none" }}>
            <span className={`ico ${s.tone}`}><Icon name={s.icon} /></span>
            <div>
              <div className="num">{s.value}</div>
              <div className="muted small">{s.label}</div>
            </div>
          </Link>
        ))}
      </div>}

      {!scoped && data.failed_messages > 0 && (
        <div className="alert warn" style={{ marginTop: 16 }}>
          {data.failed_messages} message(s) could not be sent. <Link to="/settings?tab=log">Open the notification log</Link>.
        </div>
      )}

      <OpsBoard ops={data.ops} period={period} setPeriod={setPeriod} showClients={!scoped} activeCampaigns={data.active_campaigns} />

      {!scoped && <><div className="section-title" style={{ margin: "18px 0 10px" }}>Client onboarding</div>
      <div className="grid cols-2" style={{ gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)" }}>
        <div className="card">
          <div className="card-head"><h3>Waiting for you</h3><Link to="/clients" className="small">View all</Link></div>
          {data.waiting.length === 0 ? <Empty>Nothing waiting. New registrations from the login page appear here.</Empty> : data.waiting.map((w) => (
            <Link key={w.id} to={`/clients/${w.id}`} className="queue-item" style={{ color: "inherit", textDecoration: "none" }}>
              <div className="row grow">
                <CompanyAvatar name={w.company_name} />
                <div className="grow">
                  <b>{w.company_name}</b>
                  <div className="small muted">{w.contact_name || "No contact yet"} · registered {fmtDateTime(w.created_at)}{w.source === "admin" ? " by admin" : ""}</div>
                </div>
              </div>
              <ClientStatus status={w.status} />
            </Link>
          ))}
        </div>
        <div className="card">
          <div className="card-head"><h3>Recently activated</h3></div>
          {data.recent_active.length === 0 ? <Empty>No active clients yet.</Empty> : data.recent_active.map((a) => (
            <Link key={a.id} to={`/clients/${a.id}`} className="queue-item" style={{ color: "inherit", textDecoration: "none" }}>
              <div className="row grow">
                <CompanyAvatar name={a.company_name} logo={a.logo_url} />
                <div><b>{a.company_name}</b><div className="small muted">{a.code} · profile {a.profile_percent}% · {fmtDateTime(a.activated_at)}</div></div>
              </div>
            </Link>
          ))}
        </div>
      </div></>}
    </>
  );
}
