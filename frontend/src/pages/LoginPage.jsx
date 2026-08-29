import { useRef, useState } from 'react';

import { login } from '../api/auth';
import { computeKeystrokeFeatures, createKeystrokeAccumulator } from '../capture/behavioral/keystrokeFeatures';
import LoginScene from './LoginScene';

/**
 * Staff login screen.
 *
 * SECURITY NOTE (per CLAUDE.md): keystroke capture here computes only derived,
 * anonymized timing features (flight/digraph/trigraph latency, error/correction
 * rate, rhythm consistency, automation flags) -- never raw key identity. That's
 * what makes it safe to run directly on the username/password fields: no key
 * code is ever stored, so typing the password never risks recording the
 * password itself. See keystrokeFeatures.js. Handlers are scoped to just these
 * two inputs (not global window listeners) -- the rest of the session's capture
 * is handled separately by useBehavioralCapture in the authenticated app shell.
 */
function LoginPage({ onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const keystrokeAccumulatorRef = useRef(createKeystrokeAccumulator());

  const handleKeyDown = (e) => keystrokeAccumulatorRef.current.recordDown(e.key, performance.now());
  const handleKeyUp = (e) => keystrokeAccumulatorRef.current.recordUp(e.key, performance.now());
  const handlePaste = () => keystrokeAccumulatorRef.current.recordPaste();

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const keystrokeFeatures = computeKeystrokeFeatures(keystrokeAccumulatorRef.current.drain());
      const data = await login(username, password, keystrokeFeatures);
      onLoginSuccess(data);
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-brand-panel">
        <LoginScene />
        <div className="login-brand-text">
          <h1>MedGuard</h1>
          <p className="login-tagline">Safe access, seamless healthcare.</p>
        </div>
      </div>

      <div className="login-form-panel">
        <form className="login-form" onSubmit={handleSubmit}>
          <h2>Welcome back</h2>
          <p className="login-subtitle">Sign in with your staff ID and password.</p>

          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            type="text"
            placeholder="Enter staff username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={handleKeyDown}
            onKeyUp={handleKeyUp}
            onPaste={handlePaste}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            placeholder="Enter your password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={handleKeyDown}
            onKeyUp={handleKeyUp}
            onPaste={handlePaste}
            required
          />

          {error && (
            <p className="login-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default LoginPage;
