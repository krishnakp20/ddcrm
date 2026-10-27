import { useEffect, useMemo, useState } from "react";
import api, { errorMessage, fieldErrors } from "./../api";
import { ErrorBox, Field } from "./ui";

const EMPTY_CONTACT = { name: "", designation: "", mobile: "", email: "" };
const FIELDS = [
  "company_name", "business_type", "website", "gstin", "pan", "address", "city", "state", "pincode", "billing_same",
  "billing_address", "billing_city", "billing_state", "billing_pincode", "billing_email", "services", "monthly_volume",
];
const STEP_OF = (key) => (key.startsWith("contacts") ? 2 : key === "documents" ? 3 : 1);

function pick(data) {
  return Object.fromEntries(FIELDS.map((k) => [k, data[k] ?? (k === "services" ? [] : k === "billing_same" ? true : "")]));
}

/**
 * The company profile form in 3 steps (company, contact persons, documents and logo).
 * `adapter` decides where data goes: the admin editing any client, or a client editing its own profile.
 * `lockIdentity` (client editing itself): company name, GSTIN, PAN and the login email can only be changed by DialDesk.
 */
export default function OnboardingWizard({ adapter, initial, lockIdentity = false, onSaved }) {
  const [meta, setMeta] = useState(null);
  const [step, setStep] = useState(1);
  const [f, setF] = useState(() => pick(initial));
  const [contacts, setContacts] = useState(() => {
    const list = initial.contacts?.length ? [...initial.contacts] : [{ ...EMPTY_CONTACT }];
    while (list.length < 3) list.push({ ...EMPTY_CONTACT });
    return list;
  });
  const [docs, setDocs] = useState(initial.documents || []);
  const [logo, setLogo] = useState(initial.logo_url);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => { api.get("/public/meta").then((r) => setMeta(r.data)); }, []);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const err = (k) => errors[k];

  // typing a GSTIN fills the state and PAN, as they are contained in it
  function onGstin(e) {
    const gstin = e.target.value.toUpperCase().replace(/\s/g, "").slice(0, 15);
    const next = { ...f, gstin };
    if (gstin.length >= 2 && meta?.gst_codes?.[gstin.slice(0, 2)]) next.state = meta.gst_codes[gstin.slice(0, 2)];
    if (gstin.length === 15) next.pan = gstin.slice(2, 12);
    setF(next);
  }

  const setContact = (i, k) => (e) => setContacts(contacts.map((c, j) => (j === i ? { ...c, [k]: e.target.value } : c)));

  // the server numbers contacts after dropping blank rows; keep a map so errors land on the right row
  const filled = useMemo(() => contacts.map((c, i) => [c, i]).filter(([c]) => Object.values(c).some((v) => v.trim())), [contacts]);

  function applyErrors(fields) {
    const mapped = {};
    for (const [k, v] of Object.entries(fields)) {
      const m = k.match(/^contacts\.(\d+)\.(.+)$/);
      mapped[m ? `contacts.${filled[Number(m[1])]?.[1] ?? m[1]}.${m[2]}` : k] = v;
    }
    setErrors(mapped);
    return mapped;
  }

  async function save() {
    setErrors({}); setError(""); setSaved("");
    try {
      await adapter.save({ ...f, contacts: filled.map(([c]) => c) });
      return true;
    } catch (e) {
      const mapped = applyErrors(fieldErrors(e));
      setError(errorMessage(e));
      const first = Object.keys(mapped)[0];
      if (first) setStep(STEP_OF(first));
      return false;
    }
  }

  async function next() {
    setBusy(true);
    const ok = await save();
    setBusy(false);
    if (ok) { setStep(step + 1); window.scrollTo({ top: 0, behavior: "smooth" }); }
  }

  async function finish() {
    setBusy(true);
    const ok = await save();
    setBusy(false);
    if (ok) { setSaved("Saved. Your changes are updated."); onSaved?.(); }
  }

  async function upload(type, file) {
    if (!file) return;
    setUploading(type); setError("");
    try {
      const data = await adapter.upload(type, file);
      setDocs(data.documents);
      onSaved?.();
    } catch (e) { setError(errorMessage(e)); } finally { setUploading(""); }
  }

  async function removeDoc(id) {
    setError("");
    try { setDocs((await adapter.removeDoc(id)).documents); onSaved?.(); } catch (e) { setError(errorMessage(e)); }
  }

  async function uploadLogo(file) {
    if (!file) return;
    setUploading("logo"); setError("");
    try { setLogo((await adapter.uploadLogo(file)).logo_url); onSaved?.(); } catch (e) { setError(errorMessage(e)); } finally { setUploading(""); }
  }

  if (!meta) return <div className="center muted">Loading form…</div>;

  const steps = ["Company details", "Contact persons", "Documents & logo"];
  const stepHasError = (n) => Object.keys(errors).some((k) => errors[k] && STEP_OF(k) === n);
  const lockedHint = lockIdentity ? "Only DialDesk can change this. Contact support if it is wrong." : undefined;

  return (
    <div>
      <div className="stepper">
        {steps.map((label, i) => (
          <div key={label} className={`step ${step === i + 1 ? "active" : ""} ${step > i + 1 ? "done" : ""}`} onClick={() => !busy && setStep(i + 1)}>
            <span className="n">{step > i + 1 ? "✓" : i + 1}</span>
            {label}
            {stepHasError(i + 1) && <span className="badge rejected" style={{ marginLeft: "auto" }}>Fix</span>}
          </div>
        ))}
      </div>

      <ErrorBox error={error} />
      {saved && <div className="alert success" style={{ marginBottom: 12 }}>{saved}</div>}

      {step === 1 && (
        <div className="stack">
          <div className="card card-pad">
            <div className="section-title">Company</div>
            <div className="form-grid">
              <Field label="Company name *" error={err("company_name")} hint={lockedHint} full>
                <input value={f.company_name} onChange={set("company_name")} disabled={lockIdentity} />
              </Field>
              <Field label="Business type">
                <select value={f.business_type} onChange={set("business_type")}>
                  <option value="">Select…</option>
                  {meta.business_types.map((t) => <option key={t}>{t}</option>)}
                </select>
              </Field>
              <Field label="Website" error={err("website")}><input value={f.website} onChange={set("website")} placeholder="www.example.com" /></Field>
              <Field label="GSTIN *" error={err("gstin")} hint={lockIdentity ? undefined : "15 characters. State and PAN are filled in from it."}>
                <input value={f.gstin} onChange={onGstin} disabled={lockIdentity} className={`mono ${err("gstin") ? "invalid" : ""}`} placeholder="09AAGCC4479E2ZG" />
              </Field>
              <Field label="PAN" error={err("pan")}>
                <input value={f.pan} onChange={(e) => setF({ ...f, pan: e.target.value.toUpperCase() })} className="mono" maxLength={10} disabled={lockIdentity} />
              </Field>
            </div>
          </div>

          <div className="card card-pad">
            <div className="section-title">Registered office</div>
            <div className="form-grid">
              <Field label="Address *" error={err("address")} full><textarea value={f.address} onChange={set("address")} style={{ minHeight: 64 }} /></Field>
              <Field label="City *" error={err("city")}><input value={f.city} onChange={set("city")} /></Field>
              <Field label="State *" error={err("state")}>
                <select value={f.state} onChange={set("state")} className={err("state") ? "invalid" : ""}>
                  <option value="">Select state…</option>
                  {meta.states.map((s) => <option key={s}>{s}</option>)}
                </select>
              </Field>
              <Field label="Pincode *" error={err("pincode")}><input value={f.pincode} onChange={set("pincode")} inputMode="numeric" maxLength={6} /></Field>
            </div>
          </div>

          <div className="card card-pad">
            <div className="row spread" style={{ marginBottom: 12 }}>
              <div className="section-title" style={{ margin: 0 }}>Billing address</div>
              <span className="check"><input type="checkbox" checked={f.billing_same} onChange={(e) => setF({ ...f, billing_same: e.target.checked })} /> Same as registered office</span>
            </div>
            {!f.billing_same && (
              <div className="form-grid" style={{ marginBottom: 14 }}>
                <Field label="Address *" error={err("billing_address")} full><textarea value={f.billing_address} onChange={set("billing_address")} style={{ minHeight: 64 }} /></Field>
                <Field label="City *" error={err("billing_city")}><input value={f.billing_city} onChange={set("billing_city")} /></Field>
                <Field label="State *" error={err("billing_state")}>
                  <select value={f.billing_state} onChange={set("billing_state")}>
                    <option value="">Select state…</option>
                    {meta.states.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </Field>
                <Field label="Pincode *" error={err("billing_pincode")}><input value={f.billing_pincode} onChange={set("billing_pincode")} inputMode="numeric" maxLength={6} /></Field>
              </div>
            )}
            <Field label="Billing email" error={err("billing_email")} hint="Invoices are sent here"><input type="email" value={f.billing_email} onChange={set("billing_email")} /></Field>
          </div>

          <div className="card card-pad">
            <div className="section-title">What do you need from DialDesk?</div>
            <div className="row wrap" style={{ marginBottom: 14 }}>
              {Object.entries(meta.services).map(([k, label]) => (
                <span key={k} className="check">
                  <input type="checkbox" checked={f.services.includes(k)}
                    onChange={(e) => setF({ ...f, services: e.target.checked ? [...f.services, k] : f.services.filter((x) => x !== k) })} /> {label}
                </span>
              ))}
            </div>
            <Field label="Expected volume">
              <select value={f.monthly_volume} onChange={set("monthly_volume")} style={{ maxWidth: 320 }}>
                <option value="">Select…</option>
                {meta.volumes.map((v) => <option key={v}>{v}</option>)}
              </select>
            </Field>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="stack">
          <div className="alert info">Details of at least one person are mandatory. The first contact is the account administrator.</div>
          {contacts.map((c, i) => (
            <div className="contact-card" key={i}>
              <div className="section-title">{i === 0 ? "Primary contact (account administrator) *" : `Contact person ${i + 1} (optional)`}</div>
              <div className="form-grid">
                <Field label={`Name${i === 0 ? " *" : ""}`} error={err(`contacts.${i}.name`)}><input value={c.name} onChange={setContact(i, "name")} /></Field>
                <Field label="Designation"><input value={c.designation} onChange={setContact(i, "designation")} placeholder="e.g. Operations head" /></Field>
                <Field label={`Mobile${i === 0 ? " *" : ""}`} error={err(`contacts.${i}.mobile`)}><input value={c.mobile} onChange={setContact(i, "mobile")} inputMode="tel" placeholder="10-digit number" /></Field>
                <Field label={`Email${i === 0 ? " *" : ""}`} error={err(`contacts.${i}.email`)}
                  hint={i === 0 ? (lockIdentity ? "This is your login email. Only DialDesk can change it." : "This is the login email") : ""}>
                  <input type="email" value={c.email} onChange={setContact(i, "email")} disabled={lockIdentity && i === 0} />
                </Field>
              </div>
            </div>
          ))}
          {contacts.length < 5 && (
            <div><button type="button" className="btn" onClick={() => setContacts([...contacts, { ...EMPTY_CONTACT }])}>+ Add another contact</button></div>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="stack">
          <div className="card card-pad">
            <div className="section-title">Documents</div>
            <p className="muted" style={{ margin: "0 0 8px" }}>
              Upload your documents here; the DialDesk team reviews each one. The GST certificate is the usual first one. PDF, JPG or PNG, up to {meta.limits.doc_mb} MB each.
            </p>
            {Object.entries(meta.doc_types).map(([type, label]) => {
              const mine = docs.filter((d) => d.doc_type === type);
              return (
                <div className="doc-row" key={type} style={{ alignItems: "flex-start" }}>
                  <div className="grow">
                    <div className="doc-name">{label}</div>
                    {mine.map((d) => (
                      <div key={d.id} className="row small wrap" style={{ marginTop: 4 }}>
                        <span>📎 {d.name}</span>
                        <span className={`badge ${d.status === "approved" ? "active" : d.status === "rejected" ? "rejected" : "draft"}`}>
                          {d.status === "pending" ? "waiting for review" : d.status}
                        </span>
                        {d.note && <span className="muted">{d.note}</span>}
                        {d.status !== "approved" && <button type="button" className="btn btn-sm btn-ghost" onClick={() => removeDoc(d.id)}>Remove</button>}
                      </div>
                    ))}
                  </div>
                  <span className="btn btn-sm file-btn">
                    {uploading === type ? "Uploading…" : mine.length ? "Add another" : "Choose file"}
                    <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => { upload(type, e.target.files[0]); e.target.value = ""; }} />
                  </span>
                </div>
              );
            })}
          </div>

          <div className="card card-pad">
            <div className="section-title">Company logo</div>
            <div className="row" style={{ gap: 18, alignItems: "center" }}>
              <div className="logo-preview">{logo ? <img src={logo} alt="Company logo" /> : <span className="muted small">No logo yet</span>}</div>
              <div>
                <p className="muted" style={{ margin: "0 0 8px" }}>Shown at the top of the screen whenever your team signs in. PNG, JPG or WebP, up to {meta.limits.logo_mb} MB. A wide logo on a plain background looks best.</p>
                <span className="btn btn-sm file-btn">
                  {uploading === "logo" ? "Uploading…" : logo ? "Replace logo" : "Choose logo"}
                  <input type="file" accept=".png,.jpg,.jpeg,.webp" onChange={(e) => { uploadLogo(e.target.files[0]); e.target.value = ""; }} />
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="row spread wizard-nav" style={{ marginTop: 22 }}>
        <button type="button" className="btn" disabled={step === 1 || busy} onClick={() => setStep(step - 1)}>← Previous</button>
        {step < 3 ? (
          <button type="button" className="btn btn-primary btn-lg" disabled={busy} onClick={next}>{busy ? "Saving…" : "Save & continue →"}</button>
        ) : (
          <button type="button" className="btn btn-success btn-lg" disabled={busy} onClick={finish}>{busy ? "Saving…" : "Save changes"}</button>
        )}
      </div>
    </div>
  );
}
