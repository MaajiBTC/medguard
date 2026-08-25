import { useState } from 'react';

import { login } from '../api/auth';

/**
 * Staff login screen.
 *
 * SECURITY NOTE (per CLAUDE.md / plan): no behavioral capture listeners are wired
 * anywhere on this page, including the password field below. Capturing keystroke
 * timing on a password field would store timing data that could effectively
 * reconstruct the typed password -- a serious self-inflicted hole in a security
 * product. useBehavioralCapture is only ever mounted inside the authenticated app
 * shell, after a session token exists. See App.jsx.
 */
function LoginPage({ onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const data = await login(username, password);
      onLoginSuccess(data);
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      {/*
        Inert placeholder for the future three.js login scene. CLAUDE.md scopes
        three.js to exactly two places: this login/landing page and the Security
        Dashboard visualization (step 4+). The `three` package is intentionally NOT
        installed yet -- no unused dependency until that later task actually builds
        the 3D piece.
      */}
      <div className="three-scene-placeholder" aria-hidden="true">
        <span>three.js scene placeholder</span>
      </div>

      <form className="login-form" onSubmit={handleSubmit}>
        <h1>MedGuard</h1>
        <p className="login-subtitle">Staff login</p>

        <label htmlFor="username">Username</label>
        <input
          id="username"
          name="username"
          type="text"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}

export default LoginPage;
