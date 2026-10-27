import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { useAuth } from "../auth";
import { useScope } from "../scope";
import { Badge, Empty, ErrorBox, Field, Icon, Modal, PageHead, useDebounced } from "../components/ui";

export const CAMPAIGN_STATUS = { draft: ["draft", "Draft"], active: ["active", "Active"], paused: ["submitted", "Paused"], closed: ["draft", "Closed"] };

export function CampaignStatus({ status }) {
  const [cls, label] = CAMPAIGN_STATUS[status] || ["draft", status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export const fmtDay = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "—");

const TABS = [["", "All"], ["draft", "Draft"], ["active", "Active"], ["paused", "Paused"], ["closed", "Closed"]];

export default function Campaigns() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const staff = user.user_type === "staff";
  const [clients, setClients] = useState([]);
  const { clientId, setClientId } = useScope();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [data, setData] = useState({ items: [], counts: {}, can_manage: false });
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => { api.get("/campaigns/clients").then((r) => setClients(r.data)).catch((e) => setError(errorMessage(e))); }, []);

  const load = useCallback(() => {
    api.get("/campaigns", { params: { client_id: clientId || undefined, status: status || undefined, q: dq || undefined } })
      .then((r) => { setData(r.data); setError(""); }).catch((e) => setError(errorMessage(e)));
  }, [clientId, status, dq]);
  useEffect(load, [load]);

  const total = Object.values(data.counts).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHead title="Campaigns" sub="Outbound calling campaigns. Each campaign has its own tagging form.">
        {data.can_manage && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            <span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Create campaign
          </button>
        )}
      </PageHead>

      <div className="card">
        <div className="tabs" style={{ padding: "0 14px", marginBottom: 0 }}>
          {TABS.map(([k, l]) => (
            <button key={k} className={`tab ${status === k ? "active" : ""}`} onClick={() => setStatus(k)}>
              {l} <span className="muted small">{k ? data.counts[k] ?? 0 : total}</span>
            </button>
          ))}
        </div>
        <div className="row wrap" style={{ padding: 14, borderBottom: "1px solid var(--border)" }}>
          <input style={{ maxWidth: 260 }} placeholder="Search campaign name…" value={q} onChange={(e) => setQ(e.target.value)} />
          {staff && (
            <select style={{ maxWidth: 260 }} value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">All clients</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </div>
        <ErrorBox error={error} />
        {data.items.length === 0 ? <Empty>No campaigns yet.{data.can_manage ? " Click “Create campaign” to add the first one." : ""}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Campaign</th>{staff && <th>Client</th>}<th>Status</th><th>Dates</th><th>Tagging form</th></tr></thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} className="click" onClick={() => navigate(`/campaigns/${c.id}`)}>
                    <td><b>{c.name}</b><div className="small muted mono">{c.code}</div></td>
                    {staff && <td>{c.client_name}</td>}
                    <td><CampaignStatus status={c.status} /></td>
                    <td className="small">{fmtDay(c.start_date)} → {fmtDay(c.end_date)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {c.fields_count + c.scenarios_count === 0
                        ? <Link to={`/campaigns/${c.id}?tab=form`}><Badge tone="warn">Not set up: set up now</Badge></Link>
                        : <Link to={`/campaigns/${c.id}?tab=form`} style={{ color: "inherit" }}>{c.fields_count} fields · {c.scenarios_count} scenarios</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {creating && <CampaignModal clients={clients} staff={staff} onClose={() => setCreating(false)} onSaved={(c) => navigate(`/campaigns/${c.id}?tab=form`)} />}
    </>
  );
}

export function CampaignModal({ campaign, clients = [], staff, onClose, onSaved }) {
  const { clientId: preset } = useScope();
  const editing = !!campaign;
  const [f, setF] = useState({
    client_id: campaign?.client_id || (clients.length === 1 ? clients[0].id : (preset || "")), name: campaign?.name || "", code: campaign?.code || "",
    description: campaign?.description || "", start_date: campaign?.start_date || "", end_date: campaign?.end_date || "",
  });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(""); setErrors({});
    const body = { ...f, client_id: f.client_id ? Number(f.client_id) : null, code: f.code || null, description: f.description || null,
      start_date: f.start_date || null, end_date: f.end_date || null };
    try {
      const { data } = editing ? await api.put(`/campaigns/${campaign.id}`, body) : await api.post("/campaigns", body);
      onSaved(data);
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <Modal title={editing ? "Edit campaign" : "Create campaign"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="camp-form" disabled={busy}>{busy ? "Saving…" : editing ? "Save" : "Create"}</button></>}>
      <form id="camp-form" className="stack" onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          {staff && !editing && (
            <Field label="Client *" error={errors.client_id} full>
              <select value={f.client_id} onChange={set("client_id")}>
                <option value="">Select a client…</option>
                {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          )}
          <Field label="Campaign name *" error={errors.name} full><input value={f.name} onChange={set("name")} autoFocus placeholder="e.g. Renewal Calls Nov 2026" /></Field>
          <Field label="Code" error={errors.code} hint="Leave empty to generate one (CMP001, CMP002 …)"><input className="mono" value={f.code} onChange={set("code")} /></Field>
          <span />
          <Field label="Start date" error={errors.start_date}><input type="date" value={f.start_date} onChange={set("start_date")} /></Field>
          <Field label="End date" error={errors.end_date}><input type="date" value={f.end_date} onChange={set("end_date")} /></Field>
          <Field label="Description" full><textarea value={f.description} onChange={set("description")} style={{ minHeight: 70 }} /></Field>
        </div>
      </form>
    </Modal>
  );
}
