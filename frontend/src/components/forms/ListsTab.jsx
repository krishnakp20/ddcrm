import { useCallback, useEffect, useState } from "react";
import api, { errorMessage, fieldErrors } from "../../api";
import { Badge, Empty, ErrorBox, Field, Modal } from "../ui";
import ValuesEditor from "./ValuesEditor";

/** Reusable lists of values (for example Country > State > City) that dropdown fields can use. */
export default function ListsTab({ clientId, canManage, staff }) {
  const [lists, setLists] = useState([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);   // list id being edited
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    api.get("/value-lists", { params: { client_id: clientId } }).then((r) => setLists(r.data)).catch((e) => setError(errorMessage(e)));
  }, [clientId]);
  useEffect(load, [load]);

  async function remove(l) {
    if (!window.confirm(`Delete the list “${l.name}” and all its values?`)) return;
    try { await api.delete(`/value-lists/${l.id}`); load(); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <>
      <div className="row spread wrap" style={{ marginBottom: 14 }}>
        <p className="muted" style={{ margin: 0, maxWidth: 640 }}>
          A list holds the choices of a dropdown. A list with several levels (Country, State, City) lets a dropdown show only the choices that belong to the one above it.
        </p>
        {canManage && <button className="btn btn-primary" onClick={() => setCreating(true)}>+ New list</button>}
      </div>
      <ErrorBox error={error} />
      {lists.length === 0 ? <div className="card"><Empty>No lists yet.</Empty></div> : (
        <div className="grid cols-3">
          {lists.map((l) => {
            const shared = l.client_id == null;
            const editable = canManage && (!shared || staff);
            return (
              <div key={l.id} className="card role-card" onClick={() => setEditing(l.id)}>
                <div className="row spread"><b>{l.name}</b>{shared ? <Badge tone="primary">Shared</Badge> : <Badge>This company</Badge>}</div>
                <div className="small muted">{l.level_names.join(" › ")}</div>
                <div className="row spread small">
                  <span>{l.items_count} values</span>
                  {editable && <button className="btn btn-sm btn-ghost" onClick={(e) => { e.stopPropagation(); remove(l); }}>Delete</button>}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {editing && (
        <ValuesEditor listId={editing} canEdit={canManage && (staff || lists.find((l) => l.id === editing)?.client_id != null)}
          onClose={() => { setEditing(null); load(); }} />
      )}
      {creating && <NewList clientId={clientId} onClose={() => setCreating(false)} onCreated={(l) => { setCreating(false); load(); setEditing(l.id); }} />}
    </>
  );
}

function NewList({ clientId, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [levels, setLevels] = useState(["Country", "State", "City"]);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");

  async function save(e) {
    e.preventDefault();
    setErrors({}); setError("");
    try {
      const { data } = await api.post("/value-lists", { client_id: clientId, name, level_names: levels });
      onCreated(data);
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); }
  }

  return (
    <Modal title="New list" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="list-form">Create</button></>}>
      <form id="list-form" className="stack" onSubmit={save}>
        <ErrorBox error={error} />
        <Field label="List name *" error={errors.name}><input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Geography" /></Field>
        <div>
          <div className="section-title">Levels (up to 5)</div>
          {errors.level_names && <div className="small" style={{ color: "var(--danger)" }}>{errors.level_names}</div>}
          {levels.map((l, i) => (
            <div key={i} className="row" style={{ marginBottom: 8 }}>
              <span className="badge primary">Level {i + 1}</span>
              <input value={l} onChange={(e) => setLevels(levels.map((x, j) => (j === i ? e.target.value : x)))} />
              {levels.length > 1 && <button type="button" className="btn btn-sm btn-ghost" onClick={() => setLevels(levels.filter((_, j) => j !== i))}>Remove</button>}
            </div>
          ))}
          {levels.length < 5 && <button type="button" className="btn btn-sm" onClick={() => setLevels([...levels, ""])}>+ Add a level</button>}
        </div>
      </form>
    </Modal>
  );
}
