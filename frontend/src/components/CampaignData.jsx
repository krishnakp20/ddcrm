import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import WebhookPanel from "./WebhookPanel";
import { Badge, Empty, ErrorBox, Field, Modal, Pager, Spinner, fmtDateTime, useDebounced, useToast } from "./ui";

const STATUS = { new: ["Not called", ""], callback: ["Call back", "warn"], done: ["Done", "success"], dnc: ["Do not call", "danger"] };
const FIELD_LABEL = { name: "Name * (or first name)", name2: "Last name (added after the name)", mobile: "Mobile number *", email: "Email", city: "City", ext_ref: "Reference (policy, account, order…)" };

/** Campaign data: upload a file, see the leads, share them between agents. */
export default function CampaignData({ campaign, canManage }) {
  const { can } = useAuth();
  const [sum, setSum] = useState(null);
  const [batches, setBatches] = useState([]);
  const [agents, setAgents] = useState([]);
  const [rows, setRows] = useState({ items: [], total: 0, page_size: 25 });
  const [status, setStatus] = useState("");
  const [assigned, setAssigned] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [page, setPage] = useState(1);
  const [upload, setUpload] = useState(false);
  const [alloc, setAlloc] = useState(false);
  const [download, setDownload] = useState(null);   // {batchId} while the download window is open
  const [error, setError] = useState("");
  const [toast, setToast, toastEl] = useToast();
  const base = `/campaigns/${campaign.id}/data`;

  const loadSide = useCallback(() => {
    api.get(`${base}/summary`).then((r) => setSum(r.data)).catch((e) => setError(errorMessage(e)));
    api.get(`${base}/batches`).then((r) => setBatches(r.data)).catch(() => {});
    api.get(`/campaigns/${campaign.id}/agents`).then((r) => setAgents(r.data.filter((a) => a.allocated))).catch(() => {});
  }, [base, campaign.id]);
  const loadRows = useCallback(() => {
    api.get(`${base}/leads`, { params: { status: status || undefined, assigned: assigned || undefined, q: dq || undefined, page } })
      .then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  }, [base, status, assigned, dq, page]);
  useEffect(() => { loadSide(); }, [loadSide]);
  useEffect(() => { loadRows(); }, [loadRows]);
  useEffect(() => setPage(1), [status, assigned, dq]);
  const reload = () => { loadSide(); loadRows(); };

  async function removeBatch(b) {
    if (!window.confirm(`Remove the upload “${b.name}”? Leads nobody has called yet are deleted; worked leads stay.`)) return;
    try { const { data } = await api.delete(`${base}/batches/${b.id}`); setToast(`${data.removed} lead(s) removed`); reload(); } catch (e) { setError(errorMessage(e)); }
  }

  if (!sum) return error ? <ErrorBox error={error} /> : <Spinner />;
  const tiles = [["Total", sum.total, ""], ["Not called", sum.new, ""], ["Call back", sum.callback, "var(--warn)"], ["Done", sum.done, "var(--success)"], ["Do not call", sum.dnc, "var(--danger)"], ["Shared queue", sum.unassigned, "var(--primary)"]];

  return (
    <div className="stack">
      <ErrorBox error={error} />
      <div className="row spread wrap">
        <div className="kpi-strip" style={{ gridTemplateColumns: `repeat(${tiles.length}, minmax(0,1fr))`, margin: 0, flex: 1, minWidth: 300 }}>
          {tiles.map(([l, v, tone]) => <div key={l} className="kpi"><div className="kpi-label">{l}</div><div className="kpi-value" style={tone ? { color: tone } : undefined}>{v}</div></div>)}
        </div>
        {canManage && (
          <div className="row">
            <button className="btn" disabled={sum.total === 0} onClick={() => setDownload({ batchId: "" })}>Download</button>
            <button className="btn" disabled={sum.new + sum.callback === 0} onClick={() => setAlloc(true)}>Share with agents</button>
            <button className="btn btn-primary" onClick={() => setUpload(true)}>Upload data</button>
          </div>
        )}
      </div>

      {sum.per_agent.length > 0 && (
        <div className="row wrap small muted">Still to call by agent:
          {sum.per_agent.map((a) => <Badge key={a.id} tone="primary">{a.name}: {a.open}</Badge>)}
          {sum.unassigned > 0 && <Badge>Shared queue: {sum.unassigned}</Badge>}
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Leads</h3>
          <div className="row wrap">
            <input style={{ width: 200 }} placeholder="Search name, number, reference" value={q} onChange={(e) => setQ(e.target.value)} />
            <select style={{ width: 140 }} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <select style={{ width: 160 }} value={assigned} onChange={(e) => setAssigned(e.target.value)}>
              <option value="">Everyone</option><option value="shared">Shared queue</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
        </div>
        {rows.items.length === 0 ? <Empty>{sum.total === 0 ? "No data yet. Upload a CSV or Excel file to start." : "No lead matches."}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Mobile</th><th>City</th><th>Reference</th><th>Status</th><th>Tries</th><th>Agent</th><th>Next call</th></tr></thead>
              <tbody>
                {rows.items.map((l) => (
                  <tr key={l.id}>
                    <td><b>{l.name}</b>{Object.keys(l.extra).length > 0 && <div className="small muted">{Object.entries(l.extra).slice(0, 2).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>}</td>
                    <td className="mono">{l.mobile}</td><td>{l.city || "—"}</td><td>{l.ext_ref || "—"}</td>
                    <td><Badge tone={STATUS[l.status][1]}>{STATUS[l.status][0]}</Badge></td>
                    <td>{l.attempts}</td><td>{l.assigned_to || <span className="muted">Shared</span>}</td>
                    <td className="small">{l.next_call_at ? fmtDateTime(l.next_call_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pageSize={rows.page_size} total={rows.total} onPage={setPage} />
      </div>

      {batches.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Uploads</h3></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Allocation</th><th>When</th><th>Rows</th><th>Added</th><th>Duplicates</th><th>Invalid</th><th>Called</th><th /></tr></thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id}>
                    <td><b>{b.name}</b><div className="small muted">{b.name !== b.filename ? `${b.filename} · ` : ""}{b.by}</div></td><td className="small">{fmtDateTime(b.created_at)}</td>
                    <td>{b.total}</td><td>{b.accepted}</td><td>{b.duplicates}</td><td>{b.invalid}</td><td>{b.worked}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{canManage && <><button className="btn btn-sm btn-ghost" onClick={() => setDownload({ batchId: String(b.id) })}>Download</button> <button className="btn btn-sm btn-ghost" style={{ color: "var(--danger)" }} onClick={() => removeBatch(b)}>Remove</button></>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {can("alerts.manage") && <WebhookPanel campaign={campaign} />}

      {upload && <UploadModal base={base} agents={agents} onClose={() => setUpload(false)} onDone={() => { reload(); }} />}
      {download && <DownloadModal base={base} batches={batches} start={download.batchId} onClose={() => setDownload(null)} />}
      {alloc && <AllocateModal base={base} agents={agents} sum={sum} onClose={() => setAlloc(false)} onDone={(n) => { setAlloc(false); setToast(`${n} lead(s) shared`); reload(); }} />}
      {toastEl}
    </div>
  );
}

function AgentPicker({ agents, picked, setPicked }) {
  if (agents.length === 0) return <div className="alert info">No agent is allocated to this campaign yet, so everything goes to the shared queue. Allocate agents on the Agents tab to share data between them.</div>;
  const toggle = (id) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  return (
    <div className="stack" style={{ gap: 6 }}>
      {agents.map((a) => (
        <label key={a.id} className="check"><input type="checkbox" checked={picked.includes(a.id)} onChange={() => toggle(a.id)} /> {a.name}{a.shared && <span className="muted small"> · DialDesk agent</span>}</label>
      ))}
      <div className="small muted">{picked.length === 0 ? "Nobody picked: every agent can take any lead from the shared queue." : `Leads are split evenly between the ${picked.length} agent(s) picked; only they will see them.`}</div>
    </div>
  );
}

function UploadModal({ base, agents, onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [pre, setPre] = useState(null);
  const [map, setMap] = useState({});
  const [extra, setExtra] = useState([]);
  const [picked, setPicked] = useState([]);
  const [allocName, setAllocName] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function choose(f) {
    setFile(f); setPre(null); setError("");
    if (!f) return;
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", f);
      const { data } = await api.post(`${base}/preview`, fd);
      setPre(data); setMap(data.mapping); setAllocName(f.name.replace(/\.[^.]+$/, ""));
      const used = new Set(Object.values(data.mapping).filter(Boolean));
      setExtra(data.columns.filter((c) => !used.has(c)));
    } catch (e) { setError(errorMessage(e)); setFile(null); } finally { setBusy(false); }
  }

  async function run() {
    setBusy(true); setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("mapping", JSON.stringify({ ...map, extra: extra.filter((c) => !Object.values(map).includes(c)) }));
      fd.append("agent_ids", JSON.stringify(picked));
      fd.append("name", allocName);
      const { data } = await api.post(`${base}/import`, fd);
      setResult(data); onDone();
    } catch (e) {
      const d = e.response?.data?.detail;
      setError(errorMessage(e));
      if (d?.errors) setResult({ failed: true, ...d });
    } finally { setBusy(false); }
  }

  const colSelect = (field, required) => (
    <Field key={field} label={FIELD_LABEL[field]}>
      <select value={map[field] || ""} onChange={(e) => setMap({ ...map, [field]: e.target.value || null })}>
        <option value="">{required ? "Choose a column" : "— not in the file —"}</option>
        {pre.columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </Field>
  );

  if (result && !result.failed) {
    return (
      <Modal title="Upload finished" onClose={onClose} footer={<button className="btn btn-primary" onClick={onClose}>Done</button>}>
        <div className="stack">
          <div className="alert success"><b>{result.accepted} lead(s) added</b> as “{result.name}” {result.shared ? "to the shared queue." : "and shared between the agents you picked."}</div>
          <div className="small muted">{result.total} rows read · {result.duplicates} already in this campaign (skipped) · {result.invalid} not valid (skipped)</div>
          {result.errors.length > 0 && <ErrorList errors={result.errors} />}
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Upload campaign data" onClose={onClose} wide
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!pre || busy || !map.name || !map.mobile} onClick={run}>{busy ? "Working…" : pre ? `Add ${pre.rows} rows` : "Add data"}</button></>}>
      <div className="stack">
        <ErrorBox error={error} />
        {result?.failed && result.errors.length > 0 && <ErrorList errors={result.errors} />}
        <Field label="CSV or Excel file" hint="First row = column names. Name and mobile number are required for every row. Max 50,000 rows.">
          <input type="file" accept=".csv,.xlsx,.xlsm,.txt" onChange={(e) => choose(e.target.files[0])} />
        </Field>
        {pre && (
          <>
            <div className="section-title" style={{ margin: 0 }}>Match the columns of “{pre.filename}” ({pre.rows} rows)</div>
            <div className="form-grid">{["name", "name2", "mobile", "email", "city", "ext_ref"].map((f) => colSelect(f, f === "name" || f === "mobile"))}</div>
            <Field label="Other columns to show the agent" hint="These appear on the call screen, for example premium due or plan.">
              <div className="chip-row">
                {pre.columns.filter((c) => !Object.values(map).includes(c)).map((c) => (
                  <label key={c} className="check"><input type="checkbox" checked={extra.includes(c)} onChange={() => setExtra(extra.includes(c) ? extra.filter((x) => x !== c) : [...extra, c])} /> {c}</label>
                ))}
                {pre.columns.every((c) => Object.values(map).includes(c)) && <span className="muted small">All columns are matched.</span>}
              </div>
            </Field>
            <div className="table-wrap card" style={{ boxShadow: "none" }}>
              <table>
                <thead><tr>{pre.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{pre.sample.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="small">{v}</td>)}</tr>)}</tbody>
              </table>
            </div>
            <Field label="Name of this allocation" hint="Agents see this name when they choose what to call, for example “Oct week 4 – Rahul”.">
              <input value={allocName} maxLength={120} onChange={(e) => setAllocName(e.target.value)} />
            </Field>
            <div className="section-title" style={{ margin: 0 }}>Who gets this data?</div>
            <AgentPicker agents={agents} picked={picked} setPicked={setPicked} />
          </>
        )}
      </div>
    </Modal>
  );
}

function ErrorList({ errors }) {
  return (
    <div className="alert warn" style={{ maxHeight: 160, overflowY: "auto" }}>
      <b>Rows that were skipped</b>
      {errors.map((e) => <div key={e.row} className="small">Row {e.row}: {e.reason}</div>)}
    </div>
  );
}

function AllocateModal({ base, agents, sum, onClose, onDone }) {
  const [picked, setPicked] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true); setError("");
    try { const { data } = await api.post(`${base}/allocate`, { agent_ids: picked }); onDone(data.allocated); }
    catch (e) { setError(errorMessage(e)); setBusy(false); }
  }
  return (
    <Modal title="Share the data with agents" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={go}>{busy ? "Working…" : picked.length ? "Share evenly" : "Move to shared queue"}</button></>}>
      <div className="stack">
        <ErrorBox error={error} />
        <p className="muted" style={{ margin: 0 }}>{sum.new + sum.callback} lead(s) still to be called are shared again. Done and do-not-call leads are not touched.</p>
        <AgentPicker agents={agents} picked={picked} setPicked={setPicked} />
      </div>
    </Modal>
  );
}

async function blobError(e) {
  const d = e.response?.data;
  if (d instanceof Blob) {
    try { const j = JSON.parse(await d.text()); return typeof j.detail === "string" ? j.detail : j.detail?.message || "Could not download"; } catch { return "Could not download"; }
  }
  return errorMessage(e);
}

function DownloadModal({ base, batches, start, onClose }) {
  const [batchId, setBatchId] = useState(start || "");
  const [scope, setScope] = useState("open");
  const [format, setFormat] = useState("plain");
  const [listId, setListId] = useState("");
  const [phoneCode, setPhoneCode] = useState("91");
  const [header, setHeader] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const vici = format === "vicidial";

  async function run() {
    setBusy(true); setError("");
    try {
      const r = await api.get(`${base}/export`, { params: { batch_id: batchId === "" ? undefined : batchId, scope, format, list_id: vici ? listId : undefined, phone_code: vici ? phoneCode : undefined, header }, responseType: "blob" });
      const name = /filename="([^"]+)"/.exec(r.headers["content-disposition"] || "")?.[1] || "campaign_data.csv";
      const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = name; document.body.appendChild(a); a.click(); a.remove();
      onClose();
    } catch (e) { setError(await blobError(e)); } finally { setBusy(false); }
  }

  return (
    <Modal title="Download campaign data" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy || (vici && !listId.trim())} onClick={run}>{busy ? "Preparing…" : "Download"}</button></>}>
      <div className="stack">
        <ErrorBox error={error} />
        <p className="muted" style={{ margin: 0 }}>For a dialer that is not connected to the CRM. Load the file there (Vicidial: Admin &gt; Lists &gt; Load Leads). The numbers stay in the CRM, so the agent screen still opens when that dialer connects a call.</p>
        <Field label="Which data">
          <select value={batchId} onChange={(e) => setBatchId(e.target.value)}>
            <option value="">Everything in the campaign</option>
            {batches.map((b) => <option key={b.id} value={b.id}>{b.name} ({b.accepted})</option>)}
            <option value="0">Data sent by the client's API</option>
          </select>
        </Field>
        <Field label="Which numbers">
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="open">Only numbers still to be called (not called, call back)</option>
            <option value="all">All numbers (except Do not call)</option>
          </select>
        </Field>
        <Field label="File layout">
          <select value={format} onChange={(e) => { setFormat(e.target.value); setHeader(e.target.value === "plain"); }}>
            <option value="plain">CRM columns (name, mobile, city, status, agent, allocation…)</option>
            <option value="vicidial">Vicidial “Load Leads” (standard layout)</option>
          </select>
        </Field>
        {vici && (
          <div className="form-grid">
            <Field label="Vicidial list ID" hint="The list the file will be loaded into."><input value={listId} onChange={(e) => setListId(e.target.value)} placeholder="1001" /></Field>
            <Field label="Country code"><input value={phoneCode} onChange={(e) => setPhoneCode(e.target.value)} /></Field>
          </div>
        )}
        <label className="check"><input type="checkbox" checked={header} onChange={(e) => setHeader(e.target.checked)} /> Include the column names as the first row{vici ? " (leave off for Vicidial's standard layout)" : ""}</label>
        <div className="small muted">Numbers marked Do not call are never included in a Vicidial file. Each download is written to the audit log.</div>
      </div>
    </Modal>
  );
}
