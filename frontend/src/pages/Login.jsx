import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field } from "../components/ui";

const POINTS = [
  ["☎", "Customer opens as the call connects", "Inbound and outbound calls pop up with full details."],
  ["🏢", "Many clients, one agent screen", "Each client keeps its own data, forms and access."],
  ["✓", "Every call tagged and followed up", "Nothing is left open once a call ends."],
];

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={next} replace />;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password);
      navigate(next, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <aside className="login-hero">
        <div>
          <span className="hero-tag">Call-centre CRM</span>
          <h2>Every client. Every call. One screen.</h2>
          <p className="lead">Run inbound and outbound calling for all your clients from a single, simple workspace.</p>
        </div>
        <ul className="hero-points">
          {POINTS.map(([icon, title, text]) => (
            <li key={title}>
              <span className="pt">{icon}</span>
              <div><b>{title}</b><span>{text}</span></div>
            </li>
          ))}
        </ul>
        <div className="hero-bars" aria-hidden="true">
          <i style={{ background: "var(--brand-red)" }} />
          <i style={{ background: "var(--brand-yellow)" }} />
          <i style={{ background: "#2a8aa6" }} />
          <i style={{ background: "var(--brand-lime)" }} />
        </div>
      </aside>

      <main className="login-panel">
        <div className="login-inner">
          <img className="login-logo" src="/dialdesk-logo.svg" alt="DialDesk" />
          <form className="login-card" onSubmit={submit}>
            <div>
              <h1>Welcome back</h1>
              <p className="muted" style={{ margin: "6px 0 0" }}>Sign in to your DialDesk workspace.</p>
            </div>
            <ErrorBox error={error} />
            <Field label="Email">
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus autoComplete="username" placeholder="you@company.com" />
            </Field>
            <Field label="Password">
              <div className="pw-wrap">
                <input type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" placeholder="Your password" />
                <button type="button" className="pw-toggle" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"}>
                  {show ? "Hide" : "Show"}
                </button>
              </div>
            </Field>
            <button className="btn btn-primary btn-lg" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
          <div className="login-foot">
            <div className="register-box">
              New to DialDesk? <Link to="/register"><b>Register your company</b></Link>
            </div>
            <div style={{ marginTop: 10 }}>Forgot your password? Ask your administrator to reset it.</div>
          </div>
        </div>
      </main>
    </div>
  );
}
