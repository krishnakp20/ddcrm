import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { PRIORITIES, PriorityBadge, SlaChip, SourceChip, TicketStatus } from "../components/TicketBits";
import { Empty, ErrorBox, Field, Icon, PageHead, Pager, Spinner, fmtDateTime, useDebounced, useToast } from "../components/ui";
import { useScope } from "../scope";

const VIEWS = [["open", "Open"], ["mine", "Mine"], ["unassigned", "Unassigned"], ["overdue", "Overdue"], ["all", "All"]];

export default function Tickets() {
  const { can } = useAuth();
  const { clientId } = useScope();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const view = params.get("view") || "open";
  const [data, setData] = useState(null);
  const [priority, setPriority] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (view === "sla") return;
    api.get("/tickets", { params: { view, priority: priority || undefined, client_id: clientId || undefined, q: dq || undefined, page } })
      .then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
  }, [view, priority, clientId, dq, page]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => setPage(1), [view, priority, clientId, dq]);
  useEffect(() => { const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);

  const tabs = [...VIEWS, ...(can("tickets.sla") ? [["sla", "SLA settings"]] : [])];
  return (
    <>
      <PageHead title="Tickets" sub="Follow-ups raised from calls or created offline, with status, owner and a time to resolve.">
        {can("tickets.manage") && <Link className="btn btn-primary" to="/tickets/new"><span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> New ticket</Link>}
      </PageHead>
      <ErrorBox error={error} />

      <div className="tabs">
        {tabs.map(([k, l]) => (
          <button key={k} className={`tab ${view === k ? "active" : ""}`} onClick={() => setParams(k === "open" ? {} : { view: k })}>
            {l}{data && data.counts[k] != null && <span className={`badge ${k === "overdue" && data.counts[k] ? "danger" : ""}`} style={{ marginLeft: 8 }}>{data.counts[k]}</span>}
          </button>
        ))}
      </div>

      {view === "sla" ? <SlaSettings /> : !data ? <Spinner /> : (
        <div className="card">
          <div className="card-head">
            <div className="row wrap">
              <input style={{ width: 260 }} placeholder="Search number, subject, customer, mobile" value={q} onChange={(e) => setQ(e.target.value)} />
              <select style={{ width: 150 }} value={priority} onChange={(e) => setPriority(e.target.value)}>
                <option value="">All priorities</option>
                {PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </div>
            <span className="small muted">{data.total} ticket(s)</span>
          </div>
          {data.items.length === 0 ? <Empty>{view === "all" && !dq ? "No tickets yet." : "Nothing here. Good."}</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Ticket</th><th>Customer</th><th>Priority</th><th>Status</th><th>Assigned to</th><th>Time to resolve</th><th>Created</th></tr></thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} className="click" onClick={() => navigate(`/tickets/${t.id}`)}>
                      <td><b>{t.subject}</b> <SourceChip source={t.source} /><div className="small muted mono">{t.number} · {t.client_name}</div></td>
                      <td>{t.customer_name}<div className="small muted mono">{t.mobile}</div></td>
                      <td><PriorityBadge priority={t.priority} /></td>
                      <td><TicketStatus status={t.status} /></td>
                      <td>{t.assigned_to || <span className="muted">Unassigned</span>}{t.department && <div className="small muted">{t.department}</div>}</td>
                      <td><SlaChip sla={t.sla} due={t.due_at} /></td>
                      <td className="small">{fmtDateTime(t.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </div>
      )}
    </>
  );
}

/** Time to resolve per priority, for one client. */
function SlaSettings() {
  const { user } = useAuth();
  const staff = user.user_type === "staff";
  const { clientId: scoped } = useScope();
  const [clients, setClients] = useState([]);
  const [cid, setCid] = useState("");
  const [rules, setRules] = useState(null);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast, toastEl] = useToast();

  useEffect(() => { api.get("/tickets/clients").then((r) => { setClients(r.data); setCid(String(scoped || r.data[0]?.id || "")); }).catch((e) => setError(errorMessage(e))); }, [scoped]);
  useEffect(() => {
    if (!cid && staff) return;
    api.get("/tickets/sla", { params: { client_id: cid || undefined } }).then((r) => setRules(r.data.rules.map((x) => ({ ...x, resolve_hours: String(x.resolve_hours) })))).catch((e) => setError(errorMessage(e)));
  }, [cid, staff]);

  async function save() {
    setBusy(true); setError(""); setErrors({});
    try {
      const body = rules.map((r) => ({ priority: r.priority, resolve_hours: /^\d+$/.test(r.resolve_hours) ? Number(r.resolve_hours) : r.resolve_hours }));
      const { data } = await api.put("/tickets/sla", { client_id: cid ? Number(cid) : undefined, rules: body });
      setRules(data.rules.map((x) => ({ ...x, resolve_hours: String(x.resolve_hours) }))); setToast("SLA saved");
    } catch (e) { setError(errorMessage(e)); setErrors(e.response?.data?.detail?.fields || {}); } finally { setBusy(false); }
  }

  if (!rules) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <div className="card card-pad stack" style={{ maxWidth: 640 }}>
      <ErrorBox error={error} />
      <p className="muted" style={{ margin: 0 }}>How many hours a ticket may stay unresolved, by priority. The clock starts when the ticket is created and stops when it is resolved. Changing a ticket's priority recalculates its due time; tickets already created keep their time.</p>
      {staff && (
        <Field label="Client">
          <select value={cid} onChange={(e) => setCid(e.target.value)}>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        </Field>
      )}
      <div className="form-grid">
        {rules.map((r, i) => (
          <Field key={r.priority} label={`${PRIORITIES.find(([k]) => k === r.priority)[1]} (hours)`} error={errors[r.priority]} hint={r.custom ? "Set for this client" : "Standard time (not changed yet)"}>
            <input inputMode="numeric" value={r.resolve_hours} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, resolve_hours: e.target.value } : x)))} />
          </Field>
        ))}
      </div>
      <div><button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save SLA"}</button></div>
      {toastEl}
    </div>
  );
}
