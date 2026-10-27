import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { useAuth } from "../auth";
import FormRunner from "../components/forms/FormRunner";
import { PRIORITIES } from "../components/TicketBits";
import { Badge, CompanyAvatar, ErrorBox, Field, Modal, Spinner, fmtDateTime, fmtDuration, useToast } from "../components/ui";

/** Reads the link the dialer opens: ?phonenumber=..&vendor_id=..&ingroup_id=.. (inbound) or &campaign_id=.. (predictive). */
function readLink(params) {
  const get = (...names) => names.map((n) => params.get(n)).find((v) => v) || undefined;
  return {
    phonenumber: get("phonenumber", "phone", "number"), vendor_id: get("vendor_id", "vendor"),
    ingroup_id: get("ingroup_id", "ingroup"), campaign_id: get("campaign_id", "campaign"),
    call_id: get("call_id", "callid", "uniqueid"), agent_id: get("agent_id", "agent"),
  };
}

export default function AgentCall() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [problem, setProblem] = useState(null);   // {message, code, open_call_id}
  const [saved, setSaved] = useState(false);
  const started = useRef("");
  const key = id ? `id-${id}` : params.toString();

  const open = useCallback(async () => {
    setProblem(null);
    try {
      if (id) { setData((await api.get(`/agent/calls/${id}`)).data); return; }
      const link = readLink(params);
      if (!link.phonenumber || !link.vendor_id) {
        setProblem({ message: "This page is opened by the dialer with the phone number and vendor ID in the link. Nothing was received.", code: "no_params" });
        return;
      }
      setData((await api.post("/agent/calls/start", link)).data);
    } catch (e) {
      const d = e.response?.data?.detail;
      setProblem({ message: errorMessage(e), code: d?.code, open_call_id: d?.open_call_id });
    }
  }, [id, params]);

  useEffect(() => {
    if (started.current === key) return;  // React runs effects twice in development; open the call only once
    started.current = key;
    setData(null); setSaved(false);
    open();
  }, [key, open]);

  if (problem) return <Problem problem={problem} onRetry={open} navigate={navigate} />;
  if (!data) return <Spinner label="Opening the call…" />;
  return <CallScreen data={data} setData={setData} saved={saved} setSaved={setSaved} navigate={navigate} />;
}

function Problem({ problem, onRetry, navigate }) {
  const [skipping, setSkipping] = useState(false);
  return (
    <div className="card card-pad stack" style={{ maxWidth: 640, margin: "40px auto", textAlign: "center" }}>
      <h2>{problem.code === "locked" ? "Finish your previous call first" : "This call cannot be opened"}</h2>
      <p style={{ margin: 0 }}>{problem.message}</p>
      <div className="row wrap" style={{ justifyContent: "center" }}>
        {problem.code === "locked" && <>
          <button className="btn btn-primary" onClick={() => navigate(`/agent/call/${problem.open_call_id}`)}>Open my previous call</button>
          <button className="btn" onClick={() => setSkipping(true)}>Skip it</button>
        </>}
        <button className="btn" onClick={onRetry}>Try again</button>
        <Link className="btn" to="/agent">Agent panel</Link>
      </div>
      {problem.code === "locked" && skipping && (
        <SkipModal callId={problem.open_call_id} onClose={() => setSkipping(false)} onDone={() => { setSkipping(false); onRetry(); }} />
      )}
    </div>
  );
}

function SkipModal({ callId, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  async function go() {
    try { await api.post(`/agent/calls/${callId}/skip`, { reason }); onDone(); } catch (e) { setError(errorMessage(e)); }
  }
  return (
    <Modal title="Skip this call" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-danger" disabled={reason.trim().length < 3} onClick={go}>Skip call</button></>}>
      <div className="stack"><ErrorBox error={error} />
        <p className="muted" style={{ margin: 0 }}>A skipped call is not tagged. Tell your team leader why.</p>
        <Field label="Reason"><input value={reason} onChange={(e) => setReason(e.target.value)} autoFocus placeholder="e.g. Customer hung up" /></Field>
      </div>
    </Modal>
  );
}

function useElapsed(since, running) {
  const [, tick] = useState(0);
  useEffect(() => { if (!running) return undefined; const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t); }, [running]);
  return Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 1000));
}

function CallScreen({ data, setData, saved, setSaved, navigate }) {
  const { can } = useAuth();
  const { interaction: it, client, campaign, customer, history, form, warnings, lead } = data;
  const closed = it.status !== "open" || saved;
  const elapsed = useElapsed(it.started_at, !closed);
  const [notes, setNotes] = useState("");
  const [callbackAt, setCallbackAt] = useState("");
  const [skipping, setSkipping] = useState(false);
  const [toast, setToast, toastEl] = useToast();
  const [mk, setMk] = useState(false);                       // also raise a ticket for this call
  const [tk, setTk] = useState({ subject: "", priority: "medium", user: "", dept: "", description: "" });
  const [tkErrors, setTkErrors] = useState({});
  const [people, setPeople] = useState({ users: [], departments: [] });
  const [created, setCreated] = useState(null);              // the ticket made together with the tag
  const canTicket = can("tickets.manage");

  useEffect(() => {
    if (mk && people.users.length === 0) api.get("/tickets/assignees", { params: { client_id: client.id } }).then((r) => setPeople(r.data)).catch(() => {});
  }, [mk]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function saveTag({ path, answers }) {
    setTkErrors({});
    const body = { path, answers, notes, callback_at: callbackAt ? new Date(callbackAt).toISOString() : undefined };
    if (mk) body.ticket = { subject: tk.subject || null, description: tk.description || null, priority: tk.priority, assigned_user_id: tk.user ? Number(tk.user) : null, assigned_department_id: tk.dept ? Number(tk.dept) : null };
    try {
      const { data } = await api.post(`/agent/calls/${it.id}/save`, body);
      setCreated(data.ticket);
    } catch (e) { setTkErrors(fieldErrors(e)); throw e; }
    setSaved(true);
  }

  return (
    <>
      <div className={`callbar ${closed ? "wrapup" : ""}`} style={closed ? { background: "linear-gradient(90deg,#475569,#64748b)" } : undefined}>
        <CompanyAvatar name={client.name} logo={client.logo_url} />
        <div className="meta"><b>{client.name}</b><span className="small">{campaign ? `Campaign: ${campaign.name}` : "Inbound call"}</span></div>
        <Badge>{it.mode === "pd" ? "☎ Predictive" : it.mode === "manual" ? "☎ Manual" : "⬇ Inbound"}</Badge>
        <div className="meta"><b className="mono" style={{ fontSize: 17 }}>{it.phone}</b><span className="small">{it.call_id ? `Call ${it.call_id}` : "No call id"}</span></div>
        <div className="grow" />
        <div className="timer">{fmtDuration(closed && it.tagged_at ? Math.floor((new Date(it.tagged_at) - new Date(it.started_at)) / 1000) : elapsed)}</div>
        {it.mode === "manual" && !closed && <a className="btn" href={`tel:${it.phone}`}>Dial</a>}
        {can("tickets.manage") && <Link className="btn" to={`/tickets/new?call=${it.id}`}>Create ticket</Link>}
        {closed ? <Badge>{saved || it.status === "tagged" ? "Tagged" : "Skipped"}</Badge> : <button className="btn" onClick={() => setSkipping(true)}>Skip</button>}
      </div>

      {warnings.map((w) => <div key={w} className="alert warn" style={{ marginTop: 12 }}>{w}</div>)}

      <div className="workspace two">
        <div className="stack">
          <CustomerCard it={it} customer={customer} closed={closed} onSaved={(d) => { setData(d); setToast("Customer saved"); }} />
          {lead && (
            <div className="card card-pad">
              <div className="row spread" style={{ marginBottom: 10 }}><h3>Campaign data</h3><Badge tone="primary">try {lead.attempts}</Badge></div>
              {Object.keys(lead.extra).length === 0 ? <div className="muted small">No extra columns were uploaded for this lead.</div> : (
                <dl className="kv">{Object.entries(lead.extra).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
              )}
            </div>
          )}
          <div className="card">
            <div className="card-head"><h3>Previous calls</h3></div>
            <div className="card-body">
              {history.length === 0 ? <div className="muted small">{customer ? "First tagged call with this customer." : "New caller."}</div> : (
                <div className="timeline">
                  {history.map((h) => (
                    <div className="tl-item" key={h.id}>
                      <div style={{ fontWeight: 600 }}>{h.scenario.length ? h.scenario[h.scenario.length - 1] : "Tagged"}{h.outcome && <> <Badge>{h.outcome.replace("_", " ")}</Badge></>}</div>
                      <div className="small muted">{fmtDateTime(h.when)} · {h.mode === "pd" ? "predictive" : h.mode} · {h.agent}{h.campaign ? ` · ${h.campaign}` : ""}</div>
                      {h.scenario.length > 1 && <div className="small">{h.scenario.join(" › ")}</div>}
                      {h.notes && <div className="small" style={{ marginTop: 3 }}>{h.notes}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="stack">
          {closed ? (
            <div className="card card-pad stack">
              <h2>{saved || it.status === "tagged" ? "Call tagged" : "Call skipped"}</h2>
              {it.status === "tagged" && it.scenario.length > 0 && <div>{it.scenario.join(" › ")} {it.outcome && <Badge tone="primary">{it.outcome.replace("_", " ")}</Badge>}</div>}
              {Object.keys(it.answers || {}).length > 0 && (
                <dl className="kv" style={{ gridTemplateColumns: "150px minmax(0, 1fr)" }}>
                  {Object.entries(it.answers).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{form.fields.find((f) => f.key === k)?.label || k}</dt><dd>{Array.isArray(v) ? v.join(", ") : String(v)}</dd></div>)}
                </dl>
              )}
              {created && <div className="alert info">Ticket <Link to={`/tickets/${created.id}`}><b>{created.number}</b></Link> was created for this call.</div>}
              {saved && <div className="alert success">Saved. {it.mode === "manual" ? "Take the next lead when you are ready." : "You are ready for the next call; it will open from the dialer."}</div>}
              <div className="row wrap">
                {it.mode === "manual" && campaign && <Link className="btn btn-primary" to={`/agent/queue?take=${campaign.id}`}>Next lead</Link>}
                <Link className={`btn ${it.mode === "manual" ? "" : "btn-primary"}`} to="/agent">Back to agent panel</Link>
              </div>
            </div>
          ) : (
            <div className="card card-pad">
              <div className="row spread wrap" style={{ marginBottom: 12 }}>
                <h3>Tag this call</h3>
                <span className="muted small">{form.form_key === "in_call" ? "Inbound form" : `Form of ${campaign?.name}`}</span>
              </div>
              {!customer && <div className="alert info" style={{ marginBottom: 12 }}>Save the caller's name on the left first, then tag the call.</div>}
              {form.fields.length === 0 && form.scenarios.length === 0 && <div className="alert warn" style={{ marginBottom: 12 }}>No form is set up for this {campaign ? "campaign" : "client"} yet. You can still save the call with notes.</div>}
              <FormRunner key={it.id} cfg={form} base="" onSubmit={saveTag} submitLabel="Save & finish call" disabled={!customer}>
                <Field label="Notes"><textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Anything the next agent should know" /></Field>
                {canTicket && (
                  <div className="card card-pad stack" style={{ background: "var(--surface-2)", boxShadow: "none" }}>
                    <label className="check"><input type="checkbox" checked={mk} onChange={(e) => setMk(e.target.checked)} /> <b>Also create a ticket for this call</b> <span className="muted small">(for follow-up work)</span></label>
                    {mk && (
                      <div className="form-grid">
                        <Field label="Ticket subject" error={tkErrors.ticket_subject} hint="Empty = the last scenario you pick"><input value={tk.subject} onChange={(e) => setTk({ ...tk, subject: e.target.value })} /></Field>
                        <Field label="Priority" error={tkErrors.ticket_priority} hint="Sets the time to resolve"><select value={tk.priority} onChange={(e) => setTk({ ...tk, priority: e.target.value })}>{PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
                        <Field label="Give it to (optional)" error={tkErrors.assigned_user_id}>
                          <select value={tk.user} onChange={(e) => setTk({ ...tk, user: e.target.value })}><option value="">Nobody yet</option>{people.users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.kind}</option>)}</select>
                        </Field>
                        <Field label="Department (optional)" error={tkErrors.assigned_department_id}>
                          <select value={tk.dept} onChange={(e) => setTk({ ...tk, dept: e.target.value })}><option value="">None</option>{people.departments.map((d) => <option key={d.id} value={d.id}>{d.name}{d.own ? "" : " (DialDesk)"}</option>)}</select>
                        </Field>
                        <Field label="What needs to be done" full><textarea value={tk.description} onChange={(e) => setTk({ ...tk, description: e.target.value })} placeholder="Empty = the notes above" /></Field>
                      </div>
                    )}
                  </div>
                )}
                {lead && <Field label="Call back at (only if the customer asked for a call back)" hint="Leave empty to call back in about 4 hours."><input type="datetime-local" value={callbackAt} onChange={(e) => setCallbackAt(e.target.value)} /></Field>}
              </FormRunner>
            </div>
          )}
        </div>
      </div>
      {skipping && <SkipModal callId={it.id} onClose={() => setSkipping(false)} onDone={() => navigate(it.mode === "manual" ? "/agent/queue" : "/agent")} />}
      {toastEl}
    </>
  );
}

function CustomerCard({ it, customer, closed, onSaved }) {
  const [editing, setEditing] = useState(!customer);
  const [f, setF] = useState({ name: customer?.name || "", mobile: customer?.mobile || it.phone, email: customer?.email || "", city: customer?.city || "", ext_ref: customer?.ext_ref || "" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  useEffect(() => { if (customer) { setF({ name: customer.name, mobile: customer.mobile, email: customer.email || "", city: customer.city || "", ext_ref: customer.ext_ref || "" }); setEditing(false); } }, [customer?.id, customer?.name]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(""); setErrors({});
    try {
      const { data } = await api.put(`/agent/calls/${it.id}/customer`, f);
      onSaved(data); setEditing(false);
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <div className="card card-pad">
      <div className="row spread" style={{ marginBottom: 12 }}>
        <h3>{customer ? "Customer" : "New caller"}</h3>
        {customer && !editing && !closed && <button className="btn btn-sm" onClick={() => setEditing(true)}>Edit</button>}
      </div>
      {!editing && customer ? (
        <dl className="kv" style={{ gridTemplateColumns: "90px minmax(0, 1fr)" }}>
          <dt>Name</dt><dd>{customer.name}</dd><dt>Mobile</dt><dd>{customer.mobile}</dd>
          {customer.email && <><dt>Email</dt><dd>{customer.email}</dd></>}
          {customer.city && <><dt>City</dt><dd>{customer.city}</dd></>}
          {customer.ext_ref && <><dt>Reference</dt><dd>{customer.ext_ref}</dd></>}
        </dl>
      ) : (
        <form className="stack" onSubmit={save}>
          <ErrorBox error={error && !Object.keys(errors).length ? error : ""} />
          <Field label="Name *" error={errors.name}><input value={f.name} onChange={set("name")} autoFocus /></Field>
          <Field label="Mobile *" error={errors.mobile}><input value={f.mobile} onChange={set("mobile")} inputMode="tel" /></Field>
          <Field label="Email" error={errors.email}><input type="email" value={f.email} onChange={set("email")} /></Field>
          <Field label="City"><input value={f.city} onChange={set("city")} /></Field>
          <Field label="Customer / policy / order ID"><input value={f.ext_ref} onChange={set("ext_ref")} /></Field>
          <div className="row">
            <button className="btn btn-primary" disabled={busy || closed}>{busy ? "Saving…" : "Save customer"}</button>
            {customer && <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </form>
      )}
    </div>
  );
}
