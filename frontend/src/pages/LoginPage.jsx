import { useEffect, useRef, useState } from 'react';

import { login, pollDeviceRequest } from '../api/auth';
import { setToken } from '../api/client';
import { computeKeystrokeFeatures, createKeystrokeAccumulator } from '../capture/behavioral/keystrokeFeatures';
import LoginScene from './LoginScene';

const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

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
 *
 * One device per (clinical) account (added 2026-08-30): a login attempt from a
 * device that isn't the account's approved one comes back as
 * {status: 'pending_approval', poll_token} instead of a token -- `phase` below
 * tracks the resulting wait/declined/expired states while polling
 * pollDeviceRequest() for the primary device's owner to accept or decline it
 * from their own Profile > Devices panel.
 */
function LoginPage({ onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [phase, setPhase] = useState('form'); // 'form' | 'waiting' | 'declined' | 'expired'
  const [pollToken, setPollToken] = useState(null);
  const pollStartRef = useRef(null);
  const keystrokeAccumulatorRef = useRef(createKeystrokeAccumulator());

  const handleKeyDown = (e) => keystrokeAccumulatorRef.current.recordDown(e.key, performance.now());
  const handleKeyUp = (e) => keystrokeAccumulatorRef.current.recordUp(e.key, performance.now());
  const handlePaste = () => keystrokeAccumulatorRef.current.recordPaste();

  useEffect(() => {
    if (phase !== 'waiting' || !pollToken) return undefined;

    const intervalId = setInterval(async () => {
      try {
        const data = await pollDeviceRequest(pollToken);
        if (data.status === 'approved' && data.token) {
          setToken(data.token);
          onLoginSuccess({ staff: data.staff });
          return;
        }
        if (data.status === 'rejected') {
          setPhase('declined');
          return;
        }
      } catch {
        // Transient network hiccup -- keep polling rather than failing the wait.
      }
      if (Date.now() - pollStartRef.current > POLL_TIMEOUT_MS) {
        setPhase('expired');
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [phase, pollToken, onLoginSuccess]);

  const handleBackToForm = () => {
    setPhase('form');
    setPollToken(null);
    setPassword('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const keystrokeFeatures = computeKeystrokeFeatures(keystrokeAccumulatorRef.current.drain());
      const data = await login(username, password, keystrokeFeatures);
      if (data.status === 'pending_approval') {
        pollStartRef.current = Date.now();
        setPollToken(data.poll_token);
        setPhase('waiting');
        return;
      }
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
        {phase === 'form' && (
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
        )}

        {phase === 'waiting' && (
          <div className="login-form login-pending">
            <h2>Waiting for approval</h2>
            <p className="login-subtitle">
              This device isn't approved for this account yet. Ask whoever normally
              signs in on this account to approve it from Profile &gt; Devices.
            </p>
            <div className="login-pending-spinner" aria-hidden="true" />
            <button type="button" onClick={handleBackToForm}>
              Cancel
            </button>
          </div>
        )}

        {phase === 'declined' && (
          <div className="login-form login-pending">
            <h2>Request declined</h2>
            <p className="login-subtitle">The account owner declined this device.</p>
            <button type="button" onClick={handleBackToForm}>
              Back to sign in
            </button>
          </div>
        )}

        {phase === 'expired' && (
          <div className="login-form login-pending">
            <h2>Request expired</h2>
            <p className="login-subtitle">Nobody responded in time. Try signing in again.</p>
            <button type="button" onClick={handleBackToForm}>
              Try again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default LoginPage;
