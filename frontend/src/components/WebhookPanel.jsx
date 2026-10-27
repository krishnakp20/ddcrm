import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { Badge, CopyButton, ErrorBox, Field, Spinner, fmtDateTime, useToast } from "./ui";

/** The client's data webhook for a campaign, and the optional copy sent on to the dialer. */
export default function WebhookPanel({ campaign }) {
  const { user } = useAuth();
  const staff = user.user_type === "staff";
  const base = `/campaigns/${campaign.id}/webhook`;
  const [w, setW] = useState(null);
  const [fresh, setFresh] = useState(null);     // the key, shown once
  const [dialerUrl, setDialerUrl] = useState("");
  const [dialerAuth, setDialerAuth] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();

  const load = useCallback(() => api.get(base).then((r) => { setW(r.data); setDialerUrl(r.data.dialer_url || ""); }).catch((e) => setError(errorMessage(e))), [base]);
  useEffect(() => { load(); }, [load]);

  async function run(fn, ok) {
    setBusy(true); setError("");
    try { const { data } = await fn(); setW(data); setDialerUrl(data.dialer_url || ""); if (ok) setToast(ok); return data; }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  if (!w) return error ? <ErrorBox error={error} /> : <Spinner />;
  const url = fresh?.url || `${w.base_url}/api/hooks/leads/<your-key>`;
  const sample = JSON.stringify({ leads: [{ name: "Asha Verma", mobile: "9811122233", email: "asha@example.com", city: "Pune", policy_no: "POL123", premium_due: "1200" }] }, null, 2);

  return (
    <div className="card">
      <div className="card-head">
        <h3>Data webhook</h3>
        {w.exists ? <Badge tone={w.is_active ? "success" : "warn"}>{w.is_active ? "On" : "Off"}</Badge> : <Badge>Not set up</Badge>}
      </div>
      <div className="card-body stack">
        <ErrorBox error={error} />
        <p className="muted" style={{ margin: 0 }}>The client's system can post names and numbers straight into this campaign. Each record needs a <b>name</b> and a <b>mobile</b>; other fields are kept and shown to the agent. Numbers already in the campaign are skipped.</p>

        {fresh && (
          <div className="alert warn stack" style={{ gap: 6 }}>
            <b>Copy the address now. It is shown only once.</b>
            <div className="copy-box"><code>{fresh.url}</code><CopyButton text={fresh.url} /></div>
          </div>
        )}

        <div className="row wrap">
          <button className="btn btn-primary" disabled={busy} onClick={async () => {
            if (w.exists && !window.confirm("Make a new key? The old key stops working immediately.")) return;
            const d = await run(() => api.post(`${base}/key`), "Key created");
            if (d) setFresh({ url: d.url });
          }}>{w.exists ? "Make a new key" : "Create the webhook key"}</button>
          {w.exists && <button className="btn" disabled={busy} onClick={() => run(() => api.put(base, { is_active: !w.is_active }), w.is_active ? "Webhook turned off" : "Webhook turned on")}>{w.is_active ? "Turn off" : "Turn on"}</button>}
          {w.exists && <span className="small muted">Key starts with {w.token_hint}… · {w.accepted_total} record(s) received{w.last_used_at ? ` · last used ${fmtDateTime(w.last_used_at)}` : ""}</span>}
        </div>

        <div>
          <div className="section-title">How the client sends data</div>
          <div className="copy-box"><code>POST {url}</code></div>
          <code className="block" style={{ marginTop: 8 }}>{`curl -X POST "${url}" \\\n  -H "Content-Type: application/json" \\\n  -d '${sample.replace(/\n\s*/g, " ")}'`}</code>
          <p className="small muted" style={{ margin: "8px 0 0" }}>
            Send one record, a list, or <span className="mono">{"{\"leads\": [...]}"}</span> (up to 500 per call, 60 calls a minute). Names accepted: <span className="mono">name</span> / <span className="mono">customer_name</span>; <span className="mono">mobile</span> / <span className="mono">phone</span>; <span className="mono">email</span>, <span className="mono">city</span>, <span className="mono">ref</span> / <span className="mono">policy_no</span>. The reply lists each record as accepted, duplicate or invalid.
          </p>
        </div>

        {w.exists && (
          <div>
            <div className="section-title">Copy to the dialer</div>
            {staff ? (
              <div className="stack">
                <div className="form-grid">
                  <Field label="Dialer address (https://…)" hint="New data from the webhook and from uploads is also posted here as JSON: campaign, campaign_ids and leads (name, mobile).">
                    <input value={dialerUrl} onChange={(e) => setDialerUrl(e.target.value)} placeholder="https://dialer.example.com/api/leads" />
                  </Field>
                  <Field label="Authorization header (optional)" hint={w.dialer_auth_set ? "A value is saved. Type a new one to replace it." : "Sent as the Authorization header."}>
                    <input type="password" value={dialerAuth} onChange={(e) => setDialerAuth(e.target.value)} autoComplete="off" />
                  </Field>
                </div>
                <div className="row">
                  <button className="btn" disabled={busy} onClick={async () => { await run(() => api.put(base, { dialer_url: dialerUrl, dialer_auth: dialerAuth || undefined }), "Dialer saved"); setDialerAuth(""); }}>Save dialer settings</button>
                  {w.dialer_auth_set && <button className="btn btn-ghost" onClick={() => run(() => api.put(base, { clear_dialer_auth: true }), "Header removed")}>Remove saved header</button>}
                </div>
                {w.dialer_campaign_ids.length === 0 && <div className="small muted">This campaign has no dialer campaign ID yet (see Details), so the dialer will not know which campaign the data is for.</div>}
              </div>
            ) : <div className="small muted">{w.dialer_url ? "New data is also sent to the dialer." : "The dialer copy is set up by DialDesk."}</div>}
          </div>
        )}

        {w.logs.length > 0 && (
          <div>
            <div className="section-title">Recent deliveries</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>When</th><th>From</th><th>Received</th><th>Added</th><th>Duplicate</th><th>Invalid</th><th>Dialer</th></tr></thead>
                <tbody>{w.logs.map((l) => <tr key={l.id}><td className="small">{fmtDateTime(l.created_at)}</td><td>{l.source === "upload" ? "File upload" : "Webhook"}</td><td>{l.received}</td><td>{l.accepted}</td><td>{l.duplicates}</td><td>{l.invalid}</td><td className="small">{l.dialer_status || "—"}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
      </div>
      {toastEl}
    </div>
  );
}
