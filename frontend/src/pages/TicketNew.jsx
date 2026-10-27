import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { useAuth } from "../auth";
import FormRunner from "../components/forms/FormRunner";
import { PRIORITIES } from "../components/TicketBits";
import { ErrorBox, Field, PageHead, Spinner } from "../components/ui";
import { useScope } from "../scope";

/** A new ticket: choose the client, the customer, then fill in the client's own form. Opens prefilled from a call. */
export default function TicketNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { user } = useAuth();
  const { clientId: scoped } = useScope();
  const callId = params.get("call");
  const [clients, setClients] = useState(null);
  const [clientId, setClientId] = useState(params.get("client") || "");
  const [cfg, setCfg] = useState(null);
  const [people, setPeople] = useState({ users: [], departments: [] });
  const [f, setF] = useState({ name: "", mobile: "", email: "", city: "", subject: "", description: "", priority: "medium", assigned_user_id: "", assigned_department_id: "" });
  const [known, setKnown] = useState(null);       // a customer we already have for this number
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  useEffect(() => {
    api.get("/tickets/clients").then((r) => {
      setClients(r.data);
      if (!clientId) setClientId(String((scoped && r.data.some((c) => String(c.id) === scoped) ? scoped : r.data[0]?.id) || ""));
    }).catch((e) => setError(errorMessage(e)));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // from a call: take the client, the number and the customer from it
  useEffect(() => {
    if (!callId) return;
    api.get(`/agent/calls/${callId}`).then(({ data }) => {
      setClientId(String(data.client.id));
      setF((p) => ({ ...p, mobile: data.interaction.phone, name: data.customer?.name || "", email: data.customer?.email || "", city: data.customer?.city || "" }));
      if (data.customer) setKnown(data.customer);
    }).catch((e) => setError(errorMessage(e)));
  }, [callId]);

  useEffect(() => {
    if (!clientId) return;
    setCfg(null);
    api.get(`/tickets/form/${clientId}`).then((r) => setCfg(r.data)).catch((e) => setError(errorMessage(e)));
    api.get("/tickets/assignees", { params: { client_id: clientId } }).then((r) => setPeople(r.data)).catch(() => {});
    setF((p) => ({ ...p, assigned_user_id: "", assigned_department_id: "" }));
  }, [clientId]);

  async function lookup() {
    const digits = f.mobile.replace(/\D/g, "");
    if (!clientId || digits.length < 6) return;
    try {
      const { data } = await api.get("/tickets/customer", { params: { client_id: clientId, mobile: f.mobile } });
      setKnown(data);
      if (data) setF((p) => ({ ...p, name: data.name, email: data.email || p.email, city: data.city || p.city }));
    } catch { /* the form will say what is wrong when it is saved */ }
  }

  async function submit({ path, answers }) {
    setErrors({}); setError("");
    try {
      const { data } = await api.post("/tickets", {
        client_id: Number(clientId), name: f.name, mobile: f.mobile, email: f.email || null, city: f.city || null,
        subject: f.subject, description: f.description || null, priority: f.priority, path, answers,
        interaction_id: callId ? Number(callId) : null,
        assigned_user_id: f.assigned_user_id ? Number(f.assigned_user_id) : null,
        assigned_department_id: f.assigned_department_id ? Number(f.assigned_department_id) : null,
      });
      navigate(`/tickets/${data.id}`);
    } catch (e) {
      setErrors(fieldErrors(e)); setError(errorMessage(e));
      throw e;  // the form below shows its own field errors
    }
  }

  if (!clients) return error ? <ErrorBox error={error} /> : <Spinner />;
  if (clients.length === 0) return <div className="card card-pad">There is no active client to raise a ticket for.</div>;
  const only = clients.length === 1;

  return (
    <>
      <Link to="/tickets" className="small">← All tickets</Link>
      <PageHead title="New ticket" sub={callId ? "Raised from the call you are on. The customer and number are filled in." : "Create a ticket without a call (offline)."} />
      {error && <ErrorBox error={error} />}

      <div className="stack">
        <div className="card card-pad">
          <div className="section-title">Client and customer</div>
          <div className="form-grid">
            <Field label="Client *" full>
              {only || callId ? <b style={{ padding: "6px 0" }}>{clients.find((c) => String(c.id) === clientId)?.name}</b> : (
                <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
            </Field>
            <Field label="Mobile number *" error={errors.mobile} hint="We look the customer up by this number.">
              <input className={errors.mobile ? "invalid" : ""} value={f.mobile} onChange={set("mobile")} onBlur={lookup} inputMode="tel" readOnly={!!callId} />
            </Field>
            <Field label="Customer name *" error={errors.name} hint={known ? "Existing customer. The saved name is kept." : undefined}>
              <input className={errors.name ? "invalid" : ""} value={f.name} onChange={set("name")} readOnly={!!known} />
            </Field>
            <Field label="Email" error={errors.email}><input value={f.email} onChange={set("email")} /></Field>
            <Field label="City"><input value={f.city} onChange={set("city")} /></Field>
          </div>
        </div>

        <div className="card card-pad">
          <div className="section-title">Ticket</div>
          <div className="form-grid">
            <Field label="Subject *" error={errors.subject} full><input className={errors.subject ? "invalid" : ""} value={f.subject} onChange={set("subject")} placeholder="What is this about?" /></Field>
            <Field label="Priority" error={errors.priority} hint="Sets the time to resolve (SLA).">
              <select value={f.priority} onChange={set("priority")}>{PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            </Field>
            <span />
            <Field label="Assign to (optional)" error={errors.assigned_user_id}>
              <select value={f.assigned_user_id} onChange={set("assigned_user_id")}>
                <option value="">Nobody yet</option>
                {people.users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.kind}</option>)}
              </select>
            </Field>
            <Field label="Department (optional)" error={errors.assigned_department_id}>
              <select value={f.assigned_department_id} onChange={set("assigned_department_id")}>
                <option value="">None</option>
                {people.departments.map((d) => <option key={d.id} value={d.id}>{d.name}{d.own ? "" : " (DialDesk)"}</option>)}
              </select>
            </Field>
            <Field label="Description" full><textarea value={f.description} onChange={set("description")} placeholder="What the customer said, and what is needed" /></Field>
          </div>
        </div>

        {!cfg ? <Spinner label="Loading the client's form…" /> : (
          <FormRunner key={cfg.client.id} cfg={cfg} base="" onSubmit={submit} submitLabel="Create ticket" />
        )}
      </div>
    </>
  );
}
