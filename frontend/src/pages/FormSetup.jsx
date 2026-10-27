import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { useScope } from "../scope";
import FormWorkspace from "../components/forms/FormWorkspace";
import { Empty, ErrorBox, Field, PageHead, Spinner } from "../components/ui";

/** The client's inbound call and ticket form. Outbound forms belong to campaigns (see Campaigns). */
export default function FormSetup() {
  const { user, can } = useAuth();
  const staff = user.user_type === "staff";
  const [params, setParams] = useSearchParams();
  const [clients, setClients] = useState(null);
  const [error, setError] = useState("");

  const tab = ["fields", "scenarios", "lists", "preview"].includes(params.get("tab")) ? params.get("tab") : "fields";
  const scoped = useScope().clientId;
  const clientId = (scoped && clients?.some((c) => String(c.id) === scoped) ? Number(scoped) : 0) || Number(params.get("client")) || clients?.[0]?.id;
  const update = (patch) => setParams({ client: clientId, tab, ...patch });

  useEffect(() => { api.get("/forms/clients").then((r) => setClients(r.data)).catch((e) => setError(errorMessage(e))); }, []);

  if (error && !clients) return <ErrorBox error={error} />;
  if (!clients) return <Spinner />;
  if (clients.length === 0) return <><PageHead title="Inbound call & ticket form" /><div className="card"><Empty>There is no active client yet. Activate a client first.</Empty></div></>;

  return (
    <>
      <PageHead title="Inbound call & ticket form" sub="One form per client. It opens when a call arrives and when an agent creates a ticket for this client.">
        {can("campaigns.view") && <Link className="btn" to="/campaigns">Outbound forms: open Campaigns</Link>}
      </PageHead>
      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <Field label="Client">
          {staff ? (
            <select value={clientId} onChange={(e) => update({ client: e.target.value })} style={{ minWidth: 0, width: "min(100%, 320px)" }}>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          ) : <b style={{ padding: "8px 0" }}>{clients[0].name}</b>}
        </Field>
      </div>
      <FormWorkspace key={clientId} clientId={clientId} formKey="in_call" staff={staff} tab={tab} onTab={(t) => update({ tab: t })} clients={clients} ownClientId={user.client_id} />
    </>
  );
}
