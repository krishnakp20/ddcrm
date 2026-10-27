import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { PRIORITIES, PriorityBadge, STATUSES, SlaChip, SourceChip, TicketStatus } from "../components/TicketBits";
import { ErrorBox, Field, Modal, Spinner, fmtDateTime, useToast } from "../components/ui";

export default function TicketDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const manage = can("tickets.manage");
  const [t, setT] = useState(null);
  const [people, setPeople] = useState({ users: [], departments: [] });
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [status, setStatus] = useState(null);   // the status being chosen, waiting for a note
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();

  const load = useCallback(() => api.get(`/tickets/${id}`).then((r) => setT(r.data)).catch((e) => setError(errorMessage(e))), [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (t) api.get("/tickets/assignees", { params: { client_id: t.client_id } }).then((r) => setPeople(r.data)).catch(() => {}); }, [t?.client_id]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function act(fn, ok) {
    setBusy(true); setError("");
    try { const { data } = await fn(); setT(data); if (ok) setToast(ok); return true; }
    catch (e) { setError(errorMessage(e)); return false; } finally { setBusy(false); }
  }

  if (error && !t) return <ErrorBox error={error} />;
  if (!t) return <Spinner />;
  const ended = t.status === "resolved" || t.status === "closed";

  return (
    <>
      <Link to="/tickets" className="small">← All tickets</Link>
      <div className="page-head" style={{ marginTop: 6 }}>
        <div>
          <div className="mono small muted">{t.number} · {t.client_name}</div>
          <h1>{t.subject}</h1>
        </div>
        <div className="row wrap"><SourceChip source={t.source} /><TicketStatus status={t.status} /><PriorityBadge priority={t.priority} /><SlaChip sla={t.sla} due={t.due_at} /></div>
      </div>
      <ErrorBox error={error} />

      <div className="grid ticket-grid">
        <div className="stack">
          {(t.description || t.answers.length > 0 || t.scenario.length > 0) && (
            <div className="card card-pad stack">
              {t.description && <div style={{ whiteSpace: "pre-wrap" }}>{t.description}</div>}
              {t.scenario.length > 0 && <div className="small"><span className="muted">Scenario: </span>{t.scenario.join(" › ")}</div>}
              {t.answers.length > 0 && (
                <dl className="kv" style={{ gridTemplateColumns: "150px minmax(0, 1fr)" }}>
                  {t.answers.map((a) => <div key={a.label} style={{ display: "contents" }}><dt>{a.label}</dt><dd>{Array.isArray(a.value) ? a.value.join(", ") : String(a.value)}</dd></div>)}
                </dl>
              )}
            </div>
          )}

          <div className="card">
            <div className="card-head"><h3>Conversation</h3><span className="small muted">{t.comments.length} entries</span></div>
            <div className="card-body timeline">
              {t.comments.map((c) => (
                <div key={c.id} className="tl-item" style={c.kind === "comment" ? undefined : { opacity: 0.8 }}>
                  {c.kind === "comment" ? <div style={{ whiteSpace: "pre-wrap" }}><b>{c.by || (t.source === "manual" || t.source === "call" ? "Customer" : `Customer (${t.source})`)}</b>: {c.body}</div> : <div className="small">{c.body}</div>}
                  <div className="small muted">{fmtDateTime(c.created_at)}</div>
                </div>
              ))}
            </div>
            {manage && (
              <div className="card-body" style={{ borderTop: "1px solid var(--border)" }}>
                <Field label="Add a comment"><textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Update for the team" /></Field>
                <div style={{ marginTop: 8 }}>
                  <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={async () => { if (await act(() => api.post(`/tickets/${id}/comments`, { body: text }), "Comment added")) setText(""); }}>Add comment</button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="stack">
          <div className="card card-pad stack">
            <div className="section-title" style={{ margin: 0 }}>Status</div>
            {manage ? (
              <div className="row wrap" style={{ gap: 6 }}>
                {STATUSES.map(([k, l]) => (
                  <button key={k} className={`btn btn-sm ${t.status === k ? "btn-primary" : ""}`} disabled={busy || t.status === k}
                    onClick={() => (k === "resolved" || k === "closed" ? setStatus(k) : act(() => api.post(`/tickets/${id}/status`, { status: k }), "Status updated"))}>{l}</button>
                ))}
              </div>
            ) : <TicketStatus status={t.status} />}
            <dl className="kv" style={{ gridTemplateColumns: "100px minmax(0, 1fr)" }}>
              <dt>Created</dt><dd>{fmtDateTime(t.created_at)}{t.created_by ? ` by ${t.created_by}` : ""}</dd>
              <dt>Due</dt><dd>{fmtDateTime(t.due_at)} <span className="muted small">({t.sla_hours}h)</span></dd>
              {t.resolved_at && <><dt>Resolved</dt><dd>{fmtDateTime(t.resolved_at)}</dd></>}
            </dl>
          </div>

          <div className="card card-pad stack">
            <div className="section-title" style={{ margin: 0 }}>Assignment</div>
            {manage ? (
              <AssignBox t={t} people={people} busy={busy} onSave={(b) => act(() => api.post(`/tickets/${id}/assign`, b), "Assignment saved")} />
            ) : <div>{t.assigned_to || "Unassigned"}{t.department && <div className="small muted">{t.department}</div>}</div>}
            {manage && <Field label="Priority">
              <select value={t.priority} disabled={busy || t.status === "closed"} onChange={(e) => act(() => api.put(`/tickets/${id}`, { priority: e.target.value }), "Priority changed")}>
                {PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </Field>}
          </div>

          {!t.customer && (t.contact_name || t.contact_email) && (
            <div className="card card-pad">
              <div className="section-title">Sender</div>
              <dl className="kv" style={{ gridTemplateColumns: "80px minmax(0, 1fr)" }}>
                {t.contact_name && <><dt>Name</dt><dd>{t.contact_name}</dd></>}{t.contact_email && <><dt>Email</dt><dd>{t.contact_email}</dd></>}
              </dl>
              <div className="small muted" style={{ marginTop: 8 }}>No customer record yet: it is created when a mobile number is known.</div>
            </div>
          )}
          {t.customer && (
            <div className="card card-pad">
              <div className="section-title">Customer</div>
              <dl className="kv" style={{ gridTemplateColumns: "80px minmax(0, 1fr)" }}>
                <dt>Name</dt><dd>{t.customer.name}</dd><dt>Mobile</dt><dd className="mono">{t.customer.mobile}</dd>
                {t.customer.email && <><dt>Email</dt><dd>{t.customer.email}</dd></>}{t.customer.city && <><dt>City</dt><dd>{t.customer.city}</dd></>}
              </dl>
            </div>
          )}
        </div>
      </div>

      {status && <NoteModal status={status} ended={ended} onClose={() => setStatus(null)}
        onSave={async (note) => { if (await act(() => api.post(`/tickets/${id}/status`, { status, comment: note }), "Status updated")) setStatus(null); }} />}
      {toastEl}
    </>
  );
}

function AssignBox({ t, people, busy, onSave }) {
  const [u, setU] = useState(t.assigned_user_id || "");
  const [d, setD] = useState(t.assigned_department_id || "");
  useEffect(() => { setU(t.assigned_user_id || ""); setD(t.assigned_department_id || ""); }, [t.assigned_user_id, t.assigned_department_id]);
  const dirty = String(u) !== String(t.assigned_user_id || "") || String(d) !== String(t.assigned_department_id || "");
  return (
    <>
      <Field label="Person">
        <select value={u} onChange={(e) => setU(e.target.value)}>
          <option value="">Nobody</option>{people.users.map((x) => <option key={x.id} value={x.id}>{x.name} · {x.kind}</option>)}
        </select>
      </Field>
      <Field label="Department">
        <select value={d} onChange={(e) => setD(e.target.value)}>
          <option value="">None</option>{people.departments.map((x) => <option key={x.id} value={x.id}>{x.name}{x.own ? "" : " (DialDesk)"}</option>)}
        </select>
      </Field>
      <div><button className="btn btn-sm btn-primary" disabled={busy || !dirty} onClick={() => onSave({ user_id: u ? Number(u) : null, department_id: d ? Number(d) : null })}>Save assignment</button></div>
    </>
  );
}

function NoteModal({ status, onClose, onSave }) {
  const [note, setNote] = useState("");
  return (
    <Modal title={status === "resolved" ? "Resolve this ticket" : "Close this ticket"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={note.trim().length < 3} onClick={() => onSave(note)}>{status === "resolved" ? "Mark resolved" : "Close ticket"}</button></>}>
      <Field label="What was done? *" hint="This note is added to the conversation.">
        <textarea autoFocus value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Modal>
  );
}
