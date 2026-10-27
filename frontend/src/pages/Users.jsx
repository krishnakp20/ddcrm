import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { useScope } from "../scope";
import { Badge, Empty, ErrorBox, Icon, PageHead, Pager, initials, useDebounced } from "../components/ui";

const TYPE_TABS = [["", "All"], ["staff", "DialDesk admin users"], ["client", "Client users"], ["agent", "Agents"]];
export const USER_STATUS = { active: ["active", "Active"], invited: ["submitted", "Invitation sent"], disabled: ["rejected", "Disabled"] };

export function UserStatus({ status }) {
  const [cls, label] = USER_STATUS[status] || ["draft", status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export default function Users() {
  const navigate = useNavigate();
  const { user, can } = useAuth();
  const staff = user.user_type === "staff";
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const { clientId, setClientId } = useScope();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [clients, setClients] = useState([]);
  const [data, setData] = useState({ items: [], total: 0, page_size: 25 });
  const [error, setError] = useState("");

  useEffect(() => { if (staff) api.get("/users/meta").then((r) => setClients(r.data.clients)).catch(() => {}); }, [staff]);
  useEffect(() => setPage(1), [type, dq, clientId, status]);

  const load = useCallback(() => {
    api.get("/users", { params: { type: type || undefined, q: dq || undefined, client_id: clientId || undefined, status: status || undefined, page } })
      .then((r) => { setData(r.data); setError(""); }).catch((e) => setError(errorMessage(e)));
  }, [type, dq, clientId, status, page]);
  useEffect(load, [load]);

  const tabs = staff ? TYPE_TABS : TYPE_TABS.filter(([k]) => k !== "staff");

  return (
    <>
      <PageHead title="Users" sub={staff ? "DialDesk admin users, client users and agents" : "People who work in your company account"}>
        {can("users.manage") && (
          <button className="btn btn-primary" onClick={() => navigate("/users/new")}>
            <span style={{ width: 16, height: 16 }}><Icon name="plus" /></span> Add user
          </button>
        )}
      </PageHead>
      <div className="card">
        <div className="tabs" style={{ padding: "0 14px", marginBottom: 0 }}>
          {tabs.map(([k, l]) => <button key={k} className={`tab ${type === k ? "active" : ""}`} onClick={() => setType(k)}>{l}</button>)}
        </div>
        <div className="row wrap" style={{ padding: 14, borderBottom: "1px solid var(--border)" }}>
          <input style={{ maxWidth: 280 }} placeholder="Search name, email, mobile, dialer ID…" value={q} onChange={(e) => setQ(e.target.value)} />
          {staff && (
            <select style={{ maxWidth: 240 }} value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">All companies</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <select style={{ maxWidth: 170 }} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any status</option><option value="active">Active</option><option value="invited">Invitation sent</option><option value="disabled">Disabled</option>
          </select>
        </div>
        <ErrorBox error={error} />
        {data.items.length === 0 ? <Empty>No users found.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>User</th><th>Type</th><th>Company</th><th>Role</th><th>Department</th><th>Status</th></tr></thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.id} className="click" onClick={() => navigate(`/users/${u.id}`)}>
                    <td>
                      <div className="row">
                        <span className="avatar-co" style={{ borderRadius: 999 }}>{initials(u.name)}</span>
                        <div><b>{u.name}</b><div className="small muted">{u.email}{u.dialer_agent_id ? ` · dialer ${u.dialer_agent_id}` : ""}</div></div>
                      </div>
                    </td>
                    <td><Badge tone={u.user_type === "staff" ? "primary" : ""}>{u.type_label}</Badge></td>
                    <td>{u.client ? u.client.name : <span className="muted">DialDesk</span>}</td>
                    <td>{u.role?.name || "—"}</td>
                    <td>{u.department?.name || <span className="muted">—</span>}</td>
                    <td><UserStatus status={u.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
      </div>
    </>
  );
}
