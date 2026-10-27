import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { ErrorBox, Field, PageHead, Spinner } from "../components/ui";
import { MODE, rs } from "./Plans";

const OPTION_LABEL = (key, v) => (key === "plan_mode" ? MODE[v] : v.charAt(0).toUpperCase() + v.slice(1));

/** Create or edit a plan. The fields come from the server (GET /plans/schema), so they always match its rules. */
export default function PlanForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [schema, setSchema] = useState(null);
  const [values, setValues] = useState(null);
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/plans/schema").then((r) => {
      setSchema(r.data);
      if (!id) return setValues({ plan_name: "", plan_type: "", plan_mode: "", ...r.data.defaults });
      api.get(`/plans/${id}`).then((p) => { setValues(p.data.values); setNotes(p.data.notes || ""); }).catch((e) => setError(errorMessage(e)));
    });
  }, [id]);

  if (error && !values) return <ErrorBox error={error} />;
  if (!schema || !values) return <Spinner />;

  const set = (key, v) => setValues({ ...values, [key]: v });

  async function save() {
    setBusy(true); setError(""); setErrors({});
    try {
      const { data } = id ? await api.put(`/plans/${id}`, { values, notes }) : await api.post("/plans", { values, notes });
      navigate(`/plans/${data.id}`);
    } catch (e) {
      setErrors(fieldErrors(e));
      setError(errorMessage(e));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally { setBusy(false); }
  }

  function control(f) {
    const v = values[f.key];
    const err = errors[f.key];
    const cls = err ? "invalid" : "";
    switch (f.kind) {
      case "select":
        return (
          <select className={cls} value={v} onChange={(e) => set(f.key, e.target.value)}>
            <option value="">Select…</option>
            {f.options.map((o) => <option key={o} value={o}>{OPTION_LABEL(f.key, o)}</option>)}
          </select>
        );
      case "pulse":
        return (
          <select className={cls} value={v} onChange={(e) => set(f.key, Number(e.target.value))}>
            {schema.pulses.map((p) => <option key={p} value={p}>{p} second{p > 1 ? "s" : ""}</option>)}
          </select>
        );
      case "bool":
        return <span className="check" style={{ padding: "8px 0" }}><input type="checkbox" checked={!!v} onChange={(e) => set(f.key, e.target.checked)} /> {v ? "Yes" : "No"}</span>;
      case "text":
        return <input className={cls} value={v} onChange={(e) => set(f.key, e.target.value)} autoFocus={f.key === "plan_name"} />;
      default:
        return <input className={cls} type="number" min="0" step={f.kind === "int" ? "1" : "any"} inputMode="decimal" value={v}
          onChange={(e) => set(f.key, e.target.value)} />;
    }
  }

  return (
    <>
      <PageHead title={id ? "Edit plan" : "Add plan"} sub="Amounts are in rupees. Call charges are per minute; the rate per pulse is worked out for you.">
        <Link className="btn" to={id ? `/plans/${id}` : "/plans"}>Cancel</Link>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : id ? "Save changes" : "Save plan"}</button>
      </PageHead>
      <ErrorBox error={error} />
      <div className="stack">
        {schema.sections.map((s) => (
          <div className="card card-pad" key={s.id}>
            <div className="section-title">{s.title}</div>
            <div className="form-grid">
              {s.fields.filter((f) => f.kind !== "pulse").map((f) => {
                const pulseField = f.pair ? schema.sections.flatMap((x) => x.fields).find((x) => x.key === f.pair[0]) : null;
                const per = f.pair ? (Number(values[f.key] || 0) * Number(values[f.pair[0]] || 60)) / 60 : null;
                return (
                  <div key={f.key} className="stack" style={{ gap: 8 }}>
                    <Field label={`${f.label}${f.unit ? ` (${f.unit})` : ""}${f.required ? " *" : ""}`} error={errors[f.key]} hint={f.hint}>
                      {control(f)}
                    </Field>
                    {pulseField && (
                      <Field label={`${pulseField.label}`} error={errors[pulseField.key]}>
                        {control(pulseField)}
                        <span className="hint">Rate per pulse: <b>{rs(per)}</b> for every {values[f.pair[0]]} seconds</span>
                      </Field>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        <div className="card card-pad">
          <Field label="Internal notes" hint="Only DialDesk staff see this"><textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </div>
        <div className="row"><div className="grow" /><button className="btn btn-primary btn-lg" disabled={busy} onClick={save}>{busy ? "Saving…" : id ? "Save changes" : "Save plan"}</button></div>
      </div>
    </>
  );
}
