import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import { ErrorBox, Field } from "../components/ui";

/** Opened from the welcome message: the new user chooses their own password. */
export default function SetPassword() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [fatal, setFatal] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.get(`/auth/set-password/${token}`).then((r) => setInfo(r.data)).catch((e) => setFatal(errorMessage(e)));
  }, [token]);

  const rules = [
    ["At least 8 characters", pw.length >= 8],
    ["A letter and a number", /[A-Za-z]/.test(pw) && /\d/.test(pw)],
    ["Both entries match", pw.length > 0 && pw === pw2],
  ];

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await api.post("/auth/set-password", { token, password: pw });
      setDone(true);
      setTimeout(() => navigate("/login"), 2500);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <div className="login-wrap" style={{ gridTemplateColumns: "1fr" }}>
      <main className="login-panel">
        <div className="login-inner">
          <img className="login-logo" src="/dialdesk-logo.svg" alt="DialDesk" />
          {fatal ? (
            <div className="stack"><h1>Link not valid</h1><p className="muted" style={{ margin: 0 }}>{fatal}</p><Link to="/login">Go to sign in</Link></div>
          ) : done ? (
            <div className="stack"><h1>Password saved</h1><p className="muted" style={{ margin: 0 }}>Taking you to the sign-in page…</p></div>
          ) : !info ? <div className="muted">Checking your link…</div> : (
            <form className="login-card" onSubmit={submit}>
              <div>
                <h1>Welcome, {info.name.split(" ")[0]}</h1>
                <p className="muted" style={{ margin: "6px 0 0" }}>Choose a password for <b>{info.email}</b>.</p>
              </div>
              <ErrorBox error={error} />
              <Field label="New password"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus autoComplete="new-password" /></Field>
              <Field label="Confirm password"><input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></Field>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }} className="small">
                {rules.map(([t, ok]) => <li key={t} style={{ color: ok ? "var(--success)" : "var(--muted)" }}>{ok ? "✓" : "○"} {t}</li>)}
              </ul>
              <button className="btn btn-primary btn-lg" disabled={busy || !rules.every(([, ok]) => ok)}>{busy ? "Saving…" : "Save password"}</button>
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
