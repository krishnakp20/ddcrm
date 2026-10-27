import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import api from "../api";
import { useAuth } from "../auth";
import ClientSwitcher from "./ClientSwitcher";
import { CompanyAvatar, Icon, initials } from "./ui";


const SCOPED = ["/", "/campaigns", "/users", "/departments", "/forms", "/tickets", "/alerts", "/reports", "/intake", "/cdr", "/apr"];  // pages that follow the chosen client

export default function Layout() {
  const { user, logout, can, canAny } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false); // mobile drawer
  const [menu, setMenu] = useState(false);
  const [pending, setPending] = useState(0);
  const [plansPending, setPlansPending] = useState(0);
  const [overdue, setOverdue] = useState(0);
  const watches = can("clients.view") || can("plans.approve");  // the red numbers count work waiting for the DialDesk team

  useEffect(() => { setOpen(false); setMenu(false); }, [location.pathname]);

  // the red number on "Clients" = registrations waiting for review
  useEffect(() => {
    if (!watches) return;
    const load = () => api.get("/dashboard").then((r) => { setPending(r.data.pending_review || 0); setPlansPending(r.data.plans_to_approve || 0); }).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [watches, location.pathname]);

  useEffect(() => {
    if (!can("tickets.view")) return;
    const load = () => api.get("/tickets/summary").then((r) => setOverdue(r.data.overdue || 0)).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [can, location.pathname]);

  const links = [];
  if (can("calls.work")) links.push({ to: "/agent", icon: "campaign", label: "Agent panel", end: true });
  if (can("calls.work")) links.push({ to: "/agent/queue", icon: "forms", label: "Work queue" });
  links.push({ to: "/", icon: "dashboard", label: "Dashboard", end: true });
  if (can("clients.view")) links.push({ to: "/clients", icon: "clients", label: "Clients", count: pending });
  if (can("tickets.view")) links.push({ to: "/tickets", icon: "forms", label: "Tickets", count: overdue });
  if (can("cdr.view")) links.push({ to: "/cdr", icon: "campaign", label: "Call records (CDR)" });
  if (can("apr.view")) links.push({ to: "/apr", icon: "users", label: "Agent performance (APR)" });
  if (can("reports.view")) links.push({ to: "/reports", icon: "dashboard", label: "Reports" });
  if (can("alerts.manage")) links.push({ to: "/intake", icon: "campaign", label: "Intake channels" });
  if (can("alerts.manage")) links.push({ to: "/alerts", icon: "settings", label: "Alerts" });
  if (can("plans.view")) links.push({ to: "/plans", icon: "plans", label: "Plans", count: can("plans.approve") ? plansPending : 0 });
  if (can("profile.manage")) links.push({ to: "/profile", icon: "clients", label: "Company profile", count: user.client && user.client.profile_percent < 100 ? 1 : 0 });
  if (can("campaigns.view")) links.push({ to: "/campaigns", icon: "campaign", label: "Campaigns" });
  if (canAny("forms.view", "forms.manage")) links.push({ to: "/forms", icon: "forms", label: "Inbound & ticket form" });
  const access = [];
  if (can("users.view")) access.push({ to: "/users", icon: "users", label: "Users" });
  if (canAny("departments.manage", "users.view")) access.push({ to: "/departments", icon: "dept", label: "Departments" });
  if (can("roles.manage")) access.push({ to: "/roles", icon: "shield", label: "Roles & permissions" });
  const system = [...(can("dialer.manage") ? [{ to: "/dialer-servers", icon: "settings", label: "Dialer servers" }] : []), ...(can("settings.manage") ? [{ to: "/settings", icon: "settings", label: "Settings" }] : [])];

  const item = (l) => (
    <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => (isActive ? "active" : "")}>
      <span className="ico"><Icon name={l.icon} /></span>
      {l.label}
      {l.count > 0 && <span className="count">{l.count}</span>}
    </NavLink>
  );

  return (
    <div className="app">
      <div className={`scrim ${open ? "open" : ""}`} onClick={() => setOpen(false)} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand"><img src="/dialdesk-logo.svg" alt="DialDesk" /></div>
        <nav className="nav">
          <div className="nav-label">Main</div>
          {links.map(item)}
          {access.length > 0 && <div className="nav-label">Access</div>}
          {access.map(item)}
          {system.length > 0 && <div className="nav-label">System</div>}
          {system.map(item)}
        </nav>
        <div className="sidebar-user">
          <span className="avatar-co">{initials(user.name)}</span>
          <div style={{ minWidth: 0 }}>
            <b style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.name}</b>
            <span className="r">{user.role_name || "User"}</span>
          </div>
        </div>
        <div className="side-foot">DialDesk CRM · v0.4</div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="btn btn-ghost burger" onClick={() => setOpen(true)} aria-label="Open menu">
            <span style={{ width: 20, height: 20, display: "inline-block" }}>
              <svg viewBox="0 0 24 24" style={{ stroke: "currentColor", fill: "none", strokeWidth: 2, strokeLinecap: "round" }}><path d="M3 6h18M3 12h18M3 18h18" /></svg>
            </span>
          </button>
          {user.client ? (
            <div className="client-chip">
              {user.client.logo_url ? <img src={user.client.logo_url} alt={user.client.name} /> : <CompanyAvatar name={user.client.name} />}
              {!user.client.logo_url && <span>{user.client.name}</span>}
            </div>
          ) : (
            <div className="crumb">
              {user.user_type === "agent" ? "Agent workspace" : "Administration"}
              <span className="pill">{user.role_name || "User"}</span>
            </div>
          )}
          <div className="grow" />
          {SCOPED.some((p) => (p === "/" ? location.pathname === "/" : location.pathname.startsWith(p))) && <ClientSwitcher />}
          <div className="user-menu">
            <button className="user-btn" onClick={() => setMenu(!menu)}>
              <span className="avatar-co" style={{ borderRadius: 999 }}>{initials(user.name)}</span>
              <span className="who">{user.name}<small>{user.role_name || "User"}</small></span>
            </button>
            {menu && (
              <div className="menu-pop">
                <div style={{ padding: "8px 10px" }}>
                  <b>{user.name}</b>
                  <div className="small muted">{user.email}</div>
                </div>
                <button onClick={() => { logout(); navigate("/login"); }}>Sign out</button>
              </div>
            )}
          </div>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
