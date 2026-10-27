import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { Badge, CopyButton, Empty, ErrorBox, Field, Spinner, useToast } from "./ui";

/** An id copied from the dialer. Typing is switched off on purpose so nobody mistypes it: copy it in the dialer, then paste it here (Ctrl+V, right-click Paste, or the Paste button). */
export function PasteInput({ value, onChange, placeholder }) {
  const [note, setNote] = useState("");
  const take = (raw) => {
    const t = String(raw || "").trim();
    if (!t) { setNote("Nothing to paste. Copy the value in the dialer first."); return; }
    if (/\s/.test(t)) { setNote("That has spaces or several lines. Copy only the id itself."); return; }
    if (t.length > 60) { setNote("That is too long to be an id. Copy only the id itself."); return; }
    setNote(""); onChange(t);
  };
  const block = (e) => e.preventDefault();
  async function pasteButton() {
    try { take(await navigator.clipboard.readText()); }
    catch { setNote("The browser did not allow that. Click in the box and press Ctrl+V instead."); }
  }
  return (
    <div>
      <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
        <input className="mono" value={value} placeholder={placeholder || "Paste here"} autoComplete="off" spellCheck={false}
          onChange={() => {}} onBeforeInput={block} onDrop={block}
          onPaste={(e) => { e.preventDefault(); take(e.clipboardData.getData("text")); }}
          onKeyDown={(e) => {
            const k = e.key;
            if (e.ctrlKey || e.metaKey) return;                       // paste, copy, select all
            if (["Tab", "Shift", "Escape", "Enter", "ArrowLeft", "ArrowRight", "Home", "End"].includes(k)) return;
            if (["Backspace", "Delete"].includes(k)) { e.preventDefault(); setNote(""); onChange(""); return; }
            e.preventDefault();
            setNote("Typing is off to avoid mistakes. Copy the value in the dialer and paste it here.");
          }} />
        <button type="button" className="btn btn-sm" onClick={pasteButton}>Paste</button>
        {value && <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setNote(""); onChange(""); }}>Clear</button>}
      </div>
      {note && <div className="small" style={{ color: "var(--danger)", marginTop: 4 }}>{note}</div>}
    </div>
  );
}

/* ---------- the dialer's ids for one client (vendor, ingroup, campaign) ---------- */

export function DialerIdsPanel({ client, canManage }) {
  const [rows, setRows] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [servers, setServers] = useState([]);   // dialer servers (only DialDesk staff with the right can list them)
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api.get("/dialer/servers").then((r) => setServers(r.data)).catch(() => setServers([]));
    api.get(`/clients/${client.id}/dialer-ids`).then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
    api.get("/campaigns", { params: { client_id: client.id } }).then((r) => setCampaigns(r.data.items)).catch(() => {});
  }, [client.id]);
  useEffect(load, [load]);
  if (!rows) return error ? <ErrorBox error={error} /> : <Spinner />;

  const of = (k) => rows.filter((r) => r.kind === k);
  const vendor = of("vendor")[0]?.value || "<vendor_id>";
  const group = of("ingroup")[0]?.value || "<ingroup_id>";
  const camp = of("campaign")[0]?.value || "<campaign_id>";
  const origin = window.location.origin;
  const inbound = `${origin}/agent/call?phonenumber={phone}&vendor_id=${vendor}&ingroup_id=${group}&call_id={call_id}`;
  const pd = `${origin}/agent/call?phonenumber={phone}&vendor_id=${vendor}&campaign_id=${camp}&call_id={call_id}`;

  return (
    <div className="stack">
      <ErrorBox error={error} />
      <div className="alert info">
        The dialer opens a link in the agent's browser. These ids tell the CRM which client and form it is for. <b>Copy each id from the dialer and paste it here</b>; typing is switched off so it cannot be mistyped. A <b>dialer vendor ID</b> belongs to one client only; dialer ingroup and campaign IDs belong to this client.
      </div>
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <IdBox title="Dialer vendor IDs" help="The id that identifies this client in the dialer (vendor_id). Several are allowed." kind="vendor" rows={of("vendor")} client={client} canManage={canManage} reload={load} />
        <IdBox title="Dialer ingroup IDs (inbound)" help="The dialer's inbound group / queue names of this client (ingroup_id). Several are allowed." kind="ingroup" rows={of("ingroup")} client={client} servers={servers} canManage={canManage} reload={load} />
      </div>
      <IdBox title="Dialer campaign IDs (outbound / predictive)" help="The dialer's own campaign id (campaign_id), linked to the CRM campaign it belongs to. A CRM campaign can have several." kind="campaign" rows={of("campaign")}
        client={client} campaigns={campaigns} servers={servers} canManage={canManage} reload={load} />
      <div className="card card-pad stack">
        <div className="section-title">Links to give the dialer team</div>
        <div><div className="small muted" style={{ marginBottom: 4 }}>Inbound</div><div className="copy-box"><code>{inbound}</code><CopyButton text={inbound} /></div></div>
        <div><div className="small muted" style={{ marginBottom: 4 }}>Predictive (PD)</div><div className="copy-box"><code>{pd}</code><CopyButton text={pd} /></div></div>
        <div className="small muted">Replace {"{phone}"} and {"{call_id}"} with the dialer's own variables. <code>call_id</code> is optional but recommended: it stops the same call from opening twice. You can also add <code>agent_id={"{agent}"}</code> so the CRM warns when the wrong agent is signed in.</div>
      </div>
    </div>
  );
}

function IdBox({ title, help, kind, rows, client, campaigns = [], servers = [], canManage, reload }) {
  const [value, setValue] = useState("");
  const [serverId, setServerId] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [label, setLabel] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");

  async function add(e) {
    e.preventDefault();
    setErrors({}); setError("");
    try {
      await api.post(`/clients/${client.id}/dialer-ids`, { kind, value, label: label || null, campaign_id: kind === "campaign" ? Number(campaignId) || null : null,
        dialer_server_id: kind !== "vendor" && serverId ? Number(serverId) : null });
      setValue(""); setLabel(""); reload();
    } catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); }
  }
  async function remove(r) {
    if (!window.confirm(`Remove ${r.value}? Links using it will stop working.`)) return;
    try { await api.delete(`/dialer-ids/${r.id}`); reload(); } catch (e) { setError(errorMessage(e)); }
  }
  async function toggle(r) {
    try { await api.put(`/dialer-ids/${r.id}`, { kind: r.kind, value: r.value, label: r.label, campaign_id: r.campaign_id, is_active: !r.is_active, dialer_server_id: r.dialer_server_id }); reload(); }
    catch (e) { setError(errorMessage(e)); }
  }

  return (
    <div className="card">
      <div className="card-head"><div><h3>{title}</h3><div className="small muted">{help}</div></div></div>
      <ErrorBox error={error && !Object.keys(errors).length ? error : ""} />
      {rows.length === 0 ? <Empty>None yet.</Empty> : rows.map((r) => (
        <div key={r.id} className="queue-item" style={r.is_active ? undefined : { opacity: 0.55 }}>
          <div className="grow"><b className="mono">{r.value}</b>{r.campaign_name && <span className="muted"> → CRM campaign: {r.campaign_name}</span>}{r.dialer_server_id && <span className="badge" style={{ marginLeft: 8 }}>{servers.find((x) => x.id === r.dialer_server_id)?.name || `server ${r.dialer_server_id}`}</span>}{r.label && <div className="small muted">{r.label}</div>}</div>
          {!r.is_active && <Badge>Off</Badge>}
          {canManage && <><button className="btn btn-sm btn-ghost" onClick={() => toggle(r)}>{r.is_active ? "Switch off" : "Switch on"}</button>
            <button className="btn btn-sm btn-ghost" onClick={() => remove(r)}>Remove</button></>}
        </div>
      ))}
      {canManage && (
        <form className="card-body" style={{ borderTop: "1px solid var(--border)" }} onSubmit={add}>
          <div className="row wrap" style={{ alignItems: "flex-start" }}>
            {kind === "campaign" && (
              <Field label="CRM campaign" hint="The campaign in this CRM that the dialer id belongs to" error={errors.campaign_id}>
                <select value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
                  <option value="">Select the CRM campaign…</option>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
            )}
            {kind !== "vendor" && servers.length > 0 && (
              <Field label="Dialer server" hint="Which dialer this id is on. Leave on Any server if the id is unique.">
                <select value={serverId} onChange={(e) => setServerId(e.target.value)}><option value="">Any server</option>{servers.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
              </Field>
            )}
            <Field label={`${{ vendor: "Dialer vendor ID", ingroup: "Dialer ingroup ID", campaign: "Dialer campaign ID" }[kind]} (paste from the dialer)`} error={errors.value}><PasteInput value={value} onChange={setValue} placeholder="Copy in the dialer, paste here" /></Field>
            <Field label="Note (optional)"><input value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
            <button className="btn btn-primary" style={{ marginTop: 22 }} disabled={!value.trim()}>Add</button>
          </div>
        </form>
      )}
    </div>
  );
}

/* ---------- a campaign's own dialer ids ---------- */

export function CampaignDialerIds({ campaign, canManage }) {
  const [rows, setRows] = useState(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [errors, setErrors] = useState({});
  const load = useCallback(() => api.get(`/campaigns/${campaign.id}/dialer-ids`).then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e))), [campaign.id]);
  useEffect(() => { load(); }, [load]);

  async function add(e) {
    e.preventDefault();
    setError(""); setErrors({});
    try { await api.post(`/clients/${campaign.client_id}/dialer-ids`, { kind: "campaign", value, campaign_id: campaign.id }); setValue(""); load(); }
    catch (err) { setErrors(fieldErrors(err)); setError(errorMessage(err)); }
  }
  async function remove(r) {
    if (!window.confirm(`Remove ${r.value}?`)) return;
    try { await api.delete(`/dialer-ids/${r.id}`); load(); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <div className="card card-pad">
      <div className="section-title">Dialer campaign IDs for this CRM campaign</div>
      <p className="muted" style={{ marginTop: 0 }}>The dialer's own campaign id (the <code>campaign_id</code> it sends) for this CRM campaign. Calls with an id listed here open this CRM campaign's tagging form. Copy the id in the dialer and paste it here.</p>
      <ErrorBox error={error && !errors.value ? error : ""} />
      {!rows ? <Spinner label="" /> : rows.length === 0 ? <div className="muted small" style={{ marginBottom: 10 }}>No dialer id yet, so the dialer cannot open calls for this campaign.</div> : (
        <div className="row wrap" style={{ marginBottom: 10 }}>
          {rows.map((r) => <span key={r.id} className="badge primary mono">{r.value}{canManage && <button className="btn btn-sm btn-ghost" style={{ padding: "0 4px" }} onClick={() => remove(r)}>✕</button>}</span>)}
        </div>
      )}
      {canManage ? (
        <form className="row" style={{ alignItems: "flex-start" }} onSubmit={add}>
          <Field label="Add a dialer campaign ID (paste from the dialer)" error={errors.value}><PasteInput value={value} onChange={setValue} placeholder="Copy in the dialer, paste here" /></Field>
          <button className="btn btn-primary" style={{ marginTop: 22 }} disabled={!value.trim()}>Add</button>
        </form>
      ) : <div className="small muted">Only DialDesk staff change these ids.</div>}
    </div>
  );
}

/* ---------- agents allocated to a campaign ---------- */

export function CampaignAgents({ campaign, canManage }) {
  const [rows, setRows] = useState(null);
  const [picked, setPicked] = useState(new Set());
  const [error, setError] = useState("");
  const [toast, setToast, toastEl] = useToast();
  useEffect(() => {
    api.get(`/campaigns/${campaign.id}/agents`).then((r) => { setRows(r.data); setPicked(new Set(r.data.filter((a) => a.allocated).map((a) => a.id))); }).catch((e) => setError(errorMessage(e)));
  }, [campaign.id]);

  async function save() {
    setError("");
    try { await api.put(`/campaigns/${campaign.id}/agents`, { ids: [...picked] }); setToast("Agents saved"); } catch (e) { setError(errorMessage(e)); }
  }
  const toggle = (id) => { const n = new Set(picked); n.has(id) ? n.delete(id) : n.add(id); setPicked(n); };

  if (!rows) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <div className="card">
      <div className="card-head">
        <div><h3>Agents on this campaign</h3><div className="small muted">Only these agents can open this campaign's calls. Shared DialDesk agents must first be allocated to the client (on the agent's user page).</div></div>
        {canManage && <button className="btn btn-primary" onClick={save}>Save agents</button>}
      </div>
      <ErrorBox error={error} />
      {rows.length === 0 ? <Empty>No agent can work for this client yet. Add agents under Users, and allocate shared agents to the client.</Empty> : rows.map((a) => (
        <label key={a.id} className="queue-item" style={{ cursor: canManage ? "pointer" : "default" }}>
          <span className="row grow"><input type="checkbox" checked={picked.has(a.id)} disabled={!canManage} onChange={() => toggle(a.id)} />
            <span><b>{a.name}</b><div className="small muted">{a.email}{a.dialer_agent_id ? ` · dialer ${a.dialer_agent_id}` : ""}</div></span></span>
          {a.shared ? <Badge tone="primary">DialDesk agent</Badge> : <Badge>Client's own</Badge>}
        </label>
      ))}
      {toastEl}
    </div>
  );
}

/* ---------- clients a shared DialDesk agent may work for (on the user page) ---------- */

export function AgentClientsCard({ userId }) {
  const [data, setData] = useState(null);
  const [picked, setPicked] = useState(new Set());
  const [error, setError] = useState("");
  const [toast, setToast, toastEl] = useToast();
  useEffect(() => {
    api.get(`/users/${userId}/clients`).then((r) => { setData(r.data); setPicked(new Set(r.data.clients.filter((c) => c.allocated).map((c) => c.id))); }).catch((e) => setError(errorMessage(e)));
  }, [userId]);
  if (!data) return error ? <ErrorBox error={error} /> : <Spinner label="" />;
  if (!data.shared) return null;

  async function save() {
    setError("");
    try { await api.put(`/users/${userId}/clients`, { ids: [...picked] }); setToast("Allocation saved"); } catch (e) { setError(errorMessage(e)); }
  }
  const toggle = (id) => { const n = new Set(picked); n.has(id) ? n.delete(id) : n.add(id); setPicked(n); };

  return (
    <div className="card card-pad">
      <div className="row spread wrap" style={{ marginBottom: 8 }}>
        <div className="section-title" style={{ margin: 0 }}>Works for these clients</div>
        <button className="btn btn-sm btn-primary" onClick={save}>Save allocation</button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>A shared DialDesk agent can take calls only for the clients ticked here. For outbound campaigns, add the agent on the campaign as well.</p>
      <ErrorBox error={error} />
      <div className="grid cols-2" style={{ gap: 6 }}>
        {data.clients.length === 0 ? <span className="muted">No active client yet.</span> : data.clients.map((c) => (
          <span key={c.id} className="check"><input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)} /> {c.name}</span>
        ))}
      </div>
      {toastEl}
    </div>
  );
}

export { Link };
