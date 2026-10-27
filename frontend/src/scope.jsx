import { createContext, useContext, useEffect, useMemo, useState } from "react";
import api from "./api";
import { useAuth } from "./auth";

const Ctx = createContext({ clientId: "", setClientId: () => {}, clients: [], client: null, enabled: false });

/** The client a DialDesk staff member is working on. "" means all clients. Client users are always limited to their own company. */
export function ScopeProvider({ children }) {
  const { user } = useAuth();
  const staff = user?.user_type === "staff";
  const [clients, setClients] = useState([]);
  const [clientId, setId] = useState(() => { try { return localStorage.getItem("scope_client") || ""; } catch { return ""; } });

  useEffect(() => { if (staff) api.get("/dashboard/clients").then((r) => setClients(r.data)).catch(() => {}); }, [staff]);
  // a remembered client that no longer exists falls back to all clients
  useEffect(() => { if (staff && clients.length && clientId && !clients.some((c) => String(c.id) === String(clientId))) setId(""); }, [clients, clientId, staff]);

  const setClientId = (v) => {
    const id = v ? String(v) : "";
    setId(id);
    try { id ? localStorage.setItem("scope_client", id) : localStorage.removeItem("scope_client"); } catch { /* storage unavailable */ }
  };
  const value = useMemo(() => ({
    clientId: staff ? clientId : "", setClientId, clients, enabled: staff,
    client: staff ? clients.find((c) => String(c.id) === String(clientId)) || null : null,
  }), [clientId, clients, staff]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useScope = () => useContext(Ctx);
