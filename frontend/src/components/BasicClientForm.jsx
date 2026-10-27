import { useEffect, useState } from "react";
import api, { errorMessage, fieldErrors } from "../api";
import { ErrorBox, Field, Modal } from "./ui";

const EMPTY = { company_name: "", gstin: "", city: "", contact_name: "", designation: "", mobile: "", email: "", website: "" };

/**
 * The short company form: company, GSTIN and one contact person.
 * Used on the public registration page (needs terms) and by the admin to add a client directly.
 */
export default function BasicClientForm({ endpoint, submitLabel, withTerms, withActivate, onDone }) {
  const [f, setF] = useState(EMPTY);
  const [terms, setTerms] = useState(false);
  const [activate, setActivate] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [meta, setMeta] = useState(null);

  useEffect(() => { api.get("/public/meta").then((r) => setMeta(r.data)); }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const stateOf = meta && f.gstin.length >= 2 ? meta.gst_codes[f.gstin.slice(0, 2)] : null;

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(""); setErrors({});
    try {
      const { data } = await api.post(endpoint, { ...f, terms_accepted: terms, activate_now: activate });
      onDone(data);
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
    } finally { setBusy(false); }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <ErrorBox error={error} />
      <div className="form-grid">
        <Field label="Company name *" error={errors.company_name} full><input value={f.company_name} onChange={set("company_name")} autoFocus /></Field>
        <Field label="GSTIN *" error={errors.gstin} hint={stateOf ? `State: ${stateOf}` : "15 characters, for example 09AAGCC4479E2ZG"}>
          <input className={`mono ${errors.gstin ? "invalid" : ""}`} value={f.gstin} maxLength={15}
            onChange={(e) => setF({ ...f, gstin: e.target.value.toUpperCase().replace(/\s/g, "") })} />
        </Field>
        <Field label="City" error={errors.city}><input value={f.city} onChange={set("city")} /></Field>
      </div>
      <div className="section-title" style={{ margin: "6px 0 -4px" }}>Contact person</div>
      <div className="form-grid">
        <Field label="Name *" error={errors.contact_name}><input value={f.contact_name} onChange={set("contact_name")} /></Field>
        <Field label="Designation" error={errors.designation}><input value={f.designation} onChange={set("designation")} placeholder="e.g. Operations head" /></Field>
        <Field label="Mobile *" error={errors.mobile}><input value={f.mobile} onChange={set("mobile")} inputMode="tel" placeholder="10-digit number" /></Field>
        <Field label="Email *" error={errors.email} hint="This will be your login email"><input type="email" value={f.email} onChange={set("email")} /></Field>
      </div>

      {/* hidden trap for spam bots; people never see or fill it */}
      <input tabIndex={-1} autoComplete="off" aria-hidden="true" value={f.website} onChange={set("website")}
        style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }} />

      {withTerms && (
        <div>
          <span className="check">
            <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
            I accept the <button type="button" className="btn btn-ghost btn-sm" style={{ padding: "0 4px", color: "var(--primary)" }} onClick={() => setShowTerms(true)}>Terms & Conditions</button> *
          </span>
          {errors.terms && <div className="small" style={{ color: "var(--danger)", marginTop: 4 }}>{errors.terms}</div>}
        </div>
      )}
      {withActivate && (
        <span className="check"><input type="checkbox" checked={activate} onChange={(e) => setActivate(e.target.checked)} /> Activate now and send the welcome message</span>
      )}
      <button className="btn btn-primary btn-lg" disabled={busy || (withTerms && !terms)}>{busy ? "Please wait…" : submitLabel}</button>

      {showTerms && (
        <Modal title="Terms & Conditions" onClose={() => setShowTerms(false)} footer={<button type="button" className="btn btn-primary" onClick={() => { setTerms(true); setShowTerms(false); }}>I accept</button>}>
          <div className="stack small">
            <p style={{ margin: 0 }}>Placeholder text: replace with your final Terms & Conditions before going live.</p>
            <p style={{ margin: 0 }}>1. The information you submit is true and complete.</p>
            <p style={{ margin: 0 }}>2. DialDesk may verify it and may reject or suspend an account that is found to be incorrect.</p>
            <p style={{ margin: 0 }}>3. Customer data processed on the platform belongs to you and is used only to deliver the service.</p>
          </div>
        </Modal>
      )}
    </form>
  );
}

export function AddClientModal({ onClose, onDone }) {
  return (
    <Modal title="Add a client" onClose={onClose}>
      <p className="muted" style={{ marginTop: 0 }}>Enter the basics. The client completes the rest of the profile after logging in.</p>
      <BasicClientForm endpoint="/clients" submitLabel="Add client" withActivate onDone={onDone} />
    </Modal>
  );
}
