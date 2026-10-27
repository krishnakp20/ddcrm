import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { PRIORITIES } from "../components/TicketBits";
import { Badge, Empty, ErrorBox, Field, Icon, Modal, PageHead, Spinner, fmtDateTime, useToast } from "../components/ui";
import { useScope } from "../scope";

const OUTCOMES = [["connected", "Connected"], ["converted", "Converted"], ["callback", "Call back"], ["closed", "Closed"], ["not_connected", "Not connected"], ["dnc", "Do not call"]];
const EMPTY = { name: "", event: "ticket_assigned", conditions: {}, recipients: { assignee: true, agent: false, customer: false, users: [], emails: [], mobiles: [] }, channels: ["email"], message: "", is_active: true };

export default function Alerts() {
  const { user } = useAuth();
  const staff = user.user_type === "staff";
  const { clientId: scoped, clients } = useScope();
  const [cid, setCid] = useState("");
  const [rules, setRules] = useState(null);
  const [log, setLog] = useState([]);
  const [meta, setMeta] = useState(null);
  const [editing, setEditing] = useState(null);   // a rule, or EMPTY for a new one
  const [error, setError] = useState("");
  const [toast, setToast, toastEl] = useToast();

  useEffect(() => { if (staff) setCid(scoped || String(clients[0]?.id || "")); }, [staff, scoped, clients]);
  const params = { client_id: cid || undefined };
  const load = useCallback(() => {
    if (staff && !cid) return;
    api.get("/alerts/rules", { params }).then((r) => setRules(r.data)).catch((e) => setError(errorMessage(e)));
    api.get("/alerts/log", { params }).then((r) => setLog(r.data)).catch(() => {});
    api.get("/alerts/meta", { params }).then((r) => setMeta(r.data)).catch(() => {});
  }, [cid, staff]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  async function standard() {
    try { const { data } = await api.post("/alerts/standard", null, { params }); setToast(data.added ? `${data.added} alert(s) added` : "The standard alerts are already there"); load(); } catch (e) { setError(errorMessage(e)); }
  }
  async function toggle(r) { await api.put(`/alerts/rules/${r.id}`, { ...r, is_active: !r.is_active }).catch((e) => setError(errorMessage(e))); load(); }
  async function test(r) {
    try { const { data } = await api.post(`/alerts/rules/${r.id}/test`); setToast(data.people ? `Test sent to you: ${data.sent} message(s)` : "The rule names nobody to send to"); load(); } catch (e) { setError(errorMessage(e)); }
  }
  async function remove(r) { if (window.confirm(`Delete the alert “${r.name}”?`)) { await api.delete(`/alerts/rules/${r.id}`).catch((e) => setError(errorMessage(e))); load(); } }

  if (!rules || !meta) return error ? <ErrorBox error={error} /> : <Spinner />;
  const who = (r) => [r.recipients.assignee && "Assignee", r.recipients.agent && "The agent", r.recipients.users.length && `${r.recipients.users.length} user(s)`, r.recipients.emails.length && `${r.recipients.emails.length} email(s)`, r.recipients.mobiles.length && `${r.recipients.mobiles.length} mobile(s)`].filter(Boolean).join(", ");
  const when = (r) => [r.conditions.hours && `open for ${r.conditions.hours}h`, r.conditions.campaign?.length && `${r.conditions.campaign.length} campaign(s)`, r.conditions.priority?.length && `priority ${r.conditions.priority.join("/")}`, r.conditions.outcome?.length && `outcome ${r.conditions.outcome.join("/").replace("_", " ")}`, r.conditions.scenario_path?.length && `scenario ${r.conditions.scenario_path.join(" › ")}`, r.conditions.scenario_contains && `scenario has “${r.conditions.scenario_contains}”`, r.conditions.field_key && `${meta.fields.find((f) => f.key === r.conditions.field_key)?.label || r.conditions.field_key} = ${r.conditions.field_value || "any"}`].filter(Boolean).join(" · ") || "every time";
  const notLive = meta.channels.filter((c) => !c.live).map((c) => c.label);

  return (
    <>
      <PageHead title="Alerts" sub="Message the right people by email, SMS or WhatsApp when a ticket is raised, assigned or late, or when a call is tagged a certain way.">
        <button className="btn" onClick={standard}>Add standard alerts</button>
        <button className="btn btn-primary" onClick={() => setEditing(EMPTY)}><span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> New alert</button>
      </PageHead>
      <ErrorBox error={error} />
      {staff && !scoped && clients.length > 1 && (
        <div className="card card-pad" style={{ marginBottom: 12 }}>
          <Field label="Client"><select value={cid} onChange={(e) => setCid(e.target.value)} style={{ maxWidth: 320 }}>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        </div>
      )}
      {notLive.length > 0 && <div className="alert info" style={{ marginBottom: 12 }}>{notLive.join(", ")} {notLive.length === 1 ? "is" : "are"} not connected to a provider yet, so those messages are only recorded (Settings &gt; Notification log), not delivered.</div>}

      <div className="card">
        {rules.length === 0 ? <Empty>No alerts yet. “Add standard alerts” creates the usual ones for ticket assignment and SLA.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Alert</th><th>When</th><th>Who is told</th><th>Channels</th><th>On</th><th /></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.name}</b><div className="small muted">{r.event_label}</div></td>
                    <td className="small">{when(r)}</td><td className="small">{who(r)}</td>
                    <td><div className="chip-row">{r.channels.map((c) => <span key={c} className="chip">{c}</span>)}</div></td>
                    <td><input type="checkbox" checked={r.is_active} onChange={() => toggle(r)} aria-label="Active" /></td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button className="btn btn-sm" onClick={() => test(r)}>Test</button>{" "}
                      <button className="btn btn-sm" onClick={() => setEditing(r)}>Edit</button>{" "}
                      <button className="btn btn-sm btn-ghost" style={{ color: "var(--danger)" }} onClick={() => remove(r)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-head"><h3>Recent alerts</h3></div>
        {log.length === 0 ? <Empty>Nothing has fired yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Alert</th><th>About</th><th>Messages</th></tr></thead>
              <tbody>{log.map((l) => <tr key={l.id}><td className="small">{fmtDateTime(l.created_at)}</td><td>{l.rule}<div className="small muted">{l.event}</div></td><td className="mono small">{l.ref}</td><td>{l.sent}{l.failed > 0 && <Badge tone="danger">{l.failed} failed</Badge>}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </div>

      {editing && <RuleModal rule={editing} meta={meta} clientId={cid} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setToast("Alert saved"); load(); }} />}
      {toastEl}
    </>
  );
}

const toggleIn = (arr = [], v) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
const lines = (s) => s.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean);

function RuleModal({ rule, meta, clientId, onClose, onSaved }) {
  const [f, setF] = useState({ ...rule, message: rule.message || "", recipients: { ...EMPTY.recipients, ...rule.recipients } });
  const [emails, setEmails] = useState((rule.recipients?.emails || []).join("\n"));
  const [mobiles, setMobiles] = useState((rule.recipients?.mobiles || []).join("\n"));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ev = meta.events.find((e) => e.key === f.event);
  const call = f.event === "call_tagged";
  const cond = f.conditions || {};
  const setCond = (patch) => setF({ ...f, conditions: { ...cond, ...patch } });
  const setRec = (patch) => setF({ ...f, recipients: { ...f.recipients, ...patch } });

  async function save() {
    setBusy(true); setError(""); setErrors({});
    const body = { ...f, client_id: clientId ? Number(clientId) : undefined, message: f.message || null, recipients: { ...f.recipients, emails: lines(emails), mobiles: lines(mobiles) } };
    try { rule.id ? await api.put(`/alerts/rules/${rule.id}`, body) : await api.post("/alerts/rules", body); onSaved(); }
    catch (e) { setError(errorMessage(e)); setErrors(e.response?.data?.detail?.fields || {}); } finally { setBusy(false); }
  }

  return (
    <Modal title={rule.id ? "Edit alert" : "New alert"} onClose={onClose} wide
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save alert"}</button></>}>
      <div className="stack">
        <ErrorBox error={Object.keys(errors).length ? "" : error} />
        <div className="form-grid">
          <Field label="Name *" error={errors.name}><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Urgent tickets to the manager" /></Field>
          <Field label="When *" error={errors.event}>
            <select value={f.event} onChange={(e) => setF({ ...f, event: e.target.value, conditions: {}, recipients: { ...f.recipients, assignee: false, agent: false } })}>
              {meta.events.map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
            </select>
          </Field>
        </div>

        {f.event === "ticket_stale" && (
          <Field label="Ticket still not resolved after (hours) *" error={errors.hours} hint="Counted from when the ticket was raised, like an escalation level.">
            <input inputMode="numeric" value={cond.hours || ""} onChange={(e) => setCond({ hours: e.target.value })} style={{ maxWidth: 160 }} />
          </Field>
        )}
        <div className="section-title" style={{ margin: 0 }}>Only when (optional)</div>
        {!call && (
          <Field label="Priority is"><div className="row wrap">{PRIORITIES.map(([k, l]) => <label key={k} className="check"><input type="checkbox" checked={(cond.priority || []).includes(k)} onChange={() => setCond({ priority: toggleIn(cond.priority, k) })} /> {l}</label>)}</div></Field>
        )}
        {call && (
          <Field label="Outcome is"><div className="row wrap">{OUTCOMES.map(([k, l]) => <label key={k} className="check"><input type="checkbox" checked={(cond.outcome || []).includes(k)} onChange={() => setCond({ outcome: toggleIn(cond.outcome, k) })} /> {l}</label>)}</div></Field>
        )}
        <div className="form-grid">
          <ScenarioPicker forms={meta.scenario_forms || []} cond={cond} setCond={setCond} />
          <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <Field label="Tagging field">
              <select value={cond.field_key || ""} onChange={(e) => setCond({ field_key: e.target.value })}><option value="">Any</option>{meta.fields.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</select>
            </Field>
            <Field label="equals"><input value={cond.field_value || ""} disabled={!cond.field_key} onChange={(e) => setCond({ field_value: e.target.value })} /></Field>
          </div>
        </div>

        <div className="section-title" style={{ margin: 0 }}>Who is told *</div>
        {errors.recipients && <div className="alert error">{errors.recipients}</div>}
        <div className="row wrap">
          {ev?.ticket && <label className="check"><input type="checkbox" checked={!!f.recipients.assignee} onChange={(e) => setRec({ assignee: e.target.checked })} /> The person the ticket is assigned to</label>}
          {call && <label className="check"><input type="checkbox" checked={!!f.recipients.agent} onChange={(e) => setRec({ agent: e.target.checked })} /> The agent who handled the call</label>}
          <label className="check"><input type="checkbox" checked={!!f.recipients.customer} onChange={(e) => setRec({ customer: e.target.checked })} /> The customer (SMS / WhatsApp to their mobile number)</label>
        </div>
        {meta.users.length > 0 && (
          <Field label="Users"><div className="row wrap">{meta.users.map((u) => <label key={u.id} className="check"><input type="checkbox" checked={f.recipients.users.includes(u.id)} onChange={() => setRec({ users: toggleIn(f.recipients.users, u.id) })} /> {u.name}</label>)}</div></Field>
        )}
        <div className="form-grid">
          <Field label="Other email addresses" error={errors.emails} hint="One per line. Up to 5."><textarea value={emails} onChange={(e) => setEmails(e.target.value)} style={{ minHeight: 56 }} /></Field>
          <Field label="Other mobile numbers" error={errors.mobiles} hint="One per line. Up to 5."><textarea value={mobiles} onChange={(e) => setMobiles(e.target.value)} style={{ minHeight: 56 }} /></Field>
        </div>

        <Field label="Send on *" error={errors.channels}>
          <div className="row wrap">{meta.channels.map((c) => <label key={c.key} className="check"><input type="checkbox" checked={f.channels.includes(c.key)} onChange={() => setF({ ...f, channels: toggleIn(f.channels, c.key) })} /> {c.label}{!c.live && <span className="muted small"> (not connected)</span>}</label>)}</div>
        </Field>
        <Field label="Message (optional)" hint={`Leave empty for the standard text. You can use: ${meta.variables.map((v) => `{${v}}`).join(" ")} and the name of any form field in lower case with underscores, for example {model_no}`}>
          <textarea value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} placeholder={ev?.text} />
        </Field>
      </div>
    </Modal>
  );
}

const LEVEL = ["Scenario", "Sub scenario", "Sub scenario 2", "Sub scenario 3", "Sub scenario 4"];

/** Choose the scenario the alert is for from the client's own tagging tree: scenario, then sub scenario, then sub scenario 2 and so on. */
function ScenarioPicker({ forms, cond, setCond }) {
  const path = cond.scenario_path || [];
  const formOf = () => (cond.campaign?.length === 1 ? forms.find((f) => f.campaign_id === cond.campaign[0]) : null) || forms.find((f) => f.campaign_id === null) || forms[0];
  const form = formOf();
  const columns = [];
  let nodes = form ? form.scenarios : [];
  for (let i = 0; i <= path.length && nodes && nodes.length; i += 1) {
    columns.push(nodes);
    const next = nodes.find((n) => n.name === path[i]);
    nodes = next ? next.children : null;
  }

  const pickForm = (key) => {
    const f = forms.find((x) => x.key === key);
    setCond({ scenario_path: [], campaign: f && f.campaign_id ? [f.campaign_id] : undefined });
  };
  const pick = (level, name) => setCond({ scenario_path: name ? [...path.slice(0, level), name] : path.slice(0, level) });

  if (forms.length === 0) {
    return <Field label="Scenario" hint="This client has no scenarios yet. Set them up under Inbound & ticket form."><input disabled placeholder="No scenarios set up" /></Field>;
  }
  return (
    <div className="stack" style={{ gap: 8, gridColumn: "1 / -1" }}>
      {forms.length > 1 && (
        <Field label="Scenarios of">
          <select value={form.key} onChange={(e) => pickForm(e.target.value)}>{forms.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select>
        </Field>
      )}
      <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8 }}>
        {columns.map((opts, i) => (
          <Field key={i} label={LEVEL[i] || `Level ${i + 1}`}>
            <select value={path[i] || ""} onChange={(e) => pick(i, e.target.value)}>
              <option value="">{i === 0 ? "Any scenario" : "Any (everything under it)"}</option>
              {opts.map((n) => <option key={n.name} value={n.name}>{n.name}</option>)}
            </select>
          </Field>
        ))}
      </div>
      <div className="small muted">{path.length ? `Only for: ${path.join(" › ")}${path.length < 5 ? " (and everything under it)" : ""}` : "Leave on “Any” to alert for every scenario."}</div>
      {cond.scenario_contains && <div className="small muted">This alert also matches scenarios containing “{cond.scenario_contains}”. <button type="button" className="btn btn-sm btn-ghost" onClick={() => setCond({ scenario_contains: "" })}>Remove that</button></div>}
    </div>
  );
}
