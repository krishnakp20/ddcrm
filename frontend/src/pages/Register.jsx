import { useState } from "react";
import { Link } from "react-router-dom";
import BasicClientForm from "../components/BasicClientForm";

const STEPS = [
  ["1", "Register", "Share your company and contact details."],
  ["2", "We review", "Our team checks the details and activates your account."],
  ["3", "Sign in and complete", "Set your password, then add your address, documents and logo."],
];

/** Public page opened from "Register your company" on the login screen. */
export default function Register() {
  const [done, setDone] = useState(false);

  return (
    <div className="login-wrap">
      <aside className="login-hero">
        <div>
          <span className="hero-tag">New client</span>
          <h2>Get your company on DialDesk.</h2>
          <p className="lead">Register in a minute. You can add the rest of your details after your account is activated.</p>
        </div>
        <ul className="hero-points">
          {STEPS.map(([n, title, text]) => (
            <li key={n}>
              <span className="pt">{n}</span>
              <div><b>{title}</b><span>{text}</span></div>
            </li>
          ))}
        </ul>
        <div className="hero-bars" aria-hidden="true">
          <i style={{ background: "var(--brand-red)" }} /><i style={{ background: "var(--brand-yellow)" }} />
          <i style={{ background: "#2a8aa6" }} /><i style={{ background: "var(--brand-lime)" }} />
        </div>
      </aside>

      <main className="login-panel">
        <div className="login-inner" style={{ maxWidth: 480 }}>
          <img className="login-logo" src="/dialdesk-logo.svg" alt="DialDesk" />
          {done ? (
            <div className="stack">
              <h1>Thank you!</h1>
              <p className="muted" style={{ margin: 0 }}>
                We received your registration. Our team will review it and activate your account. You will get a message on your email and
                mobile number with the link to set your password.
              </p>
              <Link className="btn" to="/login">Back to sign in</Link>
            </div>
          ) : (
            <>
              <div>
                <h1>Register your company</h1>
                <p className="muted" style={{ margin: "6px 0 0" }}>Already registered? <Link to="/login">Sign in</Link></p>
              </div>
              <BasicClientForm endpoint="/public/register" submitLabel="Submit registration" withTerms onDone={() => setDone(true)} />
            </>
          )}
        </div>
      </main>
    </div>
  );
}
