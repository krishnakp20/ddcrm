import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { Badge, ErrorBox, Field, Spinner, useToast } from "./ui";

const LABEL = { sent: "Loaded", pending: "Waiting", claimed: "Being loaded", duplicate: "Already in dialer", failed: "Failed" };
const blank = (servers) => ({ id: null, server_id: servers[0]?.id || "", list_id: "", phone_code: "91", dup_check: "DUPLIST", is_active: true, send_existing: false,
  field_map: [{ to: "first_name", from: "name" }, { to: "email", from: "email" }, { to: "city", from: "city" }] });

/** Where this campaign's leads are loaded in the dialer (staff). Leads from uploads and from the client's webhook line up here automatically. */
export default function DialerListPanel({ campaign }) {
  const base = `/campaigns/${campaign.id}/dialer-lists`;
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();

  const load = useCallback(() => api.get(base).then((r) => setData(r.data)).catch((e) => setError(errorMessage(e))), [base]);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  async function save() {
    setBusy(true); setError("");
    try {
      const { data: r } = await api.put(base, { ...form, server_id: Number(form.server_id) });
      setToast(r.queued_existing ? `Saved. ${r.queued_existing} existing lead(s) lined up.` : "Saved");
      setForm(null); load();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function act(fn, ok) { setBusy(true); setError(""); try { await fn(); setToast(ok); load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }

  if (!data) return error ? <ErrorBox error={error} /> : <Spinner />;
  const setMap = (i, k, v) => setForm({ ...form, field_map: form.field_map.map((m, j) => (j === i ? { ...m, [k]: v } : m)) });

  return (
    <div className="card">
      <div className="card-head">
        <h3>Send to the dialer</h3>
        <Badge tone={data.items.some((i) => i.is_active) ? "success" : undefined}>{data.items.some((i) => i.is_active) ? "On" : "Not connected"}</Badge>
      </div>
      <div className="card-body stack">
        <ErrorBox error={error} />
        <p className="muted" style={{ margin: 0 }}>
          New numbers from a file upload or from the client's webhook are added to the Vicidial list below by the script on that server (within a minute). Nothing is ever deleted from the dialer, and a number already in the list is not added twice.
        </p>

        {data.items.map((d) => (
          <div key={d.id} className="card card-pad stack" style={{ gap: 8 }}>
            <div className="row wrap" style={{ justifyContent: "space-between" }}>
              <div><b>{d.server}</b> · list <span className="mono">{d.list_id}</span> {!d.is_active && <Badge>Paused</Badge>}</div>
              <div className="row">
                <button className="btn btn-sm" onClick={() => setForm({ ...d, send_existing: false })}>Edit</button>
                {d.counts.failed > 0 && <button className="btn btn-sm" disabled={busy} onClick={() => act(() => api.post(`${base}/${d.id}/retry`), "Failed leads queued again")}>Try failed again</button>}
                <button className="btn btn-sm btn-ghost" style={{ color: "var(--danger)" }} onClick={() => window.confirm("Stop sending to this list? Leads already in the dialer stay there.") && act(() => api.delete(`${base}/${d.id}`), "Removed")}>Stop sending</button>
              </div>
            </div>
            <div className="row wrap" style={{ gap: 14 }}>
              {Object.keys(LABEL).map((k) => <span key={k} className="small"><b>{d.counts[k]}</b> <span className="muted">{LABEL[k]}</span></span>)}
            </div>
            <div className="small muted">Sends: {d.field_map.map((m) => `${m.from} → ${m.to}`).join(", ") || "phone number only"}</div>
            {d.last_error && d.counts.failed > 0 && <div className="small" style={{ color: "var(--danger)" }}>Last problem: {d.last_error}</div>}
          </div>
        ))}

        {!form && <div><button className="btn btn-primary" onClick={() => setForm(blank(data.servers))} disabled={data.servers.length === 0}>{data.items.length ? "Add another list" : "Connect a dialer list"}</button>
          {data.servers.length === 0 && <span className="small muted"> Add a server first under System &gt; Dialer servers.</span>}</div>}

        {form && (
          <div className="card card-pad stack">
            <div className="form-grid">
              <Field label="Dialer server">
                <select value={form.server_id} disabled={!!form.id} onChange={(e) => setForm({ ...form, server_id: e.target.value })}>{data.servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
              </Field>
              <Field label="Vicidial list ID" hint="One fixed list for this campaign. It must already exist in Vicidial, under the campaign that dials it.">
                <input value={form.list_id} onChange={(e) => setForm({ ...form, list_id: e.target.value })} placeholder="1001" />
              </Field>
              <Field label="Country code"><input value={form.phone_code} onChange={(e) => setForm({ ...form, phone_code: e.target.value })} /></Field>
              <Field label="If the number is already in Vicidial" hint="DUPLIST = same list, DUPCAMP = same campaign, DUPSYS = anywhere, NONE = add anyway.">
                <select value={form.dup_check} onChange={(e) => setForm({ ...form, dup_check: e.target.value })}>{data.dup_checks.map((o) => <option key={o}>{o}</option>)}</select>
              </Field>
            </div>
            <div>
              <div className="section-title">What is sent with the phone number</div>
              {form.field_map.map((m, i) => (
                <div key={i} className="row" style={{ marginBottom: 6 }}>
                  <select style={{ width: 150 }} value={m.from} onChange={(e) => setMap(i, "from", e.target.value)}>
                    {data.sources.includes(m.from) ? null : m.from ? <option>{m.from}</option> : <option value="">CRM field…</option>}
                    {data.sources.map((s) => <option key={s}>{s}</option>)}
                  </select>
                  <input style={{ width: 140 }} placeholder="or a data column" value={data.sources.includes(m.from) ? "" : m.from} onChange={(e) => setMap(i, "from", e.target.value)} />
                  <span className="muted">→</span>
                  <input style={{ width: 190 }} list="vici-targets" placeholder="dialer field or custom:NAME" value={m.to} onChange={(e) => setMap(i, "to", e.target.value)} />
                  <button className="btn btn-sm btn-ghost" onClick={() => setForm({ ...form, field_map: form.field_map.filter((_, j) => j !== i) })}>Remove</button>
                </div>
              ))}
              <datalist id="vici-targets">{data.targets.map((t) => <option key={t} value={t} />)}</datalist>
              <button className="btn btn-sm" onClick={() => setForm({ ...form, field_map: [...form.field_map, { to: "", from: "" }] })}>Add a field</button>
              <p className="small muted" style={{ margin: "8px 0 0" }}>Name and number are always sent. Pick a CRM field (name, email, city, ext_ref) or type the name of any other column the client sends, and the Vicidial field it goes to. For a Vicidial custom field type <span className="mono">custom:FIELDNAME</span>.</p>
            </div>
            <label className="row" style={{ gap: 8 }}><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Sending is on</label>
            <label className="row" style={{ gap: 8 }}><input type="checkbox" checked={form.send_existing} onChange={(e) => setForm({ ...form, send_existing: e.target.checked })} /> Also send the numbers already in this campaign that nobody has called yet</label>
            <div className="row">
              <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
              <button className="btn" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </div>
        )}
      </div>
      {toastEl}
    </div>
  );
}
