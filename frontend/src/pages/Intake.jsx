import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { PRIORITIES } from "../components/TicketBits";
import { Badge, CopyButton, Empty, ErrorBox, Field, PageHead, Spinner, fmtDateTime, useToast } from "../components/ui";
import { useScope } from "../scope";

const RESULT = { created: ["Ticket created", "success"], appended: ["Added to a ticket", "primary"], duplicate: ["Repeat ignored", ""], rejected: ["Rejected", "danger"] };
const KIND = { website: "Website form", whatsapp: "WhatsApp", email: "Email" };

/** Where customers can write in: a website form, a WhatsApp bot, an email address. Each becomes tickets. */
export default function Intake() {
  const { user } = useAuth();
  const staff = user.user_type === "staff";
  const { clientId: scoped, clients } = useScope();
  const [cid, setCid] = useState("");
  const [data, setData] = useState(null);
  const [people, setPeople] = useState({ users: [], departments: [] });
  const [error, setError] = useState("");

  useEffect(() => { if (staff) setCid(scoped || String(clients[0]?.id || "")); }, [staff, scoped, clients]);
  const load = useCallback(() => {
    if (staff && !cid) return;
    const params = { client_id: cid || undefined };
    api.get("/intake/channels", { params }).then((r) => { setData(r.data); api.get("/tickets/assignees", { params: { client_id: r.data.client_id } }).then((a) => setPeople(a.data)).catch(() => {}); }).catch((e) => setError(errorMessage(e)));
  }, [cid, staff]);
  useEffect(() => { setData(null); load(); }, [load]);

  if (!data) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <>
      <PageHead title="Intake channels" sub={`Customers of ${data.client_name} can write in by website form, WhatsApp or email. Every message becomes a ticket, or a comment on the ticket it answers.`} />
      <ErrorBox error={error} />
      {staff && !scoped && clients.length > 1 && (
        <div className="card card-pad" style={{ marginBottom: 12 }}>
          <Field label="Client"><select value={cid} onChange={(e) => setCid(e.target.value)} style={{ maxWidth: 320 }}>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        </div>
      )}
      <div className="stack">
        {data.channels.map((ch) => <Channel key={ch.kind} ch={ch} data={data} people={people} cid={data.client_id} onChange={load} />)}
        <div className="card">
          <div className="card-head"><h3>Recent messages</h3></div>
          {data.logs.length === 0 ? <Empty>Nothing received yet.</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>When</th><th>Channel</th><th>Result</th><th>Ticket</th><th>Note</th></tr></thead>
                <tbody>{data.logs.map((l) => <tr key={l.id}><td className="small">{fmtDateTime(l.created_at)}</td><td>{KIND[l.kind]}</td><td><Badge tone={RESULT[l.result]?.[1]}>{RESULT[l.result]?.[0] || l.result}</Badge></td><td className="mono small">{l.ticket || "—"}</td><td className="small muted">{l.detail || ""}</td></tr>)}</tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Channel({ ch, data, people, cid, onChange }) {
  const [fresh, setFresh] = useState(null);   // the new key, shown once
  const [f, setF] = useState({ priority: ch.priority, user: ch.assigned_user_id || "", dept: ch.assigned_department_id || "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();
  const params = { client_id: cid };
  useEffect(() => setF({ priority: ch.priority, user: ch.assigned_user_id || "", dept: ch.assigned_department_id || "" }), [ch.priority, ch.assigned_user_id, ch.assigned_department_id]);

  async function run(fn, ok) {
    setBusy(true); setError("");
    try { const r = await fn(); if (ok) setToast(ok); onChange(); return r; } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const key = async () => {
    if (ch.exists && !window.confirm("Make a new key? The old one stops working immediately, so the address must be updated where it is used.")) return;
    const r = await run(() => api.post(`/intake/channels/${ch.kind}/key`, null, { params }), "Key created");
    if (r) setFresh(r.data);
  };
  const save = () => run(() => api.put(`/intake/channels/${ch.kind}`, { priority: f.priority, assigned_user_id: f.user ? Number(f.user) : null, assigned_department_id: f.dept ? Number(f.dept) : null, clear_assignment: !f.user && !f.dept }, { params }), "Saved");

  const base = data.base_url;
  const url = fresh ? fresh.url : `${base}/api/intake/<your-key>/${ch.kind}`;
  const hp = '<input type="text" name="website_hp" style="display:none" tabindex="-1" autocomplete="off">';

  return (
    <div className="card">
      <div className="card-head">
        <h3>{ch.label}</h3>
        {ch.exists ? <Badge tone={ch.is_active ? "success" : "warn"}>{ch.is_active ? "On" : "Off"}</Badge> : <Badge>Not set up</Badge>}
      </div>
      <div className="card-body stack">
        <ErrorBox error={error} />
        {fresh && (
          <div className="alert warn stack" style={{ gap: 6 }}>
            <b>Copy the address now. It is shown only once.</b>
            <div className="copy-box"><code>{fresh.url}</code><CopyButton text={fresh.url} /></div>
          </div>
        )}
        <div className="row wrap">
          <button className="btn btn-primary" disabled={busy} onClick={key}>{ch.exists ? "Make a new key" : "Create the key"}</button>
          {ch.exists && <button className="btn" disabled={busy} onClick={() => run(() => api.put(`/intake/channels/${ch.kind}`, { is_active: !ch.is_active }, { params }), ch.is_active ? "Turned off" : "Turned on")}>{ch.is_active ? "Turn off" : "Turn on"}</button>}
          {ch.exists && <span className="small muted">Key starts with {ch.token_hint}… · {ch.received_total} message(s){ch.last_used_at ? ` · last ${fmtDateTime(ch.last_used_at)}` : ""}</span>}
        </div>

        {ch.exists && (
          <div className="form-grid">
            <Field label="Priority of new tickets" hint="Sets the SLA time."><select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>{PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <span />
            <Field label="Give new tickets to"><select value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}><option value="">Nobody (a team member picks them up)</option>{people.users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.kind}</option>)}</select></Field>
            <Field label="Department"><select value={f.dept} onChange={(e) => setF({ ...f, dept: e.target.value })}><option value="">None</option>{people.departments.map((d) => <option key={d.id} value={d.id}>{d.name}{d.own ? "" : " (DialDesk)"}</option>)}</select></Field>
            <div><button className="btn" disabled={busy} onClick={save}>Save settings</button></div>
          </div>
        )}

        <div>
          <div className="section-title">How to connect</div>
          {ch.kind === "website" && (
            <div className="stack" style={{ gap: 8 }}>
              <p className="small muted" style={{ margin: 0 }}>Put this form on the client's website. Name, a message, and a mobile number or email are required. Any extra field you add is kept with the ticket. The hidden field catches robots.</p>
              <code className="block">{`<form method="post" action="${url}">\n  <input name="name" placeholder="Your name" required>\n  <input name="phone" placeholder="Mobile number">\n  <input name="email" type="email" placeholder="Email">\n  <textarea name="message" required></textarea>\n  ${hp}\n  <button>Send</button>\n</form>`}</code>
              <p className="small muted" style={{ margin: 0 }}>A normal form post shows a thank-you page with the ticket reference. A script can post JSON or <span className="mono">FormData</span> to the same address and gets <span className="mono">{"{\"ok\": true, \"reference\": \"T-000123\"}"}</span>. At most 10 posts a minute per visitor address.</p>
            </div>
          )}
          {ch.kind === "whatsapp" && (
            <div className="stack" style={{ gap: 8 }}>
              <p className="small muted" style={{ margin: 0 }}>
                <b>WhatsApp Cloud API:</b> in the Meta app, set the webhook <b>Callback URL</b> to the address above and the <b>Verify token</b> to the key (the part after <span className="mono">/api/intake/</span> and before <span className="mono">/whatsapp</span>); subscribe to <span className="mono">messages</span>.
                <br /><b>Any other bot or provider:</b> post JSON for each message:
              </p>
              <code className="block">{`POST ${url}\n{ "from": "919876543210", "name": "Customer name", "message": "Hello, my claim is pending", "message_id": "unique-id" }`}</code>
              <p className="small muted" style={{ margin: 0 }}>A new number makes a ticket. Later messages from the same number are added to its open ticket (a resolved ticket opens again). A repeated <span className="mono">message_id</span> is ignored.</p>
            </div>
          )}
          {ch.kind === "email" && (
            <div className="stack" style={{ gap: 8 }}>
              <p className="small muted" style={{ margin: 0 }}>Point your mail provider's inbound webhook (SendGrid, Mailgun, Postmark, or your own mail relay) for the support address at this address. JSON or form posts both work:</p>
              <code className="block">{`POST ${url}\n{ "from": "Anita <anita@example.com>", "subject": "Refund not received", "text": "…", "message_id": "<id@example.com>", "in_reply_to": "<earlier-id>" }`}</code>
              <p className="small muted" style={{ margin: 0 }}>A reply is added to its ticket when the subject contains the ticket number (for example <span className="mono">[T-000123]</span>) or <span className="mono">in_reply_to</span> matches an earlier message. Automatic replies and repeated messages are ignored.</p>
            </div>
          )}
        </div>
      </div>
      {toastEl}
    </div>
  );
}
