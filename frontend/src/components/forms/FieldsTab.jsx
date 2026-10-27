import { useEffect, useState } from "react";
import api, { errorMessage, fieldErrors } from "../../api";
import { Badge, Empty, ErrorBox, Field, Modal } from "../ui";
import ValuesEditor from "./ValuesEditor";

const CHOICE = ["select", "multiselect", "radio"];
const TEXTY = ["text", "textarea"];
const NUMERIC = ["number", "decimal"];

export default function FieldsTab({ cfg, base, reload, canManage, staff }) {
  const [editing, setEditing] = useState(null);     // {} = new
  const [values, setValues] = useState(null);       // list id for the Values editor
  const [error, setError] = useState("");
  const fields = cfg.fields;
  const typeLabel = cfg.options.field_types;
  const listById = Object.fromEntries(cfg.lists.map((l) => [l.id, l]));
  const scenarioCount = (fid) => {
    let n = 0;
    const walk = (nodes) => nodes.forEach((x) => { if (x.fields.some((l) => l.field_id === fid)) n += 1; walk(x.children); });
    walk(cfg.scenarios);
    return n;
  };

  async function move(i, d) {
    const j = i + d;
    if (j < 0 || j >= fields.length) return;
    const ids = fields.map((f) => f.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try { await api.post(`${base}/fields/reorder`, { ids }); reload(); } catch (e) { setError(errorMessage(e)); }
  }

  async function remove(f) {
    if (!window.confirm(`Delete the field “${f.label}”?`)) return;
    try { await api.delete(`/form-fields/${f.id}`); reload(); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <>
      <div className="row spread wrap" style={{ marginBottom: 14 }}>
        <p className="muted" style={{ margin: 0, maxWidth: 640 }}>
          The questions the agent fills in. Put them in the order they should appear. A field can be shown always, or only for chosen scenarios.
        </p>
        {canManage && <button className="btn btn-primary" onClick={() => setEditing({})}>+ Add field</button>}
      </div>
      <ErrorBox error={error} />
      <div className="card">
        {fields.length === 0 ? <Empty>No fields yet.{canManage ? " Add the first one." : ""}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Order</th><th>Name</th><th>Type</th><th>Validation</th><th>Required</th><th>Shown</th>{canManage && <th />}</tr></thead>
              <tbody>
                {fields.map((f, i) => {
                  const parent = fields.find((x) => x.id === f.parent_field_id);
                  return (
                    <tr key={f.id} style={f.is_active ? undefined : { opacity: 0.55 }}>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {canManage ? <><button className="btn btn-sm btn-ghost" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                          <button className="btn btn-sm btn-ghost" disabled={i === fields.length - 1} onClick={() => move(i, 1)}>↓</button></> : i + 1}
                      </td>
                      <td>
                        <b>{f.label}</b>{!f.is_active && <> <Badge>Off</Badge></>}
                        <div className="small muted mono">{f.key}</div>
                        {parent && <div className="small muted">depends on {parent.label}</div>}
                      </td>
                      <td>{typeLabel[f.field_type]}{f.value_list_id && listById[f.value_list_id] && !listById[f.value_list_id].is_private && (
                        <div className="small muted">list: {listById[f.value_list_id].name} › {listById[f.value_list_id].level_names[f.list_level - 1]}</div>)}</td>
                      <td>{cfg.options.validations[f.validation] || "—"}</td>
                      <td>{f.required ? <Badge tone="warn">Yes</Badge> : "No"}</td>
                      <td>{f.show_always ? "Always" : <span>Only for {scenarioCount(f.id)} scenario{scenarioCount(f.id) === 1 ? "" : "s"}</span>}</td>
                      {canManage && (
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button className="btn btn-sm" onClick={() => setEditing(f)}>Edit</button>{" "}
                          {CHOICE.includes(f.field_type) && f.value_list_id && <><button className="btn btn-sm" onClick={() => setValues(f.value_list_id)}>Values</button>{" "}</>}
                          <button className="btn btn-sm btn-ghost" onClick={() => remove(f)}>Delete</button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {editing && <FieldModal field={editing.id ? editing : null} cfg={cfg} base={base} staff={staff} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      {values && <ValuesEditor listId={values} canEdit={canManage && (staff || cfg.lists.find((l) => l.id === values)?.client_id != null)} onClose={() => { setValues(null); reload(); }} />}
    </>
  );
}

function FieldModal({ field, cfg, base, onClose, onSaved }) {
  const editing = !!field;
  const [f, setF] = useState(() => ({
    label: field?.label || "", field_type: field?.field_type || "text", validation: field?.validation || "none",
    rules: field?.rules || {}, required: field?.required || false, help_text: field?.help_text || "",
    show_always: field?.show_always ?? true, is_active: field?.is_active ?? true,
    value_list_id: field?.value_list_id || "", list_level: field?.list_level || 1, parent_field_id: field?.parent_field_id || "",
  }));
  const ownList = editing && field.value_list_id && cfg.lists.find((l) => l.id === field.value_list_id)?.is_private;
  const [source, setSource] = useState(ownList || !editing || !field.value_list_id ? "own" : "list");
  const [ownValues, setOwnValues] = useState("");
  const [lists, setLists] = useState([]);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.get("/value-lists", { params: { client_id: cfg.client.id } }).then((r) => setLists(r.data)).catch(() => {}); }, [cfg.client.id]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setRule = (k) => (e) => setF({ ...f, rules: { ...f.rules, [k]: e.target.value } });
  const isChoice = CHOICE.includes(f.field_type);
  const chosenList = lists.find((l) => l.id === Number(f.value_list_id));
  // a dropdown can depend on another dropdown that uses the level just above, in the same list
  const parents = cfg.fields.filter((x) => x.id !== field?.id && ["select", "radio"].includes(x.field_type) && x.value_list_id === Number(f.value_list_id) && x.list_level === Number(f.list_level) - 1);

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(""); setErrors({});
    try {
      const body = {
        ...f, label: f.label.trim(), help_text: f.help_text || null,
        value_list_id: isChoice && (source === "list" || editing) && f.value_list_id ? Number(f.value_list_id) : null,
        list_level: source === "list" ? Number(f.list_level) : 1,
        parent_field_id: isChoice && source === "list" && f.parent_field_id ? Number(f.parent_field_id) : null,
        own_values: !editing && isChoice && source === "own" ? ownValues.split("\n").map((x) => x.trim()).filter(Boolean) : [],
      };
      if (editing) await api.put(`/form-fields/${field.id}`, body); else await api.post(`${base}/fields`, body);
      onSaved();
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <Modal title={editing ? `Edit field: ${field.label}` : "Add field"} wide onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="field-form" disabled={busy}>{busy ? "Saving…" : "Save field"}</button></>}>
      <form id="field-form" className="stack" onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          <Field label="Field name *" error={errors.label}><input value={f.label} onChange={set("label")} autoFocus placeholder="e.g. Caller Name" /></Field>
          <Field label="Type *" error={errors.field_type} hint={editing ? "The type cannot be changed once the field exists." : undefined}>
            <select value={f.field_type} onChange={set("field_type")} disabled={editing}>
              {Object.entries(cfg.options.field_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>

          {TEXTY.includes(f.field_type) && <>
            <Field label="Validation" error={errors.validation}>
              <select value={f.validation} onChange={set("validation")}>
                {Object.entries(cfg.options.validations).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            {f.validation === "pattern" && <Field label="Pattern (regular expression)" error={errors.rules}><input className="mono" value={f.rules.pattern || ""} onChange={setRule("pattern")} placeholder="[A-Z]{5}[0-9]{4}[A-Z]" /></Field>}
            <Field label="Minimum characters"><input type="number" min="0" value={f.rules.min_length ?? ""} onChange={setRule("min_length")} /></Field>
            <Field label="Maximum characters"><input type="number" min="1" value={f.rules.max_length ?? ""} onChange={setRule("max_length")} /></Field>
          </>}
          {NUMERIC.includes(f.field_type) && <>
            <Field label="Smallest value"><input type="number" value={f.rules.min ?? ""} onChange={setRule("min")} /></Field>
            <Field label="Largest value"><input type="number" value={f.rules.max ?? ""} onChange={setRule("max")} /></Field>
          </>}
          <Field label="Help text" hint="Shown under the field" full><input value={f.help_text} onChange={set("help_text")} /></Field>
        </div>

        {isChoice && (
          <div className="card card-pad" style={{ background: "var(--surface-2)" }}>
            <div className="section-title">Values</div>
            <div className="row wrap" style={{ marginBottom: 12 }}>
              <span className="check"><input type="radio" checked={source === "own"} onChange={() => setSource("own")} disabled={editing && !ownList} /> This field has its own values</span>
              <span className="check"><input type="radio" checked={source === "list"} onChange={() => setSource("list")} /> Use a list (for dependent dropdowns)</span>
            </div>
            {source === "own" ? (
              editing ? <div className="muted small">Use the <b>Values</b> button on the field list to change the values.</div> : (
                <Field label="Values, one per line" hint="You can add more later with the Values button">
                  <textarea value={ownValues} onChange={(e) => setOwnValues(e.target.value)} placeholder={"Low\nMedium\nHigh"} />
                </Field>
              )
            ) : (
              <div className="form-grid">
                <Field label="List" error={errors.value_list_id}>
                  <select value={f.value_list_id} onChange={(e) => setF({ ...f, value_list_id: e.target.value, list_level: 1, parent_field_id: "" })}>
                    <option value="">Select a list…</option>
                    {lists.map((l) => <option key={l.id} value={l.id}>{l.name} ({l.level_names.join(" › ")})</option>)}
                  </select>
                </Field>
                <Field label="Level of the list this field shows" error={errors.list_level}>
                  <select value={f.list_level} onChange={(e) => setF({ ...f, list_level: Number(e.target.value), parent_field_id: "" })} disabled={!chosenList}>
                    {(chosenList?.level_names || []).map((n, i) => <option key={i} value={i + 1}>Level {i + 1}: {n}</option>)}
                  </select>
                </Field>
                {Number(f.list_level) > 1 && (
                  <Field label="Depends on *" error={errors.parent_field_id} hint="The dropdown above this one. Only its choices' children are shown." full>
                    <select value={f.parent_field_id} onChange={set("parent_field_id")}>
                      <option value="">Select the dropdown above…</option>
                      {parents.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                    </select>
                    {parents.length === 0 && <span className="hint">Add a dropdown that uses level {Number(f.list_level) - 1} of this list first.</span>}
                  </Field>
                )}
              </div>
            )}
          </div>
        )}

        <div className="row wrap" style={{ gap: 22 }}>
          <span className="check"><input type="checkbox" checked={f.required} onChange={set("required")} /> Required</span>
          <span className="check"><input type="checkbox" checked={f.is_active} onChange={set("is_active")} /> Active</span>
        </div>
        <div>
          <div className="section-title">Where it is shown</div>
          <div className="row wrap">
            <span className="check"><input type="radio" checked={f.show_always} onChange={() => setF({ ...f, show_always: true })} /> Always</span>
            <span className="check"><input type="radio" checked={!f.show_always} onChange={() => setF({ ...f, show_always: false })} /> Only for scenarios I choose (set in the Scenarios tab)</span>
          </div>
        </div>
      </form>
    </Modal>
  );
}
