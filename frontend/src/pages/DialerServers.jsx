import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { Badge, CopyButton, Empty, ErrorBox, Field, Icon, Modal, PageHead, Spinner, fmtDateTime, useToast } from "../components/ui";

const STATUS = { ok: ["Receiving", "success"], late: ["Late", "warn"], silent: ["Silent", "danger"], never: ["Nothing yet", ""], off: ["Switched off", ""] };
const TABLE = { closer_log: "Inbound calls", log: "Outbound calls", recording_log: "Recordings", agent_log: "Agent log" };
const EMPTY = { name: "", timezone: "Asia/Kolkata", allowed_ips: "", default_client_id: "", recording_base_url: "", is_active: true };

/** The Vicidial servers that push call records, recordings and agent logs here. */
export default function DialerServers() {
  const [rows, setRows] = useState(null);
  const [clients, setClients] = useState([]);
  const [edit, setEdit] = useState(null);       // a server, or EMPTY for a new one
  const [shown, setShown] = useState(null);     // {server, key}: the key, shown once
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [toast, setToast, toastEl] = useToast();

  const load = useCallback(() => api.get("/dialer/servers").then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e))), []);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  useEffect(() => { api.get("/dashboard/clients").then((r) => setClients(r.data)).catch(() => {}); }, []);

  async function newKey(s) {
    if (!window.confirm(`Make a new key for ${s.name}? The old key stops working at once, so the script on that server must be updated.`)) return;
    try { const { data } = await api.post(`/dialer/servers/${s.id}/key`); setShown({ server: data, key: data.key }); load(); } catch (e) { setError(errorMessage(e)); }
  }

  if (!rows) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <>
      <PageHead title="Dialer servers" sub="Each Vicidial server sends its call records, recordings and agent logs here with its own key, only from the IP addresses you list.">
        <button className="btn btn-primary" onClick={() => setEdit(EMPTY)}><span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add server</button>
      </PageHead>
      <ErrorBox error={error} />
      {rows.length === 0 ? <div className="card"><Empty>No dialer server yet. Add one, then install the script on it (the steps appear after you add it).</Empty></div> : (
        <div className="stack">
          {rows.map((s) => (
            <div key={s.id} className="card">
              <div className="card-head">
                <div className="row"><h3>{s.name}</h3><Badge tone={STATUS[s.status][1]}>{STATUS[s.status][0]}</Badge></div>
                <div className="row wrap">
                  <button className="btn btn-sm" onClick={() => setDetail(s)}>Details &amp; pause codes</button>
                  <button className="btn btn-sm" onClick={() => setEdit({ ...s, allowed_ips: s.allowed_ips.join("\n"), default_client_id: s.default_client_id || "", recording_base_url: s.recording_base_url || "" })}>Edit</button>
                  <button className="btn btn-sm" onClick={() => newKey(s)}>New key</button>
                </div>
              </div>
              <div className="card-body">
                <dl className="kv" style={{ gridTemplateColumns: "150px minmax(0, 1fr)" }}>
                  <dt>Allowed IPs</dt><dd className="mono">{s.allowed_ips.length ? s.allowed_ips.join(", ") : <span style={{ color: "var(--danger)" }}>none: nothing is accepted</span>}</dd>
                  <dt>Time zone</dt><dd>{s.timezone}</dd>
                  <dt>Recordings from</dt><dd className="mono">{s.recording_base_url || <span className="muted">not set: recordings cannot be played</span>}</dd>
                  <dt>Only one client?</dt><dd>{s.default_client || <span className="muted">No: clients are found from the campaign and ingroup IDs</span>}</dd>
                  <dt>Key</dt><dd className="mono">{s.key_hint}…</dd>
                  <dt>Last data</dt>
                  <dd>
                    {s.last_seen_at ? <>{fmtDateTime(s.last_seen_at)} <span className="muted small">({s.silent_minutes} min ago)</span></> : "never"}
                    <div className="row wrap" style={{ marginTop: 4, gap: 6 }}>{Object.entries(s.last_seen).map(([t, v]) => <span key={t} className="chip">{TABLE[t] || t}: {fmtDateTime(v.at)}</span>)}</div>
                  </dd>
                </dl>
              </div>
            </div>
          ))}
        </div>
      )}
      {edit && <ServerModal server={edit} clients={clients} onClose={() => setEdit(null)} onSaved={(data) => { setEdit(null); load(); if (data?.key) setShown({ server: data, key: data.key }); else setToast("Saved"); }} />}
      {shown && <KeyModal server={shown.server} keyText={shown.key} onClose={() => setShown(null)} />}
      {detail && <DetailModal server={detail} onClose={() => setDetail(null)} />}
      {toastEl}
    </>
  );
}

function ServerModal({ server, clients, onClose, onSaved }) {
  const [f, setF] = useState(server);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setBusy(true); setError(""); setErrors({});
    const body = { name: f.name, timezone: f.timezone, allowed_ips: String(f.allowed_ips).split(/[\s,;]+/).filter(Boolean), default_client_id: f.default_client_id ? Number(f.default_client_id) : null,
      recording_base_url: f.recording_base_url || null, is_active: f.is_active };
    try { const { data } = server.id ? await api.put(`/dialer/servers/${server.id}`, body) : await api.post("/dialer/servers", body); onSaved(data); }
    catch (e) { setError(errorMessage(e)); setErrors(e.response?.data?.detail?.fields || {}); } finally { setBusy(false); }
  }
  return (
    <Modal title={server.id ? `Edit ${server.name}` : "Add a dialer server"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button></>}>
      <div className="stack">
        <ErrorBox error={Object.keys(errors).length ? "" : error} />
        <Field label="Name *" error={errors.name}><input value={f.name} onChange={set("name")} placeholder="e.g. Vicidial 1 Noida" /></Field>
        <Field label="IP addresses it posts from *" error={errors.allowed_ips} hint="One per line. Only these addresses are accepted for this server's key."><textarea value={f.allowed_ips} onChange={set("allowed_ips")} style={{ minHeight: 70 }} placeholder={"203.0.113.10\n203.0.113.11"} /></Field>
        <div className="form-grid">
          <Field label="Time zone of the server" error={errors.timezone} hint="Agent-log times are in this zone."><input value={f.timezone} onChange={set("timezone")} /></Field>
          <Field label="Only one client uses this server?" error={errors.default_client_id} hint="Calls that match no ID go to this client."><select value={f.default_client_id} onChange={set("default_client_id")}><option value="">No</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        </div>
        <Field label="Where the recordings are served from" error={errors.recording_base_url} hint="The web address of the recording server, for example https://rec.example.com . The CRM plays recordings from here for people who may listen."><input value={f.recording_base_url} onChange={set("recording_base_url")} className="mono" /></Field>
        <label className="check"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Accept data from this server</label>
      </div>
    </Modal>
  );
}

function KeyModal({ server, keyText, onClose }) {
  const url = window.location.origin;
  return (
    <Modal title={`Key for ${server.name}`} onClose={onClose} wide footer={<button className="btn btn-primary" onClick={onClose}>I have saved it</button>}>
      <div className="stack">
        <div className="alert warn"><b>Copy the key now. It is shown only once.</b> If it is lost, make a new one.</div>
        <div className="copy-box"><code>{keyText}</code><CopyButton text={keyText} /></div>
        <div className="section-title" style={{ margin: 0 }}>Install on the Vicidial server</div>
        <ol className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          <li>Copy <span className="mono">dialer/vicidial_push.php</span> and <span className="mono">vicidial_push.config.sample.php</span> to the server (for example <span className="mono">/opt/dialdesk/</span>).</li>
          <li>Copy the sample to <span className="mono">vicidial_push.config.php</span> and fill in: <span className="mono">crm_url</span> = <span className="mono">{url}</span> (the public address of the CRM), <span className="mono">server_key</span> = the key above, and a read-only Vicidial database user.</li>
          <li>Test: <span className="mono">php vicidial_push.php --dry-run</span>, then <span className="mono">php vicidial_push.php</span> (the first run starts 12 months back; <span className="mono">--since=2026-01-01</span> changes that).</li>
          <li>Add to cron: <span className="mono">* * * * * php /opt/dialdesk/vicidial_push.php &gt;&gt; /var/log/dialdesk_push.log 2&gt;&amp;1</span></li>
        </ol>
        <div className="small muted">The server's IP must be in the allowed list, and the CRM must be reachable over HTTPS from it.</div>
      </div>
    </Modal>
  );
}

function DetailModal({ server, onClose }) {
  const [stats, setStats] = useState(null);
  const [pause, setPause] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();
  const load = useCallback(() => {
    api.get(`/dialer/servers/${server.id}/stats`).then((r) => setStats(r.data)).catch((e) => setError(errorMessage(e)));
    api.get("/dialer/pause-codes").then((r) => setPause(r.data)).catch(() => {});
  }, [server.id]);
  useEffect(() => { load(); }, [load]);

  async function run(fn, ok) { setBusy(true); setError(""); try { const { data } = await fn(); setToast(typeof ok === "function" ? ok(data) : ok); load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  const setCode = (code, category) => run(() => api.put("/dialer/pause-codes", { code, category }), "Saved. Rebuild the APR to apply it to past days.");

  const days = {};
  (stats?.last_7_days || []).forEach((d) => { days[d.day] = { ...(days[d.day] || {}), [d.direction]: d.calls }; });
  const unmapped = stats ? stats.unmapped_calls.length + stats.unmapped_agent_rows.length : 0;
  return (
    <Modal title={`${server.name}: data and pause codes`} onClose={onClose} wide footer={<button className="btn" onClick={onClose}>Close</button>}>
      <div className="stack">
        <ErrorBox error={error} />
        {!stats ? <Spinner /> : (
          <>
            <div className="section-title" style={{ margin: 0 }}>Calls received, last 7 days (compare with the dialer)</div>
            {Object.keys(days).length === 0 ? <div className="muted small">Nothing in the last 7 days.</div> : (
              <div className="table-wrap"><table><thead><tr><th>Day</th><th>Inbound</th><th>Outbound</th></tr></thead>
                <tbody>{Object.entries(days).map(([d, v]) => <tr key={d}><td>{d}</td><td>{v.in || 0}</td><td>{v.out || 0}</td></tr>)}</tbody></table></div>
            )}
            <div className="section-title" style={{ margin: 0 }}>Not matched to a client yet</div>
            {unmapped === 0 ? <div className="alert success">Every call and agent row has a client.</div> : (
              <div className="stack" style={{ gap: 8 }}>
                <div className="alert warn">These campaign or ingroup names are not in any client's Dialer IDs. Add them on the client's page (Dialer IDs tab) and the waiting rows are matched at once; <b>Match now</b> re-checks all.</div>
                <div className="row wrap">
                  {stats.unmapped_calls.map((u) => <span key={u.code + u.direction} className="chip">{u.code || "(empty)"} · {u.direction === "in" ? "inbound" : "outbound"} · {u.calls} calls</span>)}
                  {stats.unmapped_agent_rows.map((u) => <span key={"a" + u.code} className="chip">{u.code || "(empty)"} · agent log · {u.rows}</span>)}
                </div>
                <div><button className="btn btn-sm" disabled={busy} onClick={() => run(() => api.post(`/dialer/servers/${server.id}/remap`), (d) => `${d.calls} call(s) and ${d.agent_log} agent row(s) matched`)}>Match now</button></div>
              </div>
            )}
          </>
        )}
        <div className="section-title" style={{ margin: 0 }}>Pause codes (what each break counts as in the APR)</div>
        {!pause ? <Spinner /> : pause.codes.length === 0 ? <div className="muted small">No pause codes seen yet.</div> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Code</th><th>Time (all servers)</th><th>Counts as</th></tr></thead>
            <tbody>{pause.codes.map((c) => (
              <tr key={c.code}><td className="mono"><b>{c.code}</b></td><td>{Math.round(c.seconds / 60)} min</td>
                <td><select style={{ width: 160 }} value={c.category} onChange={(e) => setCode(c.code, e.target.value)}>{pause.categories.map((k) => <option key={k} value={k}>{k}</option>)}</select>{!c.set && <span className="muted small"> (guessed)</span>}</td></tr>
            ))}</tbody></table></div>
        )}
        <div><button className="btn" disabled={busy} onClick={() => run(() => api.post(`/dialer/servers/${server.id}/rebuild-apr`), (d) => `${d.agent_days} agent day(s) recounted`)}>Rebuild the APR from the raw log</button> <span className="small muted">after changing codes</span></div>
      </div>
      {toastEl}
    </Modal>
  );
}
