import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { Badge, Empty, ErrorBox, Icon, PageHead, fmtDateTime, useDebounced } from "../components/ui";

export const rs = (v) => `Rs. ${Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 4 })}`;
export const MODE = { monthly: "Monthly", quarterly: "Quarterly", half_yearly: "Half yearly", yearly: "Yearly" };
export const PLAN_STATUS = { pending: "Waiting for approval", approved: "Approved", rejected: "Rejected", retired: "Retired" };
const TONE = { pending: "submitted", approved: "active", rejected: "rejected", retired: "draft" };

export function PlanStatus({ status }) {
  return <span className={`badge ${TONE[status]}`}>{PLAN_STATUS[status] || status}</span>;
}

const TABS = [["", "All"], ["pending", "Waiting for approval"], ["approved", "Approved"], ["rejected", "Rejected"], ["retired", "Retired"]];

export default function Plans() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [data, setData] = useState({ items: [], counts: {} });
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get("/plans", { params: { status: status || undefined, q: dq || undefined } })
      .then((r) => { setData(r.data); setError(""); }).catch((e) => setError(errorMessage(e)));
  }, [status, dq]);
  useEffect(load, [load]);
  const total = Object.values(data.counts).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHead title="Plans" sub="Price plans you can give to clients. A plan must be approved before it can be used.">
        <button className="btn btn-primary" onClick={() => navigate("/plans/new")}>
          <span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add plan
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
          <input style={{ maxWidth: 320 }} placeholder="Search plan name…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <ErrorBox error={error} />
        {data.items.length === 0 ? <Empty>No plans here yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Plan</th><th>Type</th><th>Billing period</th><th>Subscription</th><th>Setup fee</th><th>Status</th><th>Created</th></tr></thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id} className="click" onClick={() => navigate(`/plans/${p.id}`)}>
                    <td><b>{p.name}</b></td>
                    <td><Badge tone="primary">{p.plan_type}</Badge></td>
                    <td>{MODE[p.plan_mode]}</td>
                    <td>{rs(p.subscription_amount)}</td>
                    <td>{rs(p.setup_fee)}</td>
                    <td><PlanStatus status={p.status} /></td>
                    <td className="small muted">{fmtDateTime(p.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
