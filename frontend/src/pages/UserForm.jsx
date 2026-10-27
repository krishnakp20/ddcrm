import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { useAuth } from "../auth";
import { AgentClientsCard } from "../components/DialerAdmin";
import PermissionMatrix from "../components/PermissionMatrix";
import { Badge, CopyButton, ErrorBox, Field, Modal, PageHead, Spinner, useToast } from "../components/ui";
import { UserStatus } from "./Users";

const TYPE_HELP = {
  staff: "Works for DialDesk: onboarding clients, plans, support.",
  client: "Works for one client company and sees only that company.",
  agent: "Takes and makes calls. Can work for DialDesk or for one client.",
};
const DEFAULT_ROLE = { staff: "support", client: "client_manager", agent: "agent" };

/** Add a user, or open one to change details, role and permissions. */
export default function UserForm() {
  const { id } = useParams();
  const editing = !!id;
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { user: me, refresh } = useAuth();
  const [meta, setMeta] = useState(null);
  const [orig, setOrig] = useState(null);
  const [f, setF] = useState(null);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, setToast, toastEl] = useToast();

  useEffect(() => {
    api.get("/users/meta").then(async (m) => {
      setMeta(m.data);
      if (editing) {
        const { data } = await api.get(`/users/${id}`);
        setOrig(data);
        setF({
          name: data.name, email: data.email, phone: data.phone || "", user_type: data.user_type, role_id: data.role?.id || "",
          department_id: data.department?.id || "", client_id: data.client?.id || "", dialer_agent_id: data.dialer_agent_id || "",
          extra_permissions: data.extra_permissions, denied_permissions: data.denied_permissions, is_active: data.is_active, send_invite: false,
        });
      } else {
        const type = params.get("type") || m.data.types[0].key;
        setF({
          name: "", email: "", phone: "", user_type: type, role_id: "", department_id: "",
          client_id: params.get("client_id") || (m.data.own_client_id ?? ""), dialer_agent_id: "",
          extra_permissions: [], denied_permissions: [], is_active: true, send_invite: true,
        });
      }
    }).catch((e) => setError(errorMessage(e)));
  }, [id, editing]);  // eslint-disable-line react-hooks/exhaustive-deps

  const roles = useMemo(() => (meta && f ? meta.roles.filter((r) => r.user_type === f.user_type) : []), [meta, f]);

  // pick the usual role when the kind of user changes
  useEffect(() => {
    if (!meta || !f || editing) return;
    if (!roles.find((r) => r.id === f.role_id)) {
      const pick = roles.find((r) => r.key === DEFAULT_ROLE[f.user_type] && r.assignable) || roles.find((r) => r.assignable);
      setF((x) => ({ ...x, role_id: pick?.id || "", extra_permissions: [], denied_permissions: [] }));
    }
  }, [meta, f?.user_type]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !meta) return <ErrorBox error={error} />;
  if (!meta || !f) return <Spinner />;

  const staffUser = me.user_type === "staff";
  const role = roles.find((r) => r.id === Number(f.role_id));
  const clientScope = f.user_type === "staff" ? null : (Number(f.client_id) || null);
  const departments = meta.departments.filter((d) => d.client_id === clientScope);
  // a department that was switched off later stays visible for the people already in it
  if (editing && orig?.department && !departments.some((d) => d.id === orig.department.id)) {
    departments.push({ id: orig.department.id, name: `${orig.department.name} (switched off)` });
  }
  const canGrant = new Set(meta.my_permissions);
  const isSelf = editing && orig?.id === me.id;
  const invited = orig?.status === "invited";
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  function changeRole(e) {
    const rid = Number(e.target.value);
    const next = roles.find((r) => r.id === rid);
    const base = new Set(next?.permissions || []);
    // drop overrides the new role makes pointless
    setF({
      ...f, role_id: rid,
      extra_permissions: f.extra_permissions.filter((k) => !base.has(k)),
      denied_permissions: f.denied_permissions.filter((k) => base.has(k)),
    });
  }

  async function save(e) {
    e?.preventDefault();
    setBusy(true); setError(""); setErrors({});
    try {
      const body = { ...f, role_id: Number(f.role_id), client_id: f.client_id ? Number(f.client_id) : null,
        department_id: f.department_id ? Number(f.department_id) : null, phone: f.phone || null, dialer_agent_id: f.dialer_agent_id || null };
      if (editing) {
        const { data } = await api.put(`/users/${id}`, body);
        setOrig(data);
        setToast("Saved");
        if (isSelf) refresh();
      } else {
        const { data } = await api.post("/users", body);
        setResult(data);
      }
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally { setBusy(false); }
  }

  async function sendLink() {
    if (!window.confirm(`Send ${orig.name} a new password link by email, SMS and WhatsApp?`)) return;
    try {
      const { data } = await api.post(`/users/${id}/send-password-link`);
      setResult({ ...orig, invitation: data.invitation, link: data.link, resend: true });
    } catch (err) { setError(errorMessage(err)); }
  }

  return (
    <>
      <Link to="/users" className="small">← All users</Link>
      <PageHead title={editing ? orig.name : "Add user"} sub={editing ? `${orig.type_label}${orig.client ? ` · ${orig.client.name}` : ""}` : "The person gets a message with a link to set their own password."}>
        {editing && <UserStatus status={orig.status} />}
        {editing && !isSelf && <button className="btn" onClick={sendLink}>Send password link</button>}
        <button className="btn btn-primary" disabled={busy || !f.role_id} onClick={save}>{busy ? "Saving…" : editing ? "Save changes" : "Add user"}</button>
      </PageHead>
      <ErrorBox error={error} />
      {isSelf && <div className="alert info" style={{ marginBottom: 14 }}>This is your own account. You can change your name and mobile here, but not your role, permissions or status.</div>}

      <form className="stack" onSubmit={save}>
        {!editing && meta.types.length > 1 && (
          <div className="card card-pad">
            <div className="section-title">Kind of user</div>
            <div className="grid cols-3">
              {meta.types.map((t) => (
                <button type="button" key={t.key} className={`type-card ${f.user_type === t.key ? "on" : ""}`}
                  onClick={() => setF({ ...f, user_type: t.key, role_id: "", department_id: "", client_id: t.key === "staff" ? "" : f.client_id, dialer_agent_id: "", extra_permissions: [], denied_permissions: [] })}>
                  <b>{t.label}</b><span className="small muted">{TYPE_HELP[t.key]}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="card card-pad">
          <div className="section-title">Details</div>
          <div className="form-grid">
            <Field label="Name *" error={errors.name}><input value={f.name} onChange={set("name")} autoFocus={!editing} /></Field>
            <Field label="Email (login) *" error={errors.email} hint={editing && !invited ? "The login cannot be changed after sign-up." : undefined}>
              <input type="email" value={f.email} onChange={set("email")} disabled={editing && !invited} />
            </Field>
            <Field label="Mobile" error={errors.phone} hint="Used for SMS and WhatsApp messages"><input value={f.phone} onChange={set("phone")} inputMode="tel" placeholder="10-digit number" /></Field>
            {f.user_type !== "staff" && staffUser && (
              <Field label={f.user_type === "client" ? "Client company *" : "Client company"} error={errors.client_id}
                hint={f.user_type === "agent" ? "Leave empty for a DialDesk agent who works for several clients" : undefined}>
                <select value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value, department_id: "" })} disabled={editing}>
                  <option value="">{f.user_type === "agent" ? "DialDesk (shared agent)" : "Select a company…"}</option>
                  {meta.clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
            )}
            <Field label="Department" error={errors.department_id}>
              <select value={f.department_id} onChange={set("department_id")}>
                <option value="">No department</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            {f.user_type === "agent" && (
              <Field label="Dialer agent ID" error={errors.dialer_agent_id} hint="The agent's login on the dialer. Calls reach the agent through it.">
                <input value={f.dialer_agent_id} onChange={set("dialer_agent_id")} />
              </Field>
            )}
            {editing && !isSelf && (
              <span className="check" style={{ alignSelf: "end", paddingBottom: 8 }}>
                <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Account is active
              </span>
            )}
          </div>
        </div>

        {editing && staffUser && f.user_type === "agent" && !f.client_id && <AgentClientsCard userId={orig.id} />}

        <div className="card card-pad">
          <div className="section-title">Role</div>
          <Field label="Role *" error={errors.role_id} hint={role?.description}>
            <select value={f.role_id} onChange={changeRole} disabled={isSelf} style={{ maxWidth: 360 }}>
              <option value="">Select a role…</option>
              {roles.map((r) => <option key={r.id} value={r.id} disabled={!r.assignable && r.id !== orig?.role?.id}>{r.name}{!r.assignable && r.id !== orig?.role?.id ? " (more access than you have)" : ""}</option>)}
            </select>
          </Field>
        </div>

        <div className="card card-pad">
          <div className="row spread wrap" style={{ marginBottom: 6 }}>
            <div className="section-title" style={{ margin: 0 }}>Permissions</div>
            {(f.extra_permissions.length > 0 || f.denied_permissions.length > 0) && !isSelf && (
              <button type="button" className="btn btn-sm" onClick={() => setF({ ...f, extra_permissions: [], denied_permissions: [] })}>Reset to the role's permissions</button>
            )}
          </div>
          <p className="muted" style={{ margin: "0 0 14px" }}>
            The ticks come from the role. Change a tick to give this person more or less than their role.
          </p>
          {errors.permissions && <div className="alert error" style={{ marginBottom: 12 }}>{errors.permissions}</div>}
          <PermissionMatrix
            catalog={meta.catalog} userType={f.user_type} base={role?.permissions || []}
            extra={f.extra_permissions} denied={f.denied_permissions} canGrant={canGrant} disabled={isSelf}
            onOverrides={({ extra, denied }) => setF({ ...f, extra_permissions: extra, denied_permissions: denied })}
          />
        </div>

        {!editing && (
          <div className="card card-pad">
            <span className="check"><input type="checkbox" checked={f.send_invite} onChange={(e) => setF({ ...f, send_invite: e.target.checked })} /> Send the login invitation now (email, SMS and WhatsApp)</span>
          </div>
        )}
        <div className="row"><div className="grow" /><button className="btn btn-primary btn-lg" disabled={busy || !f.role_id}>{busy ? "Saving…" : editing ? "Save changes" : "Add user"}</button></div>
      </form>

      {result && (
        <Modal title={result.resend ? "Password link sent" : "User added"} onClose={() => { setResult(null); if (!result.resend) navigate(`/users/${result.id}`); }}
          footer={<button className="btn btn-primary" onClick={() => { setResult(null); if (!result.resend) navigate(`/users/${result.id}`); }}>Done</button>}>
          <p style={{ marginTop: 0 }}><b>{result.name}</b> {result.resend ? "was sent a new link to set a password:" : f.send_invite ? "was sent a login invitation:" : "was added. No invitation was sent yet; use “Send password link” when ready."}</p>
          {(result.invitation || []).map((s) => (
            <div key={s.channel} className="row" style={{ marginBottom: 6 }}>
              <b style={{ textTransform: "capitalize", width: 84 }}>{s.channel}</b>
              <span className="grow small muted">{s.to}</span>
              <span className={`badge ${s.status === "sent" ? "active" : s.status === "failed" ? "rejected" : "draft"}`}>{s.status === "logged" ? "Recorded" : s.status}</span>
            </div>
          ))}
          {result.link && (
            <div className="stack" style={{ marginTop: 12 }}>
              <div className="alert info">The email / SMS / WhatsApp provider is not connected, so nothing was delivered. Give this link to <b>{result.name}</b>: they open it and choose their own password. It works for 7 days.</div>
              <div className="copy-box"><code>{result.link}</code><CopyButton text={result.link} /></div>
            </div>
          )}
        </Modal>
      )}
      {toastEl}
    </>
  );
}
