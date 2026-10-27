import { useState } from "react";
import api, { errorMessage, fieldErrors } from "../../api";
import { Badge, Empty, ErrorBox, Field, Modal } from "../ui";

/** The call scenario (disposition) tree: up to 5 levels, with the fields each scenario brings along. */
export default function ScenariosTab({ cfg, base, reload, canManage }) {
  const [open, setOpen] = useState({});        // expanded nodes
  const [dialog, setDialog] = useState(null);  // {mode: "add"|"edit", parent?, node?}
  const [error, setError] = useState("");
  const max = cfg.options.max_levels;
  const outcomes = cfg.options.outcomes;
  const fieldById = Object.fromEntries(cfg.fields.map((f) => [f.id, f]));

  async function act(fn) {
    setError("");
    try { await fn(); reload(); } catch (e) { setError(errorMessage(e)); }
  }
  const move = (n, direction) => act(() => api.post(`/scenarios/${n.id}/move`, { direction }));
  const remove = (n) => {
    const kids = countAll(n) - 1;
    if (!window.confirm(`Delete “${n.name}”${kids ? ` and the ${kids} option(s) under it` : ""}?`)) return;
    act(() => api.delete(`/scenarios/${n.id}`));
  };

  function Node({ n, index, total }) {
    const kids = n.children.length;
    const isOpen = open[n.id] ?? n.level === 1;
    return (
      <div>
        <div className={`sc-row ${n.is_active ? "" : "off"}`} style={{ paddingLeft: 10 + (n.level - 1) * 22 }}>
          <button className="btn btn-sm btn-ghost sc-caret" onClick={() => setOpen({ ...open, [n.id]: !isOpen })} disabled={!kids}>{kids ? (isOpen ? "▾" : "▸") : "·"}</button>
          <span className="badge primary">L{n.level}</span>
          <span className="grow"><b>{n.name}</b>
            {n.outcome && !kids && <> <Badge tone="success">{outcomes[n.outcome]}</Badge></>}
            {n.fields.length > 0 && <> <Badge tone="warn">{n.fields.length} field{n.fields.length === 1 ? "" : "s"}</Badge></>}
            {!n.is_active && <> <Badge>Off</Badge></>}
          </span>
          {canManage && (
            <span className="row gap-sm sc-actions">
              <button className="btn btn-sm btn-ghost" disabled={index === 0} onClick={() => move(n, "up")}>↑</button>
              <button className="btn btn-sm btn-ghost" disabled={index === total - 1} onClick={() => move(n, "down")}>↓</button>
              {n.level < max && <button className="btn btn-sm" onClick={() => { setOpen({ ...open, [n.id]: true }); setDialog({ mode: "add", parent: n }); }}>+ Sub</button>}
              <button className="btn btn-sm" onClick={() => setDialog({ mode: "edit", node: n })}>Edit</button>
              <button className="btn btn-sm btn-ghost" onClick={() => remove(n)}>Delete</button>
            </span>
          )}
        </div>
        {isOpen && n.children.map((c, i) => <Node key={c.id} n={c} index={i} total={n.children.length} />)}
      </div>
    );
  }

  return (
    <>
      <div className="row spread wrap" style={{ marginBottom: 14 }}>
        <p className="muted" style={{ margin: 0, maxWidth: 680 }}>
          What the call was about, from broad to specific (up to {max} levels). The agent picks one option at each level. On any option you can choose which extra fields appear and which are mandatory.
        </p>
        {canManage && <button className="btn btn-primary" onClick={() => setDialog({ mode: "add", parent: null })}>+ Add level 1 option</button>}
      </div>
      <ErrorBox error={error} />
      <div className="card" style={{ padding: "6px 0" }}>
        {cfg.scenarios.length === 0 ? <Empty>No scenarios yet. Add the first level 1 option, for example “Enquiry Call”.</Empty> :
          cfg.scenarios.map((n, i) => <Node key={n.id} n={n} index={i} total={cfg.scenarios.length} />)}
      </div>
      {dialog && <ScenarioModal dialog={dialog} cfg={cfg} base={base} fieldById={fieldById} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); reload(); }} />}
    </>
  );
}

function countAll(n) { return 1 + n.children.reduce((a, c) => a + countAll(c), 0); }

function ScenarioModal({ dialog, cfg, base, onClose, onSaved }) {
  const adding = dialog.mode === "add";
  const node = dialog.node;
  const [name, setName] = useState(node?.name || "");
  const [outcome, setOutcome] = useState(node?.outcome || "");
  const [active, setActive] = useState(node?.is_active ?? true);
  // links: field id -> {show, required}
  const [links, setLinks] = useState(() => Object.fromEntries((node?.fields || []).map((l) => [l.field_id, { show: true, required: l.required }])));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const level = adding ? (dialog.parent ? dialog.parent.level + 1 : 1) : node.level;
  const hasKids = !adding && node.children.length > 0;

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(""); setErrors({});
    try {
      let id = node?.id;
      if (adding) {
        const { data } = await api.post(`${base}/scenarios`, { name, parent_id: dialog.parent?.id ?? null, outcome: outcome || null, is_active: active });
        id = data.id;
      } else {
        await api.put(`/scenarios/${id}`, { name, outcome: outcome || null, is_active: active, parent_id: node.parent_id });
      }
      const chosen = Object.entries(links).filter(([, v]) => v.show || v.required).map(([fid, v]) => ({ field_id: Number(fid), required: v.required }));
      if (adding ? chosen.length : true) await api.put(`/scenarios/${id}/fields`, { links: chosen });
      onSaved();
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); } finally { setBusy(false); }
  }

  const setLink = (fid, patch) => setLinks({ ...links, [fid]: { show: false, required: false, ...(links[fid] || {}), ...patch } });
  const fields = cfg.fields.filter((f) => f.is_active);

  return (
    <Modal title={adding ? `Add level ${level} option${dialog.parent ? ` under “${dialog.parent.name}”` : ""}` : `Edit: ${node.name}`} wide onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="sc-form" disabled={busy}>{busy ? "Saving…" : "Save"}</button></>}>
      <form id="sc-form" className="stack" onSubmit={save}>
        <ErrorBox error={error} />
        <div className="form-grid">
          <Field label="Name *" error={errors.name}><input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Complaint" /></Field>
          <Field label="Outcome when the call ends here" error={errors.outcome} hint={hasKids ? "Used when this is the last level chosen" : "Drives follow-up and reports"}>
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">No outcome</option>
              {Object.entries(cfg.options.outcomes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
        </div>
        <span className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active (agents can choose it)</span>

        <div>
          <div className="section-title">Fields for this option (and everything under it)</div>
          {fields.length === 0 ? <div className="muted small">Add fields in the Fields tab first.</div> : (
            <div className="card">
              <table>
                <thead><tr><th>Field</th><th>Show</th><th>Mandatory here</th></tr></thead>
                <tbody>
                  {fields.map((f) => {
                    const l = links[f.id] || { show: false, required: false };
                    return (
                      <tr key={f.id}>
                        <td><b>{f.label}</b>{f.required && <> <Badge tone="warn">always mandatory</Badge></>}</td>
                        <td>{f.show_always ? <span className="muted small">Always shown</span> :
                          <input type="checkbox" checked={!!l.show} onChange={(e) => setLink(f.id, { show: e.target.checked, required: e.target.checked ? l.required : false })} />}</td>
                        <td><input type="checkbox" checked={!!l.required} disabled={f.required || (!f.show_always && !l.show)}
                          onChange={(e) => setLink(f.id, { required: e.target.checked, show: f.show_always ? false : true })} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </form>
    </Modal>
  );
}
