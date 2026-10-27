import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";
import api, { errorMessage, openProtectedFile } from "../api";
import ClientBilling from "../components/ClientBilling";
import { DialerIdsPanel } from "../components/DialerAdmin";
import OnboardingWizard from "../components/OnboardingWizard";
import { Badge, ClientStatus, CompanyAvatar, ErrorBox, Field, Modal, Spinner, fmtDateTime } from "../components/ui";

const Row = ({ label, children }) => (<><dt>{label}</dt><dd>{children || "—"}</dd></>);
const SERVICE_LABEL = { inbound: "Inbound calls", outbound: "Outbound calls", whatsapp: "WhatsApp", email: "Email support" };

export default function ClientDetail() {
  const { id } = useParams();
  const [c, setC] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState(false);
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const tab = params.get("tab") === "plan" && can("plans.view") ? "plan" : params.get("tab") === "dialer" ? "dialer" : "overview";
  const setTab = (t) => setParams(t === "overview" ? {} : { tab: t });
  const [dialog, setDialog] = useState(null); // {type, ...}
  const base = `/clients/${id}`;

  const load = useCallback(() => api.get(base).then((r) => setC(r.data)).catch((e) => setError(errorMessage(e))), [base]);
  useEffect(() => { load(); }, [load]);

  if (error && !c) return <ErrorBox error={error} />;
  if (!c) return <Spinner />;

  async function act(name, path, body, onOk) {
    setBusy(name); setError("");
    try {
      const { data } = await api.post(`${base}/${path}`, body);
      await load();
      onOk?.(data);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(""); }
  }

  async function reviewDoc(doc, status, note) {
    try { await api.put(`${base}/documents/${doc.id}/review`, { status, note: note || null }); await load(); }
    catch (e) { setError(errorMessage(e)); }
  }

  const adapter = {
    save: (body) => api.put(`${base}/onboarding`, body).then((r) => r.data),
    upload: (type, file) => { const fd = new FormData(); fd.append("doc_type", type); fd.append("file", file); return api.post(`${base}/documents`, fd).then((r) => r.data); },
    removeDoc: (docId) => api.delete(`${base}/documents/${docId}`).then((r) => r.data),
    uploadLogo: (file) => { const fd = new FormData(); fd.append("file", file); return api.post(`${base}/logo`, fd).then((r) => r.data); },
  };

  
  if (editing) {
    return (
      <>
        <div className="page-head">
          <div><h1>Edit {c.company_name || "client"}</h1><p>Changes are saved as you continue.</p></div>
          <button className="btn" onClick={() => { setEditing(false); load(); }}>← Back to review</button>
        </div>
        <OnboardingWizard adapter={adapter} initial={c} onSaved={() => load()} />
      </>
    );
  }

  return (
    <>
      <Link to="/clients" className="small">← All clients</Link>
      <div className="page-head" style={{ marginTop: 10 }}>
        <div className="row" style={{ gap: 16, minWidth: 0, alignItems: "flex-start" }}>
          <CompanyAvatar name={c.company_name} logo={c.logo_url} large />
          <div style={{ minWidth: 0 }}>
            <div className="row wrap"><h1 style={{ overflowWrap: "anywhere" }}>{c.company_name || "(not filled yet)"}</h1><ClientStatus status={c.status} /></div>
            <p>{c.code ? `Client code ${c.code} · ` : ""}Registered {fmtDateTime(c.submitted_at || c.created_at)}{c.source === "admin" ? " by admin" : ""}</p>
          </div>
        </div>
        <div className="row wrap">
          {(c.status === "active" || c.status === "suspended") && can("plans.view") && (
            <button className="btn btn-primary" onClick={() => setTab("plan")}>Plan &amp; billing</button>
          )}
          <button className="btn" onClick={() => setEditing(true)}>Edit details</button>
          {c.status === "submitted" && <>
            <button className="btn btn-danger" onClick={() => setDialog({ type: "reject" })}>Reject</button>
            <button className="btn btn-success" disabled={!!busy}
              onClick={() => act("activate", "activate", undefined, (d) => setDialog({ type: "welcome", data: d }))}>
              {busy === "activate" ? "Activating…" : "Activate client"}
            </button>
          </>}
          {c.status === "active" && <>
            <button className="btn" disabled={!!busy} onClick={() => act("resend", "resend-welcome", undefined, (d) => setDialog({ type: "welcome", data: d, resend: true }))}>Resend welcome</button>
            <button className="btn btn-danger" disabled={!!busy} onClick={() => { if (window.confirm("Suspend this client? Their users will be signed out and blocked.")) act("suspend", "suspend"); }}>Suspend</button>
          </>}
          {c.status === "suspended" && <button className="btn btn-success" disabled={!!busy} onClick={() => act("react", "reactivate")}>Re-activate</button>}
        </div>
      </div>

      <div className="tabs">
        {[["overview", "Overview"], ...(can("plans.view") ? [["plan", "Plan & billing"]] : []), ...(c.status === "active" || c.status === "suspended" ? [["dialer", "Dialer IDs"]] : [])].map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      <ErrorBox error={error} />
      {c.status === "submitted" && <div className="alert info" style={{ marginBottom: 14 }}>
        This client gave only the basic details. After you activate, they sign in and complete the address, documents and logo themselves.</div>}
      {c.status === "active" && !c.profile.complete && <div className="alert warn" style={{ marginBottom: 14 }}>
        Profile {c.profile.percent}% complete. Still missing: {c.profile.items.filter((i) => !i.done).map((i) => i.label).join(", ")}.</div>}
      {c.status === "rejected" && <div className="alert error" style={{ marginBottom: 14 }}><b>Rejected:</b> {c.review_note}</div>}

      {tab === "dialer" ? <DialerIdsPanel client={c} canManage={can("clients.manage")} /> : tab === "plan" ? <ClientBilling client={c} /> : (
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <div className="card card-pad">
            <div className="section-title">Company</div>
            <dl className="kv" style={{ gridTemplateColumns: "110px minmax(0, 1fr)" }}>
              <Row label="Business type">{c.business_type}</Row>
              <Row label="GSTIN"><span className="mono">{c.gstin}</span></Row>
              <Row label="PAN"><span className="mono">{c.pan}</span></Row>
              <Row label="Website">{c.website}</Row>
              <Row label="Services">{c.services.map((s) => SERVICE_LABEL[s] || s).join(", ")}</Row>
              <Row label="Volume">{c.monthly_volume}</Row>
            </dl>
          </div>
          <div className="card card-pad">
            <div className="section-title">Addresses</div>
            <dl className="kv" style={{ gridTemplateColumns: "110px minmax(0, 1fr)" }}>
              <Row label="Registered office">{[c.address, c.city, c.state, c.pincode].filter(Boolean).join(", ")}</Row>
              <Row label="Billing">{c.billing_same ? "Same as registered office" : [c.billing_address, c.billing_city, c.billing_state, c.billing_pincode].filter(Boolean).join(", ")}</Row>
              <Row label="Billing email">{c.billing_email}</Row>
            </dl>
          </div>
          <div className="card card-pad">
            <div className="section-title">Contact persons</div>
            {c.contacts.length === 0 ? <span className="muted">No contacts yet.</span> : c.contacts.map((p, i) => (
              <div key={i} className="doc-row">
                <div className="grow">
                  <b>{p.name || "(no name)"}</b> {i === 0 && <Badge tone="primary">Primary · login</Badge>}
                  <div className="small muted">{p.designation || "—"}</div>
                </div>
                <div className="small" style={{ textAlign: "right" }}>{p.mobile}<div className="muted">{p.email}</div></div>
              </div>
            ))}
          </div>
        </div>

        <div className="stack">
          <div className="card card-pad">
            <div className="section-title">Documents ({c.documents.length})</div>
            {c.documents.length === 0 ? <span className="muted">No documents uploaded yet. The client adds them after logging in.</span> : c.documents.map((d) => (
              <div key={d.id} className="doc-row" style={{ flexWrap: "wrap" }}>
                <div className="grow">
                  <div className="doc-name">{d.label}</div>
                  <button type="button" className="btn btn-ghost btn-sm" style={{ padding: 0, color: "var(--primary)" }}
                    onClick={() => openProtectedFile(`${base}/documents/${d.id}/file`).catch((e) => setError(errorMessage(e)))}>
                    📎 {d.name}
                  </button>
                  <span className="small muted"> · {(d.size / 1024).toFixed(0)} KB</span>
                  {d.note && <div className="small muted">Note: {d.note}</div>}
                </div>
                <span className={`badge ${d.status === "approved" ? "active" : d.status === "rejected" ? "rejected" : "draft"}`}>{d.status}</span>
                <div className="row gap-sm">
                  <button className="btn btn-sm" disabled={d.status === "approved"} onClick={() => reviewDoc(d, "approved")}>Approve</button>
                  <button className="btn btn-sm" disabled={d.status === "rejected"} onClick={() => setDialog({ type: "docreject", doc: d })}>Reject</button>
                </div>
              </div>
            ))}
          </div>
          <div className="card card-pad">
            <div className="section-title">Account</div>
            <dl className="kv" style={{ gridTemplateColumns: "110px minmax(0, 1fr)" }}>
              <Row label="Terms accepted">{c.terms_accepted ? fmtDateTime(c.terms_accepted_at) : "Not yet"}</Row>
              <Row label="Activated">{c.activated_at ? fmtDateTime(c.activated_at) : ""}</Row>
              <Row label="Logins">{c.users?.map((u) => `${u.email}${u.is_active ? "" : " (blocked)"}`).join(", ")}</Row>
            </dl>
          </div>
        </div>
      </div>)}

      {dialog?.type === "welcome" && <WelcomeResult dialog={dialog} onClose={() => setDialog(null)} />}
      {dialog?.type === "reject" && (
        <NoteModal title="Reject registration" label="Reason (sent to the client)" button="Reject" danger onClose={() => setDialog(null)}
          onSubmit={(note) => act("reject", "reject", { note }, () => setDialog(null))} />
      )}
      {dialog?.type === "docreject" && (
        <NoteModal title={`Reject ${dialog.doc.label}`} label="What is wrong with this document?" button="Reject document" danger onClose={() => setDialog(null)}
          onSubmit={async (note) => { await reviewDoc(dialog.doc, "rejected", note); setDialog(null); }} />
      )}
    </>
  );
}

function WelcomeResult({ dialog, onClose }) {
  const sent = dialog.data.welcome;
  return (
    <Modal title={dialog.resend ? "Welcome message sent again" : "Client activated 🎉"} onClose={onClose} footer={<button className="btn btn-primary" onClick={onClose}>Done</button>}>
      <p style={{ marginTop: 0 }}>The welcome message with the password-setup link was sent on:</p>
      {sent.map((s) => (
        <div key={s.channel} className="row" style={{ marginBottom: 6 }}>
          <b style={{ textTransform: "capitalize", width: 80 }}>{s.channel}</b>
          <span className="grow small muted">{s.to}</span>
          <span className={`badge ${s.status === "sent" ? "active" : s.status === "failed" ? "rejected" : "draft"}`}>
            {s.status === "logged" ? "Recorded" : s.status}
          </span>
        </div>
      ))}
      {sent.some((s) => s.status === "logged") && (
        <div className="alert info" style={{ marginTop: 12 }}>
          “Recorded” means the email / SMS / WhatsApp provider is not connected yet. The full text is in <Link to="/settings?tab=log">Settings → Notification log</Link>.
        </div>
      )}
    </Modal>
  );
}

function NoteModal({ title, label, button, danger, onClose, onSubmit }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose} footer={
      <><button className="btn" onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} disabled={busy || note.trim().length < 3}
          onClick={async () => { setBusy(true); await onSubmit(note.trim()); setBusy(false); }}>{button}</button></>}>
      <Field label={label}><textarea value={note} onChange={(e) => setNote(e.target.value)} autoFocus /></Field>
    </Modal>
  );
}
