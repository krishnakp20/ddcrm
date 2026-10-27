import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import CampaignData from "../components/CampaignData";
import DialerListPanel from "../components/DialerListPanel";
import { CampaignAgents, CampaignDialerIds } from "../components/DialerAdmin";
import FormWorkspace from "../components/forms/FormWorkspace";
import { ErrorBox, PageHead, Spinner, useToast } from "../components/ui";
import { CampaignModal, CampaignStatus, fmtDay } from "./Campaigns";

const ACTION = {
  active: ["Activate", "btn btn-success"], paused: ["Pause", "btn"], closed: ["Close campaign", "btn btn-danger"],
};

export default function CampaignDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, can } = useAuth();
  const staff = user.user_type === "staff";
  const [params, setParams] = useSearchParams();
  const [c, setC] = useState(null);
  const [clients, setClients] = useState([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState("");
  const [toast, setToast, toastEl] = useToast();

  const section = ["form", "agents", "data"].includes(params.get("tab")) ? params.get("tab") : "details";
  const formTab = ["fields", "scenarios", "lists", "preview"].includes(params.get("ftab")) ? params.get("ftab") : "fields";

  const load = useCallback(() => api.get(`/campaigns/${id}`).then((r) => setC(r.data)).catch((e) => setError(errorMessage(e))), [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/campaigns/clients").then((r) => setClients(r.data)).catch(() => {}); }, []);

  if (error && !c) return <ErrorBox error={error} />;
  if (!c) return <Spinner />;

  async function setStatus(status) {
    setBusy(status); setError("");
    try { await api.post(`/campaigns/${id}/status`, { status }); setToast("Status updated"); await load(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }

  async function remove() {
    if (!window.confirm(`Delete the draft campaign “${c.name}” and its tagging form?`)) return;
    try { await api.delete(`/campaigns/${id}`); navigate("/campaigns"); } catch (e) { setError(errorMessage(e)); }
  }

  const go = (patch) => setParams({ tab: section, ftab: formTab, ...patch });
  const canManage = c.can_manage;
  const hasForm = c.fields_count + c.scenarios_count > 0;

  return (
    <>
      <Link to="/campaigns" className="small">← All campaigns</Link>
      <PageHead title={c.name} sub={`${c.client_name} · ${c.code}`}>
        <CampaignStatus status={c.status} />
        {canManage && c.next_statuses.map((s) => (
          <button key={s} className={ACTION[s][0] === "Pause" ? "btn" : ACTION[s][1]} disabled={!!busy}
            onClick={() => (s === "closed" ? window.confirm("Close this campaign? You can reopen it as paused later.") && setStatus(s) : setStatus(s))}>
            {busy === s ? "Please wait…" : c.status === "closed" && s === "paused" ? "Reopen" : ACTION[s][0]}
          </button>
        ))}
      </PageHead>
      <ErrorBox error={error} />

      <div className="tabs">
        {[["details", "Details"], ["form", "Tagging form"], ["agents", "Agents"], ["data", "Data"]].map(([k, l]) => (
          <button key={k} className={`tab ${section === k ? "active" : ""}`} onClick={() => go({ tab: k })}>
            {l}{k === "form" && !hasForm && <span className="badge warn" style={{ marginLeft: 8 }}>to do</span>}
          </button>
        ))}
      </div>

      {section === "details" && (
        <div className="stack">
          <div className="card card-pad">
            <div className="row spread" style={{ marginBottom: 12 }}>
              <div className="section-title" style={{ margin: 0 }}>Campaign</div>
              {canManage && <button className="btn btn-sm" onClick={() => setEditing(true)}>Edit</button>}
            </div>
            <dl className="kv" style={{ gridTemplateColumns: "130px minmax(0, 1fr)" }}>
              <dt>Client</dt><dd>{c.client_name}</dd>
              <dt>Code</dt><dd className="mono">{c.code}</dd>
              <dt>Dates</dt><dd>{fmtDay(c.start_date)} → {fmtDay(c.end_date)}</dd>
              <dt>Description</dt><dd>{c.description || "—"}</dd>
              <dt>Tagging form</dt><dd>{hasForm ? `${c.fields_count} fields, ${c.scenarios_count} scenarios` : "Not set up yet"}</dd>
            </dl>
          </div>
          {!hasForm && (
            <div className="alert warn">
              This campaign has no tagging form yet, so it cannot be activated. <button className="btn btn-sm" onClick={() => go({ tab: "form" })}>Set up the form</button>
            </div>
          )}
          <CampaignDialerIds campaign={c} canManage={can("clients.manage")} />
          {canManage && c.status === "draft" && <div><button className="btn btn-ghost" style={{ color: "var(--danger)" }} onClick={remove}>Delete this draft campaign</button></div>}
        </div>
      )}

      {section === "data" && (
        <>
          <CampaignData campaign={c} canManage={canManage} />
          {can("dialer.manage") && <div style={{ marginTop: 12 }}><DialerListPanel campaign={c} /></div>}
        </>
      )}

      {section === "agents" && <CampaignAgents campaign={c} canManage={canManage} />}

      {section === "form" && (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            This is the form agents fill in when a call of <b>{c.name}</b> connects. It belongs to this campaign only; use the copy button to start from another campaign's form.
          </p>
          <FormWorkspace key={c.id} clientId={c.client_id} formKey={`campaign-${c.id}`} staff={staff} tab={formTab}
            onTab={(t) => go({ ftab: t })} clients={clients} ownClientId={user.client_id}
            onLoaded={(cfg) => {
              const count = (nodes) => nodes.reduce((n, x) => n + 1 + count(x.children), 0);
              setC((prev) => (prev ? { ...prev, fields_count: cfg.fields.length, scenarios_count: count(cfg.scenarios) } : prev));
            }} />
        </>
      )}

      {editing && <CampaignModal campaign={c} clients={clients} staff={staff} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); setToast("Saved"); load(); }} />}
      {toastEl}
    </>
  );
}
