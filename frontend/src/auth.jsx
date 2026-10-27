import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import api from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);

  const refresh = useCallback(async () => {
    const me = await api.get("/auth/me");
    setUser(me.data);
    return me.data;
  }, []);

  const start = useCallback(() => {
    if (!localStorage.getItem("token")) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setUnreachable(false);
    refresh()
      .catch((err) => {
        // Only a real "not signed in" answer signs the person out. If the server is merely restarting
        // or the network blinked, keep the login and let them retry.
        if (err.response?.status === 401) localStorage.removeItem("token");
        else setUnreachable(true);
      })
      .finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => { start(); }, [start]);

  async function login(email, password) {
    const body = new URLSearchParams({ username: email, password });
    const { data } = await api.post("/auth/login", body);
    localStorage.setItem("token", data.access_token);
    return refresh();
  }

  function logout() {
    localStorage.removeItem("token");
    setUser(null);
  }

  const can = (perm) => !!user?.permissions?.includes(perm);
  const canAny = (...perms) => perms.some(can);

  return <AuthContext.Provider value={{ user, loading, unreachable, retry: start, login, logout, refresh, can, canAny }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

export function RequireAuth({ children }) {
  const { user, loading, unreachable, retry } = useAuth();
  const location = useLocation();
  if (loading) return <div className="center muted">Loading…</div>;
  if (unreachable) {
    return (
      <div className="center stack" style={{ alignItems: "center" }}>
        <b>Cannot reach the server</b>
        <span className="muted">You are still signed in. Check your connection and try again.</span>
        <button className="btn btn-primary" onClick={retry}>Try again</button>
      </div>
    );
  }
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return children;
}
