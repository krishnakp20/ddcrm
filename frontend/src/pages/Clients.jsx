import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { AddClientModal } from "../components/BasicClientForm";
import {
  Badge, ClientStatus, CompanyAvatar, Empty, ErrorBox, Icon, PageHead, fmtDateTime, useDebounced,
} from "../components/ui";

const TABS = [["", "All"], ["submitted", "Waiting for review"], ["active", "Active"], ["suspended", "Suspended"], ["rejected", "Rejected"]];

export default function Clients() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [data, setData] = useState({ items: [], counts: {} });
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(params.get("add") === "1");

  const load = useCallback(() => {
    api.get("/clients", { params: { status: status || undefined, q: dq || undefined } })
      .then((r) => { setData(r.data); setError(""); })
      .catch((e) => setError(errorMessage(e)));
  }, [status, dq]);
  useEffect(load, [load]);

  const total = Object.values(data.counts).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHead title="Clients" sub="Review new registrations and manage your clients">
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          <span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add client
        </button>
      </PageHead>

      <div className="card">
        <div className="tabs" style={{ padding: "0 14px", marginBottom: 0 }}>
          {TABS.map(([k, label]) => (
            <button key={k} className={`tab ${status === k ? "active" : ""}`} onClick={() => setParams(k ? { status: k } : {})}>
              {label} <span className="muted small">{k ? data.counts[k] ?? 0 : total}</span>
            </button>
          ))}
        </div>
        <div style={{ padding: 14, borderBottom: "1px solid var(--border)" }}>
          <input style={{ maxWidth: 340 }} placeholder="Search company, GSTIN or client code…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <ErrorBox error={error} />
        {data.items.length === 0 ? <Empty>No clients here yet. Clients can register from the login page, or you can add one.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Company</th><th>Contact</th><th>GSTIN</th><th>Plan</th><th>Profile</th><th>Status</th><th>Registered</th></tr></thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} className="click" onClick={() => navigate(`/clients/${c.id}`)}>
                    <td>
                      <div className="row">
                        <CompanyAvatar name={c.company_name} logo={c.logo_url} />
                        <div><b>{c.company_name}</b><div className="small muted">{c.code || "No code yet"}{c.city ? ` · ${c.city}` : ""}</div></div>
                      </div>
                    </td>
                    <td>{c.contact_name || "—"}<div className="small muted">{c.contact_mobile || c.contact_email || ""}</div></td>
                    <td className="mono">{c.gstin || "—"}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {c.plan_name ? (
                        <div><b>{c.plan_name}</b>
                          <div className="small muted">{c.next_plan ? `then ${c.next_plan} from ${c.next_plan_from}` : `since ${c.plan_from}`}</div></div>
                      ) : c.status === "active" || c.status === "suspended" ? (
                        can("plans.assign") ? <button className="btn btn-sm btn-primary" onClick={() => navigate(`/clients/${c.id}?tab=plan`)}>Give plan</button> : <span className="muted">No plan</span>
                      ) : <span className="muted">—</span>}
                    </td>
                    <td>
                      {c.status === "active" || c.status === "suspended" ? (
                        <div className="row gap-sm">
                          <span className="small">{c.profile_percent}%</span>
                          {c.pending_docs > 0 && <Badge tone="warn">{c.pending_docs} doc to review</Badge>}
                        </div>
                      ) : <span className="muted">—</span>}
                    </td>
                    <td><ClientStatus status={c.status} /></td>
                    <td className="small muted">{fmtDateTime(c.submitted_at || c.created_at)}{c.source === "admin" ? " · by admin" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {adding && (
        <AddClientModal
          onClose={() => { setAdding(false); if (params.get("add")) setParams({}); }}
          onDone={(r) => navigate(`/clients/${r.id}`)}
        />
      )}
    </>
  );
}
