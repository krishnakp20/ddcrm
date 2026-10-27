import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { errorMessage, fieldErrors } from "../api";
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, useToast } from "./ui";
import { MODE, rs } from "../pages/Plans";

const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "—");
const STATE = { current: ["active", "Current"], upcoming: ["submitted", "Starts later"], past: ["draft", "Ended"] };

/** "Plan & billing" tab of a client: the plan timeline with effective dates, and who is not billed. */
export default function ClientBilling({ client }) {
  const [plan, setPlan] = useState(null);
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  const [assigning, setAssigning] = useState(false);
  const [toast, setToast, toastEl] = useToast();
  const canAssign = client.status === "active" || client.status === "suspended";

  const load = useCallback(() => {
    api.get(`/clients/${client.id}/plan`).then((r) => setPlan(r.data)).catch((e) => setError(errorMessage(e)));
    api.get(`/clients/${client.id}/billing-settings`).then((r) => setSettings(r.data)).catch((e) => setError(errorMessage(e)));
  }, [client.id]);
  useEffect(load, [load]);

  async function cancel(row) {
    if (!window.confirm(`Cancel the change to ${row.plan_name} from ${fmtDate(row.effective_from)}?`)) return;
    try { await api.delete(`/clients/${client.id}/plan-assignments/${row.id}`); setToast("Plan change cancelled"); load(); }
    catch (e) { setError(errorMessage(e)); }
  }

  if (!plan || !settings) return error ? <ErrorBox error={error} /> : <Spinner />;
  const current = plan.rows.find((r) => r.state === "current");
  const upcoming = plan.rows.filter((r) => r.state === "upcoming");

  return (
    <div className="stack">
      <ErrorBox error={error} />
      {!canAssign && <div className="alert info">Activate the client before giving it a plan.</div>}

      <div className="card card-pad">
        <div className="row spread wrap" style={{ marginBottom: 14 }}>
          <div className="section-title" style={{ margin: 0 }}>Plan</div>
          <button className="btn btn-primary" disabled={!canAssign} onClick={() => setAssigning(true)}>
            {plan.first_allocation ? "Give a plan" : "Change plan"}
          </button>
        </div>
        {current ? (
          <div className="row wrap" style={{ gap: 16 }}>
            <div className="grow">
              <div className="row wrap"><Link to={`/plans/${current.plan_id}`}><h2>{current.plan_name}</h2></Link><Badge tone="success">Current</Badge></div>
              <div className="small muted">{current.plan_type} · {MODE[current.plan_mode]} · since {fmtDate(current.effective_from)}</div>
            </div>
          </div>
        ) : upcoming.length ? (
          <span className="muted">No plan is running yet. {upcoming[0].plan_name} starts on {fmtDate(upcoming[0].effective_from)}.</span>
        ) : <span className="muted">This client has no plan yet.</span>}
        {upcoming.map((u) => (
          <div key={u.id} className="alert warn row wrap" style={{ marginTop: 12 }}>
            <span className="grow">From <b>{fmtDate(u.effective_from)}</b> the client moves to <b>{u.plan_name}</b>{u.note ? ` (${u.note})` : ""}.</span>
            <button className="btn btn-sm" onClick={() => cancel(u)}>Cancel this change</button>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-head"><h3>Plan history</h3></div>
        {plan.rows.length === 0 ? <Empty>No plans given yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Plan</th><th>From</th><th>To</th><th>Status</th><th>Note</th></tr></thead>
              <tbody>
                {plan.rows.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/plans/${r.plan_id}`}><b>{r.plan_name}</b></Link><div className="small muted">{r.plan_type} · {MODE[r.plan_mode]}</div></td>
                    <td>{fmtDate(r.effective_from)}</td>
                    <td>{r.effective_to ? fmtDate(r.effective_to) : <span className="muted">Open</span>}</td>
                    <td><span className={`badge ${STATE[r.state][0]}`}>{STATE[r.state][1]}</span></td>
                    <td className="small muted">{r.note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <BillingSettings clientId={client.id} data={settings} onSaved={(d) => { setSettings(d); setToast("Billing settings saved"); }} />
      {assigning && <AssignModal clientId={client.id} plan={plan} onClose={() => setAssigning(false)} onDone={() => { setAssigning(false); setToast("Plan saved"); load(); }} />}
      {toastEl}
    </div>
  );
}

function AssignModal({ clientId, plan, onClose, onDone }) {
  const [planId, setPlanId] = useState("");
  const [date, setDate] = useState(plan.today);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const live = plan.rows.filter((r) => r.state !== "past");
  const last = live[0];
  const min = plan.first_allocation ? new Date(new Date(plan.today).getTime() - 90 * 864e5).toISOString().slice(0, 10) : plan.today;
  const current = plan.rows.find((r) => r.state === "current");

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(""); setErrors({});
    try {
      await api.post(`/clients/${clientId}/plan-assignments`, { plan_id: Number(planId), effective_from: date, note: note || null });
      onDone();
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
    } finally { setBusy(false); }
  }

  const endsOn = current && date ? new Date(new Date(date).getTime() - 864e5).toISOString().slice(0, 10) : null;

  return (
    <Modal title={plan.first_allocation ? "Give a plan" : "Change plan"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="assign-form" disabled={busy || !planId}>{busy ? "Saving…" : "Save"}</button></>}>
      <form id="assign-form" className="stack" onSubmit={submit}>
        <ErrorBox error={error} />
        {plan.available_plans.length === 0 && (
          <div className="alert warn">There is no approved plan yet. <Link to="/plans">Create a plan</Link> and get it approved first (open the plan and click Approve).</div>
        )}
        <Field label="Plan *" error={errors.plan_id} hint="Only approved plans are listed">
          <select value={planId} onChange={(e) => setPlanId(e.target.value)} autoFocus>
            <option value="">Select a plan…</option>
            {plan.available_plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {MODE[p.plan_mode]} · {rs(p.subscription_amount)}</option>)}
          </select>
        </Field>
        <Field label="Effective from *" error={errors.effective_from}
          hint={plan.first_allocation ? "The first plan may start up to 90 days ago." : last ? `Must be after ${fmtDate(last.effective_from)}, the start of the latest plan.` : undefined}>
          <input type="date" value={date} min={min} onChange={(e) => setDate(e.target.value)} required style={{ maxWidth: 220 }} />
        </Field>
        {endsOn && date > plan.today && (
          <div className="alert info small">The current plan, <b>{current.plan_name}</b>, runs until <b>{fmtDate(endsOn)}</b>; the new plan starts on <b>{fmtDate(date)}</b>.</div>
        )}
        <Field label="Note (optional)"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Client asked for a monthly plan" /></Field>
      </form>
    </Modal>
  );
}

function BillingSettings({ clientId, data, onSaved }) {
  const [excl, setExcl] = useState(() => Object.fromEntries(data.users.filter((u) => u.excluded).map((u) => [u.id, u.reason || ""])));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true); setError("");
    try {
      const { data: d } = await api.put(`/clients/${clientId}/billing-settings`, {
        exclusions: Object.entries(excl).map(([id, reason]) => ({ user_id: Number(id), reason: reason || null })),
      });
      onSaved(d);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  const billable = data.users.filter((u) => u.is_active && !(u.id in excl)).length;
  const extra = data.free_users != null ? Math.max(0, billable - data.free_users) : null;

  return (
    <div className="card">
      <div className="card-head">
        <div><h3>Users we do not bill</h3><div className="small muted">Tick users that this client must not be charged for, for example your own support agents.</div></div>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      </div>
      <ErrorBox error={error} />
      {data.users.length === 0 ? <Empty>This client has no users yet. Agents and managers appear here once they are added.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Do not bill</th><th>User</th><th>Role</th><th>Reason</th></tr></thead>
            <tbody>
              {data.users.map((u) => (
                <tr key={u.id}>
                  <td><input type="checkbox" checked={u.id in excl} onChange={(e) => { const n = { ...excl }; if (e.target.checked) n[u.id] = ""; else delete n[u.id]; setExcl(n); }} /></td>
                  <td><b>{u.name}</b><div className="small muted">{u.email}{!u.is_active ? " · blocked" : ""}</div></td>
                  <td><Badge>{u.role.replace("_", " ")}</Badge></td>
                  <td><input disabled={!(u.id in excl)} placeholder="Why is this user free?" value={excl[u.id] ?? ""} onChange={(e) => setExcl({ ...excl, [u.id]: e.target.value })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="card-body row wrap" style={{ gap: 24, borderTop: "1px solid var(--border)" }}>
        <div><div className="small muted">Billable users</div><b style={{ fontSize: 20 }}>{billable}</b></div>
        {extra != null ? <>
          <div><div className="small muted">Free in plan</div><b style={{ fontSize: 20 }}>{data.free_users}</b></div>
          <div><div className="small muted">Extra users</div><b style={{ fontSize: 20 }}>{extra}</b></div>
          <div><div className="small muted">Extra user charge</div><b style={{ fontSize: 20 }}>{rs(extra * Number(data.extra_user_charge))}</b></div>
        </> : <span className="muted small">Give the client a plan to see the extra user charge.</span>}
      </div>
    </div>
  );
}
