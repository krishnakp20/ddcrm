import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { Badge, Empty, ErrorBox, PageHead, fmtDateTime, useToast } from "../components/ui";

const GROUPS = [
  ["After a client registers (acknowledgement)", ["received_email_subject", "received_email_body", "received_sms", "received_whatsapp"]],
  ["Welcome message after activation", ["welcome_email_subject", "welcome_email_body", "welcome_sms", "welcome_whatsapp"]],
  ["Invitation for a new user (admin user, client user, agent)", ["user_invite_email_subject", "user_invite_email_body", "user_invite_sms", "user_invite_whatsapp"]],
];
const LABEL = {
  received_email_subject: "Email subject", received_email_body: "Email body", received_sms: "SMS", received_whatsapp: "WhatsApp",
  welcome_email_subject: "Email subject", welcome_email_body: "Email body", welcome_sms: "SMS", welcome_whatsapp: "WhatsApp",
  user_invite_email_subject: "Email subject", user_invite_email_body: "Email body", user_invite_sms: "SMS", user_invite_whatsapp: "WhatsApp",
};

export default function Settings() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "templates";
  return (
    <>
      <PageHead title="Settings" sub="Messages sent to clients, and a record of everything sent" />
      <div className="tabs">
        {[["templates", "Message templates"], ["log", "Notification log"]].map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setParams({ tab: k })}>{l}</button>
        ))}
      </div>
      {tab === "templates" ? <Templates /> : <Log />}
    </>
  );
}

function Channels() {
  const [ch, setCh] = useState(null);
  useEffect(() => { api.get("/settings/channels").then((r) => setCh(r.data)); }, []);
  if (!ch) return null;
  return (
    <div className="card card-pad row wrap" style={{ marginBottom: 16, gap: 18 }}>
      <b>Sending status</b>
      {[["email", "Email (SMTP)"], ["sms", "SMS"], ["whatsapp", "WhatsApp"]].map(([k, l]) => (
        <span key={k} className="row gap-sm">{l}: <span className={`badge ${ch[k] ? "active" : "draft"}`}>{ch[k] ? "Live" : "Not connected, only recorded"}</span></span>
      ))}
    </div>
  );
}

function Templates() {
  const [data, setData] = useState(null);
  const [values, setValues] = useState({});
  const [error, setError] = useState("");
  const [toast, setToast, toastEl] = useToast();

  useEffect(() => { api.get("/settings/templates").then((r) => { setData(r.data); setValues(r.data.templates); }); }, []);
  if (!data) return null;

  async function save() {
    setError("");
    try { await api.put("/settings/templates", { templates: values }); setToast("Templates saved"); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <div className="stack">
      <Channels />
      <div className="alert info">
        Use these placeholders in any text: <span className="chip-row" style={{ display: "inline-flex", verticalAlign: "middle" }}>
          {data.variables.map((v) => <span className="chip" key={v}>{`{${v}}`}</span>)}</span>
      </div>
      <ErrorBox error={error} />
      {GROUPS.map(([title, keys]) => (
        <div className="card card-pad stack" key={title}>
          <h3>{title}</h3>
          {keys.map((k) => (
            <label className="field" key={k}>
              <span className="row spread">{LABEL[k]}
                {values[k] !== data.defaults[k] && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setValues({ ...values, [k]: data.defaults[k] })}>Reset to default</button>}
              </span>
              {k.endsWith("subject") ? (
                <input value={values[k] || ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
              ) : (
                <textarea style={{ minHeight: k.endsWith("body") ? 190 : 80 }} value={values[k] || ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
              )}
            </label>
          ))}
        </div>
      ))}
      <div className="row"><div className="grow" /><button className="btn btn-primary btn-lg" onClick={save}>Save templates</button></div>
      {toastEl}
    </div>
  );
}

function Log() {
  const [rows, setRows] = useState(null);
  const [channel, setChannel] = useState("");
  const [open, setOpen] = useState(null);
  const load = () => api.get("/settings/notifications", { params: { channel: channel || undefined } }).then((r) => setRows(r.data));
  useEffect(() => { load(); }, [channel]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="stack">
      <Channels />
      <div className="card">
        <div className="card-head">
          <h3>Last 100 messages</h3>
          <div className="row">
            <select style={{ width: 160 }} value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="">All channels</option><option value="email">Email</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option>
            </select>
            <button className="btn btn-sm" onClick={load}>Refresh</button>
          </div>
        </div>
        {!rows ? null : rows.length === 0 ? <Empty>No messages yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Channel</th><th>To</th><th>Subject / message</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map((n) => (
                  <Fragment key={n.id}>
                    <tr className="click" onClick={() => setOpen(open === n.id ? null : n.id)}>
                      <td className="small">{fmtDateTime(n.created_at)}</td>
                      <td style={{ textTransform: "capitalize" }}>{n.channel}</td>
                      <td>{n.recipient}</td>
                      <td>{n.subject || n.body.slice(0, 70)}</td>
                      <td><Badge tone={n.status === "sent" ? "success" : n.status === "failed" ? "danger" : ""}>{n.status === "logged" ? "recorded" : n.status}</Badge></td>
                    </tr>
                    {open === n.id && (
                      <tr><td colSpan={5}><div className="msg-body">{n.body}</div>{n.error && <div className="alert error" style={{ marginTop: 8 }}>{n.error}</div>}</td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
