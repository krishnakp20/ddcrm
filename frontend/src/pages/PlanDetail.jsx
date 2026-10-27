import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { ErrorBox, Field, Modal, Spinner, fmtDateTime } from "../components/ui";
import { MODE, PlanStatus, rs } from "./Plans";

function show(f, v, rates) {
  if (f.kind === "bool") return v ? "Yes" : "No";
  if (f.kind === "pulse") return `${v} sec`;
  if (f.kind === "pct") return `${v}%`;
  if (f.kind === "int") return String(v);
  if (f.kind === "money") {
    const base = `${rs(v)}${f.unit && f.unit !== "Rs." ? f.unit.replace("Rs.", "") : ""}`;
    return f.pair ? `${base} · ${rs(rates[f.pair[1]])} per pulse` : base;
  }
  if (f.key === "plan_mode") return MODE[v];
  return v ? v.charAt(0).toUpperCase() + v.slice(1) : "—";
}

export default function PlanDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [plan, setPlan] = useState(null);
  const [schema, setSchema] = useState(null);
  const [error, setError] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => api.get(`/plans/${id}`).then((r) => setPlan(r.data)).catch((e) => setError(errorMessage(e))), [id]);
  useEffect(() => { load(); api.get("/plans/schema").then((r) => setSchema(r.data)); }, [load]);

  if (error && !plan) return <ErrorBox error={error} />;
  if (!plan || !schema) return <Spinner />;

  async function act(name, path, body, then) {
    setBusy(name); setError("");
    try {
      const { data } = await api.post(`/plans/${id}/${path}`, body);
      if (then) then(data); else await load();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }

  const v = plan.values;
  return (
    <>
      <Link to="/plans" className="small">← All plans</Link>
      <div className="page-head" style={{ marginTop: 10 }}>
        <div>
          <div className="row wrap"><h1>{plan.name}</h1><PlanStatus status={plan.status} /></div>
          <p>{plan.plan_type === "prepaid" ? "Prepaid" : "Postpaid"} · {MODE[plan.plan_mode]} · {plan.clients_using} client{plan.clients_using === 1 ? "" : "s"} on this plan</p>
        </div>
        <div className="row wrap">
          {plan.status === "pending" && <>
            <button className="btn btn-danger" onClick={() => setRejecting(true)}>Reject</button>
            <button className="btn btn-success" disabled={!!busy} onClick={() => act("approve", "approve")}>{busy === "approve" ? "Approving…" : "Approve plan"}</button>
          </>}
          {(plan.status === "pending" || plan.status === "rejected") && <button className="btn" onClick={() => navigate(`/plans/${id}/edit`)}>Edit</button>}
          {plan.status === "approved" && <button className="btn" disabled={!!busy} onClick={() => { if (window.confirm("Retire this plan? It can no longer be given to new clients. Clients already on it keep it.")) act("retire", "retire"); }}>Retire</button>}
          <button className="btn" disabled={!!busy} onClick={() => act("clone", "clone", undefined, (d) => navigate(`/plans/${d.id}`))}>Clone as new plan</button>
        </div>
      </div>
      <ErrorBox error={error} />
      {plan.status === "rejected" && <div className="alert error" style={{ marginBottom: 14 }}><b>Rejected:</b> {plan.reject_remarks} Edit the plan to send it for approval again.</div>}
      {plan.status === "pending" && <div className="alert info" style={{ marginBottom: 14 }}>Waiting for approval. Created by {plan.created_by || "—"} on {fmtDateTime(plan.created_at)}. Once approved it can no longer be edited, so billing never changes under a client; clone it to make a new version.</div>}
      {plan.status === "approved" && <div className="alert success" style={{ marginBottom: 14 }}>Approved by {plan.approved_by || "—"} on {fmtDateTime(plan.approved_at)}. This plan is locked.</div>}

      <div className="grid cols-2" style={{ alignItems: "start" }}>
        {schema.sections.map((s) => (
          <div className="card card-pad" key={s.id}>
            <div className="section-title">{s.title}</div>
            <dl className="kv" style={{ gridTemplateColumns: "minmax(0, 1.2fr) minmax(0, 1fr)" }}>
              {s.fields.filter((f) => f.kind !== "pulse").map((f) => (
                <FragmentRow key={f.key} label={f.label} value={show(f, v[f.key], v)} extra={f.pair ? `Pulse: ${v[f.pair[0]]} sec` : null} />
              ))}
            </dl>
          </div>
        ))}
        {plan.notes && <div className="card card-pad"><div className="section-title">Notes</div><p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{plan.notes}</p></div>}
      </div>

      {rejecting && <RejectModal onClose={() => setRejecting(false)} onSubmit={async (note) => { await act("reject", "reject", { note }, () => { setRejecting(false); load(); }); }} />}
    </>
  );
}

function FragmentRow({ label, value, extra }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}{extra && <div className="small muted">{extra}</div>}</dd>
    </>
  );
}

function RejectModal({ onClose, onSubmit }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="Reject plan" onClose={onClose} footer={
      <><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger" disabled={busy || note.trim().length < 3} onClick={async () => { setBusy(true); await onSubmit(note.trim()); setBusy(false); }}>Reject plan</button></>}>
      <Field label="What needs to change?"><textarea value={note} onChange={(e) => setNote(e.target.value)} autoFocus /></Field>
    </Modal>
  );
}
