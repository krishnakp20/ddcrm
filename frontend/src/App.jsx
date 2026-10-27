import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ScopeProvider } from "./scope";
import { AuthProvider, RequireAuth, useAuth } from "./auth";
import Layout from "./components/Layout";
import AgentCall from "./pages/AgentCall";
import AgentHome from "./pages/AgentHome";
import AgentQueue from "./pages/AgentQueue";
import Alerts from "./pages/Alerts";
import Apr from "./pages/Apr";
import Cdr from "./pages/Cdr";
import DialerServers from "./pages/DialerServers";
import Intake from "./pages/Intake";
import Reports from "./pages/Reports";
import TicketDetail from "./pages/TicketDetail";
import TicketNew from "./pages/TicketNew";
import Tickets from "./pages/Tickets";
import CampaignDetail from "./pages/CampaignDetail";
import Campaigns from "./pages/Campaigns";
import ClientDetail from "./pages/ClientDetail";
import Clients from "./pages/Clients";
import Dashboard from "./pages/Dashboard";
import FormSetup from "./pages/FormSetup";
import Departments from "./pages/Departments";
import Login from "./pages/Login";
import PlanDetail from "./pages/PlanDetail";
import PlanForm from "./pages/PlanForm";
import Plans from "./pages/Plans";
import Profile from "./pages/Profile";
import Register from "./pages/Register";
import { RoleForm, RolesList } from "./pages/Roles";
import Settings from "./pages/Settings";
import SetPassword from "./pages/SetPassword";
import UserForm from "./pages/UserForm";
import Users from "./pages/Users";

/** Shows the page only to people holding one of the permissions; everyone else goes back to the dashboard. */
function Guard({ any, children }) {
  const { canAny } = useAuth();
  return canAny(...any) ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
      <ScopeProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/set-password/:token" element={<SetPassword />} />
          <Route element={<RequireAuth><Layout /></RequireAuth>}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/clients" element={<Guard any={["clients.view"]}><Clients /></Guard>} />
            <Route path="/clients/:id" element={<Guard any={["clients.view"]}><ClientDetail /></Guard>} />
            <Route path="/plans" element={<Guard any={["plans.view"]}><Plans /></Guard>} />
            <Route path="/plans/new" element={<Guard any={["plans.manage"]}><PlanForm /></Guard>} />
            <Route path="/plans/:id" element={<Guard any={["plans.view"]}><PlanDetail /></Guard>} />
            <Route path="/plans/:id/edit" element={<Guard any={["plans.manage"]}><PlanForm /></Guard>} />
            <Route path="/profile" element={<Guard any={["profile.manage"]}><Profile /></Guard>} />
            <Route path="/agent" element={<Guard any={["calls.work"]}><AgentHome /></Guard>} />
            <Route path="/reports" element={<Guard any={["reports.view"]}><Reports /></Guard>} />
            <Route path="/intake" element={<Guard any={["alerts.manage"]}><Intake /></Guard>} />
            <Route path="/cdr" element={<Guard any={["cdr.view"]}><Cdr /></Guard>} />
            <Route path="/apr" element={<Guard any={["apr.view"]}><Apr /></Guard>} />
            <Route path="/dialer-servers" element={<Guard any={["dialer.manage"]}><DialerServers /></Guard>} />
            <Route path="/alerts" element={<Guard any={["alerts.manage"]}><Alerts /></Guard>} />
            <Route path="/tickets" element={<Guard any={["tickets.view"]}><Tickets /></Guard>} />
            <Route path="/tickets/new" element={<Guard any={["tickets.manage"]}><TicketNew /></Guard>} />
            <Route path="/tickets/:id" element={<Guard any={["tickets.view"]}><TicketDetail /></Guard>} />
            <Route path="/agent/queue" element={<Guard any={["calls.work"]}><AgentQueue /></Guard>} />
            <Route path="/agent/call" element={<Guard any={["calls.work"]}><AgentCall /></Guard>} />
            <Route path="/agent/call/:id" element={<Guard any={["calls.work"]}><AgentCall /></Guard>} />
            <Route path="/campaigns" element={<Guard any={["campaigns.view"]}><Campaigns /></Guard>} />
            <Route path="/campaigns/:id" element={<Guard any={["campaigns.view"]}><CampaignDetail /></Guard>} />
            <Route path="/forms" element={<Guard any={["forms.view", "forms.manage"]}><FormSetup /></Guard>} />
            <Route path="/users" element={<Guard any={["users.view"]}><Users /></Guard>} />
            <Route path="/users/new" element={<Guard any={["users.manage"]}><UserForm /></Guard>} />
            <Route path="/users/:id" element={<Guard any={["users.view"]}><UserForm /></Guard>} />
            <Route path="/departments" element={<Guard any={["departments.manage", "users.view"]}><Departments /></Guard>} />
            <Route path="/roles" element={<Guard any={["roles.manage"]}><RolesList /></Guard>} />
            <Route path="/roles/new" element={<Guard any={["roles.manage"]}><RoleForm /></Guard>} />
            <Route path="/roles/:id" element={<Guard any={["roles.manage"]}><RoleForm /></Guard>} />
            <Route path="/settings" element={<Guard any={["settings.manage"]}><Settings /></Guard>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ScopeProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
