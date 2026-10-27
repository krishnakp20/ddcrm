import { useCallback, useEffect, useState } from "react";
import api, { errorMessage, fieldErrors } from "../api";
import { useAuth } from "../auth";
import { useScope } from "../scope";
import { Badge, Empty, ErrorBox, Field, Icon, Modal, PageHead } from "../components/ui";

export default function Departments() {
  const { user, can } = useAuth();
  const staff = user.user_type === "staff";
  const manage = can("departments.manage");
  const [rows, setRows] = useState([]);
  const [clients, setClients] = useState([]);
  const [scope, setScope] = useState("");
  const global = useScope();
  useEffect(() => { setScope(global.clientId); }, [global.clientId]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", description: "", client_id: "", is_active: true });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get("/departments", { params: { client_id: scope || undefined } }).then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  }, [scope]);
  useEffect(load, [load]);
  useEffect(() => { if (staff) api.get("/users/meta").then((r) => setClients(r.data.clients)).catch(() => {}); }, [staff]);

  function open(d) {
    setErrors({}); setError("");
    setEditing(d || {});
    setForm(d ? { name: d.name, description: d.description || "", client_id: d.client_id ?? "", is_active: d.is_active }
      : { name: "", description: "", client_id: staff && scope && scope !== "dialdesk" ? scope : "", is_active: true });
  }

  async function save(e) {
    e.preventDefault();
    setErrors({}); setError("");
    const body = { ...form, client_id: form.client_id ? Number(form.client_id) : null, description: form.description || null };
    try {
      if (editing.id) await api.put(`/departments/${editing.id}`, body); else await api.post("/departments", body);
      setEditing(null); load();
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); }
  }

  async function remove(d) {
    if (!window.confirm(`Delete the department “${d.name}”?`)) return;
    try { await api.delete(`/departments/${d.id}`); load(); } catch (err) { setError(errorMessage(err)); }
  }

  return (
    <>
      <PageHead title="Departments" sub={staff ? "DialDesk's own departments and each client's departments" : "Departments in your company"}>
        {manage && <button className="btn btn-primary" onClick={() => open(null)}><span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add department</button>}
      </PageHead>
      <div className="card">
        {staff && (
          <div style={{ padding: 14, borderBottom: "1px solid var(--border)" }}>
            <select style={{ maxWidth: 300 }} value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">All departments</option><option value="dialdesk">DialDesk only</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        )}
        <ErrorBox error={error && !editing ? error : ""} />
        {rows.length === 0 ? <Empty>No departments yet.{manage ? " Add the first one." : ""}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Department</th>{staff && <th>Belongs to</th>}<th>Users</th><th>Status</th>{manage && <th />}</tr></thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td><b>{d.name}</b>{d.description && <div className="small muted">{d.description}</div>}</td>
                    {staff && <td>{d.client_id ? d.scope : <Badge tone="primary">DialDesk</Badge>}</td>}
                    <td>{d.users_count}</td>
                    <td>{d.is_active ? <Badge tone="success">Active</Badge> : <Badge>Switched off</Badge>}</td>
                    {manage && <td style={{ textAlign: "right" }}>
                      <button className="btn btn-sm" onClick={() => open(d)}>Edit</button>{" "}
                      <button className="btn btn-sm btn-ghost" onClick={() => remove(d)}>Delete</button>
                    </td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <Modal title={editing.id ? "Edit department" : "Add department"} onClose={() => setEditing(null)}
          footer={<><button className="btn" onClick={() => setEditing(null)}>Cancel</button><button className="btn btn-primary" form="dept-form">Save</button></>}>
          <form id="dept-form" className="stack" onSubmit={save}>
            <ErrorBox error={error && editing ? error : ""} />
            <Field label="Department name *" error={errors.name}><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></Field>
            {staff && !editing.id && (
              <Field label="Belongs to" hint="DialDesk's own department, or one client's">
                <select value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
                  <option value="">DialDesk</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
            )}
            <Field label="Description"><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <span className="check"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active (can be given to users)</span>
          </form>
        </Modal>
      )}
    </>
  );
}
