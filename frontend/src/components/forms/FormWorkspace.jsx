import { useCallback, useEffect, useState } from "react";
import api, { errorMessage } from "../../api";
import { ErrorBox, Field, Modal, Spinner, useToast } from "../ui";
import FieldsTab from "./FieldsTab";
import FormRunner from "./FormRunner";
import ListsTab from "./ListsTab";
import ScenariosTab from "./ScenariosTab";

/**
 * Everything for setting up ONE form: fields, scenarios, value lists, preview and copy.
 * formKey is "in_call" (the client's inbound / ticket form) or "campaign-<id>" (that campaign's tagging form).
 */
export default function FormWorkspace({ clientId, formKey, staff, tab, onTab, clients = [], ownClientId, onLoaded }) {
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState("");
  const [copying, setCopying] = useState(false);
  const [toast, setToast, toastEl] = useToast();
  const base = `/forms/${clientId}/${formKey}`;
  const isCampaign = formKey.startsWith("campaign-");

  const load = useCallback(() => {
    api.get(base).then((r) => { setCfg(r.data); setError(""); onLoaded?.(r.data); }).catch((e) => setError(errorMessage(e)));
  }, [base]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setCfg(null); load(); }, [load]);

  if (error && !cfg) return <ErrorBox error={error} />;
  if (!cfg) return <Spinner />;

  const canManage = cfg.can_manage;
  // a campaign form can be copied by anyone who may change forms; an inbound form only by DialDesk staff
  const canCopy = canManage && (isCampaign || staff);
  const TABS = [["fields", `Fields (${cfg.fields.length})`], ["scenarios", "Scenarios"], ["lists", "Value lists"], ["preview", "Preview"]];

  return (
    <>
      {!canManage && <div className="alert info" style={{ marginBottom: 14 }}>You can look at this setup but not change it. Ask DialDesk to give you the right to change forms.</div>}
      <div className="row spread wrap" style={{ marginBottom: 6 }}>
        <div className="tabs" style={{ flex: 1, marginBottom: 0, borderBottom: 0 }}>
          {TABS.map(([k, l]) => <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => onTab(k)}>{l}</button>)}
        </div>
        {canCopy && <button className="btn btn-sm" onClick={() => setCopying(true)}>{isCampaign ? "Copy form from another campaign" : "Copy from another client"}</button>}
      </div>
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16 }}>
        <ErrorBox error={error} />
        {tab === "fields" && <FieldsTab cfg={cfg} base={base} reload={load} canManage={canManage} staff={staff} />}
        {tab === "scenarios" && <ScenariosTab cfg={cfg} base={base} reload={load} canManage={canManage} />}
        {tab === "lists" && <ListsTab clientId={clientId} canManage={canManage} staff={staff} />}
        {tab === "preview" && <FormRunner cfg={cfg} base={base} />}
      </div>
      {copying && (
        <CopyModal base={base} isCampaign={isCampaign} staff={staff} clients={clients} clientId={clientId} ownClientId={ownClientId}
          campaignId={cfg.campaign?.id} onClose={() => setCopying(false)}
          onDone={(r) => { setCopying(false); setToast(`Copied ${r.fields} fields and ${r.scenarios} scenarios`); load(); }} />
      )}
      {toastEl}
    </>
  );
}

function CopyModal({ base, isCampaign, staff, clients, clientId, ownClientId, campaignId, onClose, onDone }) {
  const [sourceClient, setSourceClient] = useState(isCampaign ? String(clientId) : "");
  const [campaigns, setCampaigns] = useState([]);
  const [sourceCampaign, setSourceCampaign] = useState("");
  const [replace, setReplace] = useState(false);
  const [needsReplace, setNeedsReplace] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // campaigns of the chosen client, except the one being filled
  useEffect(() => {
    if (!isCampaign || !sourceClient) return;
    setSourceCampaign("");
    api.get("/campaigns", { params: { client_id: sourceClient } })
      .then((r) => setCampaigns(r.data.items.filter((c) => c.id !== campaignId)))
      .catch((e) => setError(errorMessage(e)));
  }, [isCampaign, sourceClient, campaignId]);

  async function go() {
    setBusy(true); setError("");
    try {
      const body = { source_client_id: Number(sourceClient), replace };
      if (isCampaign) body.source_campaign_id = Number(sourceCampaign);
      onDone((await api.post(`${base}/copy-from`, body)).data);
    } catch (e) {
      if (e.response?.status === 409) setNeedsReplace(true);
      setError(errorMessage(e));
    } finally { setBusy(false); }
  }

  const ready = isCampaign ? !!sourceCampaign : !!sourceClient;
  return (
    <Modal title={isCampaign ? "Copy the form of another campaign" : "Copy a form from another client"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!ready || busy || (needsReplace && !replace)} onClick={go}>{busy ? "Copying…" : "Copy"}</button></>}>
      <div className="stack">
        <ErrorBox error={error} />
        <p className="muted" style={{ margin: 0 }}>
          {isCampaign
            ? "Copies the fields, scenarios and values of the chosen campaign into this campaign. The two forms stay separate afterwards."
            : "Copies the fields, scenarios and value lists into this client's form."}
        </p>
        {(!isCampaign || staff) && (
          <Field label={isCampaign ? "Client" : "Copy from client"}>
            <select value={sourceClient} onChange={(e) => setSourceClient(e.target.value)}>
              {!isCampaign && <option value="">Select a client…</option>}
              {clients.filter((c) => isCampaign || c.id !== clientId).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        {isCampaign && (
          <Field label="Campaign to copy from">
            <select value={sourceCampaign} onChange={(e) => setSourceCampaign(e.target.value)}>
              <option value="">{campaigns.length ? "Select a campaign…" : "No other campaign for this client"}</option>
              {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.fields_count} fields, {c.scenarios_count} scenarios)</option>)}
            </select>
          </Field>
        )}
        {needsReplace && <span className="check"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace what this form already has</span>}
      </div>
    </Modal>
  );
}
