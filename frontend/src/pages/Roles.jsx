import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import PermissionMatrix from "../components/PermissionMatrix";
import { Badge, ErrorBox, Field, Icon, PageHead, Spinner, useToast } from "../components/ui";

const TYPES = [["staff", "DialDesk admin user"], ["client", "Client user"], ["agent", "Agent"]];

export function RolesList() {
  const navigate = useNavigate();
  const [roles, setRoles] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get("/roles").then((r) => setRoles(r.data)).catch((e) => setError(errorMessage(e))); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!roles) return <Spinner />;
  return (
    <>
      <PageHead title="Roles & permissions" sub="A role is a set of permissions. Give a role to a user, then fine-tune on the user if needed.">
        <button className="btn btn-primary" onClick={() => navigate("/roles/new")}>
          <span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add role
        </button>
      </PageHead>
      {TYPES.map(([type, label]) => (
        <div key={type} style={{ marginBottom: 22 }}>
          <div className="section-title">{label} roles</div>
          <div className="grid cols-3">
            {roles.filter((r) => r.user_type === type).map((r) => (
              <div key={r.id} className="card role-card" onClick={() => navigate(`/roles/${r.id}`)}>
                <div className="row spread"><b style={{ fontSize: 15 }}>{r.name}</b>{r.is_locked ? <Badge tone="warn">Locked</Badge> : r.is_system ? <Badge>Built in</Badge> : <Badge tone="primary">Custom</Badge>}</div>
                <div className="small muted" style={{ minHeight: 34 }}>{r.description || "No description"}</div>
                <div className="row spread small"><span>{r.permissions.length} permissions</span><span className="muted">{r.users_count} user{r.users_count === 1 ? "" : "s"}</span></div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

export function RoleForm() {
  const { id } = useParams();
  const editing = !!id;
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState(null);
  const [f, setF] = useState(null);
  const [role, setRole] = useState(null);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();

  useEffect(() => {
    api.get("/access/permissions").then(async (c) => {
      setCatalog(c.data.groups);
      if (editing) {
        const { data } = await api.get(`/roles/${id}`);
        setRole(data);
        setF({ name: data.name, description: data.description || "", user_type: data.user_type, permissions: data.permissions });
      } else setF({ name: "", description: "", user_type: "staff", permissions: [] });
    }).catch((e) => setError(errorMessage(e)));
  }, [id, editing]);

  if (error && !f) return <ErrorBox error={error} />;
  if (!catalog || !f) return <Spinner />;
  const locked = role?.is_locked;

  async function save() {
    setBusy(true); setError(""); setErrors({});
    try {
      const { data } = editing ? await api.put(`/roles/${id}`, f) : await api.post("/roles", f);
      if (editing) { setRole(data); setToast("Role saved"); } else navigate(`/roles/${data.id}`);
    } catch (e) { setErrors(fieldErrors(e)); setError(errorMessage(e)); } finally { setBusy(false); }
  }

  async function remove() {
    if (!window.confirm(`Delete the role “${role.name}”?`)) return;
    try { await api.delete(`/roles/${id}`); navigate("/roles"); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <>
      <Link to="/roles" className="small">← All roles</Link>
      <PageHead title={editing ? role.name : "Add role"} sub={editing ? `${role.type_label} · ${role.users_count} user${role.users_count === 1 ? "" : "s"} have this role` : "Choose who the role is for, then tick what it allows."}>
        {editing && !role.is_system && <button className="btn btn-danger" onClick={remove}>Delete</button>}
        {!locked && <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save role"}</button>}
      </PageHead>
      <ErrorBox error={error} />
      {locked && <div className="alert info" style={{ marginBottom: 14 }}>The super admin role always has every permission and cannot be changed.</div>}
      <div className="stack">
        <div className="card card-pad">
          <div className="form-grid">
            <Field label="Role name *" error={errors.name}><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} disabled={locked} autoFocus={!editing} /></Field>
            <Field label="For" hint={editing && role.users_count ? "Cannot change while users have this role" : undefined}>
              <select value={f.user_type} disabled={locked || (editing && role.users_count > 0)}
                onChange={(e) => setF({ ...f, user_type: e.target.value, permissions: [] })}>
                {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </Field>
            <Field label="Description" full><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} disabled={locked} placeholder="What is this role for?" /></Field>
          </div>
        </div>
        <div className="card card-pad">
          <div className="section-title">Permissions</div>
          {errors.permissions && <div className="alert error" style={{ marginBottom: 12 }}>{errors.permissions}</div>}
          <PermissionMatrix catalog={catalog} userType={f.user_type} value={f.permissions} onChange={(permissions) => setF({ ...f, permissions })} disabled={locked} />
        </div>
      </div>
      {toastEl}
    </>
  );
}
