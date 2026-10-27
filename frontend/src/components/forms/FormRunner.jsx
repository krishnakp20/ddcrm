import { useEffect, useMemo, useState } from "react";
import api, { errorMessage, fieldErrors } from "../../api";
import { ErrorBox, Field } from "../ui";

/** Finds the chosen scenario nodes for a path of ids. */
function nodesOnPath(tree, path) {
  const out = [];
  let level = tree;
  for (const id of path) {
    const n = (level || []).find((x) => x.id === id);
    if (!n) break;
    out.push(n);
    level = n.children;
  }
  return out;
}

/** The fields that apply to a path, with whether each is mandatory (same rule as the server). */
export function visibleFor(fields, nodes) {
  const links = {};
  nodes.forEach((n) => n.fields.forEach((l) => { links[l.field_id] = links[l.field_id] || l.required; }));
  return fields.filter((f) => f.is_active).flatMap((f) => {
    if (f.show_always) return [{ f, required: f.required || !!links[f.id] }];
    if (f.id in links) return [{ f, required: f.required || !!links[f.id] }];
    return [];
  });
}

/**
 * The form an agent fills in: scenario levels first, then the fields that scenario needs.
 * Used for the setup preview now; the call screen and ticket screen will use the same component.
 */
export default function FormRunner({ cfg, base, onChecked, onSubmit, submitLabel, children, disabled }) {
  const [path, setPath] = useState([]);
  const [answers, setAnswers] = useState({});
  const [options, setOptions] = useState({});      // field id -> choices currently available
  const [chosenItem, setChosenItem] = useState({}); // field id -> the list item picked (children depend on it)
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const nodes = useMemo(() => nodesOnPath(cfg.scenarios, path), [cfg.scenarios, path]);
  const visible = useMemo(() => visibleFor(cfg.fields, nodes), [cfg.fields, nodes]);

  // reset when the form changes (another client or call type)
  useEffect(() => { setPath([]); setAnswers({}); setChosenItem({}); setOptions({}); setErrors({}); setResult(null); }, [cfg.client.id, cfg.context]);

  // load the choices of every dropdown that can show right now
  useEffect(() => {
    visible.forEach(async ({ f }) => {
      if (!["select", "multiselect", "radio"].includes(f.field_type) || !f.value_list_id) return;
      const parent = f.parent_field_id ? chosenItem[f.parent_field_id] : null;
      if (f.parent_field_id && !parent) { setOptions((o) => (o[f.id] ? { ...o, [f.id]: [] } : o)); return; }
      const { data } = await api.get(`/value-lists/${f.value_list_id}/items`, { params: { parent_id: parent?.id, active_only: true } });
      setOptions((o) => ({ ...o, [f.id]: data }));
    });
  }, [visible, chosenItem]);  // eslint-disable-line react-hooks/exhaustive-deps

  function chooseScenario(level, id) {
    setPath(id ? [...path.slice(0, level - 1), Number(id)] : path.slice(0, level - 1));
    setResult(null);
  }

  function setAnswer(f, value) {
    const next = { ...answers, [f.key]: value };
    const items = { ...chosenItem };
    if (["select", "radio"].includes(f.field_type)) {
      items[f.id] = (options[f.id] || []).find((o) => o.label === value) || null;
      // changing a dropdown clears everything that depends on it, all the way down
      const clear = (parentId) => cfg.fields.filter((x) => x.parent_field_id === parentId).forEach((child) => {
        delete next[child.key]; delete items[child.id]; clear(child.id);
      });
      clear(f.id);
    }
    setAnswers(next);
    setChosenItem(items);
    setResult(null);
  }

  async function check() {
    setBusy(true); setError(""); setErrors({}); setResult(null);
    try {
      if (onSubmit) { await onSubmit({ path, answers }); return; }  // live use: the caller saves the answers
      const { data } = await api.post(`${base}/check`, { path, answers });
      setResult(data);
      onChecked?.(data);
    } catch (e) { setErrors(fieldErrors(e)); setError(errorMessage(e)); } finally { setBusy(false); }
  }

  // scenario selectors: level 1, then one more level for each choice that has children
  const selectors = [];
  let level = cfg.scenarios.filter((n) => n.is_active);
  for (let i = 1; level && level.length > 0 && i <= 5; i++) {
    const chosen = nodes[i - 1];
    selectors.push({ level: i, options: level, chosen });
    level = chosen ? chosen.children.filter((n) => n.is_active) : null;
  }

  return (
    <div className="stack">
      {cfg.scenarios.length === 0 && <div className="alert info">No scenarios are set up for this form yet, so only the always-shown fields appear.</div>}
      <ErrorBox error={error && !Object.keys(errors).length ? error : ""} />
      {errors.scenario && <div className="alert error">{errors.scenario}</div>}

      {selectors.length > 0 && (
        <div className="card card-pad">
          <div className="section-title">Call scenario</div>
          <div className="form-grid">
            {selectors.map(({ level: lv, options: opts, chosen }) => (
              <Field key={lv} label={`Level ${lv}${lv === 1 ? " *" : ""}`}>
                <select value={chosen?.id || ""} onChange={(e) => chooseScenario(lv, e.target.value)}>
                  <option value="">Select…</option>
                  {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </Field>
            ))}
          </div>
          {nodes.length > 0 && nodes[nodes.length - 1].outcome && !nodes[nodes.length - 1].children.length && (
            <div className="small muted" style={{ marginTop: 8 }}>Outcome: <b>{cfg.options.outcomes[nodes[nodes.length - 1].outcome]}</b></div>
          )}
        </div>
      )}

      <div className="card card-pad">
        <div className="section-title">Details</div>
        {visible.length === 0 ? <div className="muted">No fields for this selection.</div> : (
          <div className="form-grid">
            {visible.map(({ f, required }) => (
              <RunnerField key={f.id} f={f} required={required} value={answers[f.key]} error={errors[f.key]}
                options={options[f.id]} blocked={!!f.parent_field_id && !chosenItem[f.parent_field_id]}
                parentLabel={cfg.fields.find((x) => x.id === f.parent_field_id)?.label} onChange={(v) => setAnswer(f, v)} />
            ))}
          </div>
        )}
      </div>

      {children}
      <div className="row spread wrap">
        <span className="muted small">{onSubmit ? "" : "This is a test; nothing is saved."}</span>
        <button className="btn btn-primary btn-lg" disabled={busy || disabled} onClick={check}>
          {busy ? (onSubmit ? "Saving…" : "Checking…") : submitLabel || "Check this form"}
        </button>
      </div>
      {result && (
        <div className="alert success">
          <b>The form is valid.</b> This is what would be saved:
          <pre className="mono" style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>{JSON.stringify({ scenario: result.scenario_path, answers: result.answers }, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function RunnerField({ f, required, value, error, options, blocked, parentLabel, onChange }) {
  const label = `${f.label}${required ? " *" : ""}`;
  const cls = error ? "invalid" : "";
  let input;
  switch (f.field_type) {
    case "textarea": input = <textarea className={cls} value={value || ""} onChange={(e) => onChange(e.target.value)} />; break;
    case "number": case "decimal": input = <input className={cls} type="number" step={f.field_type === "decimal" ? "any" : "1"} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />; break;
    case "date": input = <input className={cls} type="date" value={value || ""} onChange={(e) => onChange(e.target.value)} />; break;
    case "datetime": input = <input className={cls} type="datetime-local" value={value || ""} onChange={(e) => onChange(e.target.value)} />; break;
    case "time": input = <input className={cls} type="time" value={value || ""} onChange={(e) => onChange(e.target.value)} />; break;
    case "email": input = <input className={cls} type="email" value={value || ""} onChange={(e) => onChange(e.target.value)} />; break;
    case "phone": input = <input className={cls} inputMode="tel" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder="10-digit number" />; break;
    case "checkbox": input = <span className="check" style={{ padding: "8px 0" }}><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> Yes</span>; break;
    case "select":
      input = (
        <select className={cls} value={value || ""} disabled={blocked} onChange={(e) => onChange(e.target.value)}>
          <option value="">{blocked ? `Choose ${parentLabel} first` : "Select…"}</option>
          {(options || []).map((o) => <option key={o.id} value={o.label}>{o.label}</option>)}
        </select>
      );
      break;
    case "radio":
      input = <div className="row wrap">{(options || []).map((o) => <span key={o.id} className="check"><input type="radio" name={f.key} checked={value === o.label} onChange={() => onChange(o.label)} /> {o.label}</span>)}</div>;
      break;
    case "multiselect": {
      const picked = Array.isArray(value) ? value : [];
      input = <div className="row wrap">{(options || []).map((o) => (
        <span key={o.id} className="check"><input type="checkbox" checked={picked.includes(o.label)} onChange={(e) => onChange(e.target.checked ? [...picked, o.label] : picked.filter((x) => x !== o.label))} /> {o.label}</span>
      ))}</div>;
      break;
    }
    default: input = <input className={cls} value={value || ""} onChange={(e) => onChange(e.target.value)} />;
  }
  const full = ["textarea", "radio", "multiselect"].includes(f.field_type);
  return <Field label={label} error={error} hint={f.help_text || undefined} full={full}>{input}</Field>;
}
