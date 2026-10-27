import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { Badge, Empty, ErrorBox, PageHead, Spinner, fmtDateTime } from "../components/ui";

/** The agent's manual dialing queue: the campaign data waiting for them, taken one lead at a time. */
export default function AgentQueue() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [camps, setCamps] = useState(null);
  const [open, setOpen] = useState(null);        // campaign id whose own list is shown
  const [mine, setMine] = useState([]);
  const [alloc, setAlloc] = useState({});        // campaign id -> chosen allocation id ("" = all)
  const [problem, setProblem] = useState(null);  // {message, code, open_call_id}
  const [busy, setBusy] = useState(false);
  const autoTook = useRef(false);

  const load = useCallback(() => api.get("/agent/queue").then((r) => setCamps(r.data)).catch((e) => setProblem({ message: errorMessage(e) })), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (camps && !open && camps.length) setOpen(camps.find((c) => c.mine > 0)?.id || camps[0].id);
  }, [camps, open]);
  useEffect(() => { if (open) api.get(`/agent/queue/${open}`, { params: { batch_id: alloc[open] === undefined || alloc[open] === "" ? undefined : alloc[open] } }).then((r) => setMine(r.data)).catch(() => setMine([])); }, [open, camps, alloc]);

  async function take(campaignId, leadId, batchId) {
    setBusy(true); setProblem(null);
    try {
      const { data } = await api.post("/agent/queue/take", { campaign_id: campaignId, lead_id: leadId, batch_id: batchId === "" || batchId === undefined ? undefined : Number(batchId) });
      navigate(`/agent/call/${data.interaction.id}`);
    } catch (e) {
      const d = e.response?.data?.detail;
      setProblem({ message: errorMessage(e), code: d?.code, open_call_id: d?.open_call_id });
      load();
    } finally { setBusy(false); }
  }

  // "Next lead" on the call screen comes here and takes the next one straight away
  useEffect(() => {
    const id = Number(params.get("take"));
    if (!id || autoTook.current || !camps) return;
    autoTook.current = true;
    setParams({}, { replace: true });
    take(id);
  }, [params, camps]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!camps) return problem ? <ErrorBox error={problem.message} /> : <Spinner />;
  return (
    <>
      <PageHead title="Work queue" sub="Campaign data waiting for you. Take one lead at a time: call, then tag it." />

      {problem && (
        <div className="alert warn" style={{ marginBottom: 12 }}>
          {problem.message}
          {problem.open_call_id && <> <Link className="btn btn-sm btn-primary" to={`/agent/call/${problem.open_call_id}`}>Open that call</Link></>}
        </div>
      )}

      {camps.length === 0 ? <div className="card"><Empty>You are not allocated to any campaign yet. Ask your admin.</Empty></div> : (
        <div className="grid cols-2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0,1fr) minmax(0,1.4fr)" }}>
          <div className="stack">
            {camps.map((c) => (
              <div key={c.id} className="card card-pad" style={{ borderColor: open === c.id ? "var(--primary)" : undefined, cursor: "pointer" }} onClick={() => setOpen(c.id)}>
                <div className="row spread"><h3>{c.name}</h3><Badge tone={c.status === "active" ? "success" : "warn"}>{c.status}</Badge></div>
                <div className="row wrap" style={{ margin: "10px 0", gap: 18 }}>
                  <div><div className="kpi-value">{c.mine}</div><div className="small muted">Yours now</div></div>
                  <div><div className="kpi-value">{c.shared}</div><div className="small muted">Shared queue</div></div>
                  <div><div className="kpi-value" style={{ color: c.callbacks ? "var(--warn)" : undefined }}>{c.callbacks}</div><div className="small muted">Call backs due</div></div>
                </div>
                {c.later > 0 && <div className="small muted" style={{ marginBottom: 8 }}>{c.later} more later (retries and call backs not due yet)</div>}
                {c.allocations.length > 0 && (
                  <div style={{ marginBottom: 10 }} onClick={(e) => e.stopPropagation()}>
                    <label className="small muted">Allocation</label>
                    <select value={alloc[c.id] ?? ""} onChange={(e) => { setOpen(c.id); setAlloc({ ...alloc, [c.id]: e.target.value }); }}>
                      <option value="">All allocations</option>
                      {c.allocations.map((a) => <option key={a.id} value={a.id}>{a.name} · yours {a.mine} · shared {a.shared}</option>)}
                    </select>
                  </div>
                )}
                <button className="btn btn-primary" disabled={busy || c.status !== "active" || c.mine + c.shared === 0}
                  onClick={(e) => { e.stopPropagation(); take(c.id, undefined, alloc[c.id]); }}>
                  {c.status !== "active" ? `Campaign is ${c.status}` : c.mine + c.shared === 0 ? "Nothing to call right now" : "Take next lead"}
                </button>
              </div>
            ))}
          </div>

          <div className="card">
            <div className="card-head"><h3>Your leads</h3><span className="small muted">{camps.find((c) => c.id === open)?.name}{alloc[open] ? ` · ${camps.find((c) => c.id === open)?.allocations.find((a) => String(a.id) === String(alloc[open]))?.name || ""}` : ""}</span></div>
            {mine.length === 0 ? <Empty>No data is assigned to you in this campaign. Use “Take next lead” to pick from the shared queue.</Empty> : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Name</th><th>Mobile</th><th>Status</th><th>Next call</th><th /></tr></thead>
                  <tbody>
                    {mine.map((l) => (
                      <tr key={l.id}>
                        <td><b>{l.name}</b>{l.city && <div className="small muted">{l.city}</div>}</td>
                        <td className="mono">{l.mobile}</td>
                        <td><Badge tone={l.status === "callback" ? "warn" : ""}>{l.status === "callback" ? "Call back" : l.attempts ? `Try ${l.attempts + 1}` : "New"}</Badge></td>
                        <td className="small">{l.next_call_at ? fmtDateTime(l.next_call_at) : "Now"}</td>
                        <td style={{ textAlign: "right" }}>
                          <button className="btn btn-sm" disabled={busy || (l.next_call_at && new Date(l.next_call_at) > new Date())} onClick={() => take(open, l.id)}>Call</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
