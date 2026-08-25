import { useCallback, useEffect, useState } from 'react';

import { getBehavioralCapture } from '../api/captures';
import { useContextualCapture } from '../capture/contextual/useContextualCapture';

/**
 * TEMPORARY, DEV-ONLY SCREEN.
 *
 * Exercises the capture pipeline (raw event counts, JSON viewers, a plain numeric
 * patient-ID input) before step 4's real search/record UI exists. Remove or hide
 * this once that lands -- it is not part of the product's real UI.
 *
 * Per the user's own decision (see plan), this panel is exercised with real,
 * user-supplied patient data once available -- it deliberately does not create any
 * Patient rows itself.
 */
function CaptureDevPanel({ staff, onLogout, flushNow }) {
  const [behavioral, setBehavioral] = useState(null);
  const [behavioralError, setBehavioralError] = useState(null);
  const [patientIdInput, setPatientIdInput] = useState('');

  const {
    capture: contextual,
    error: contextualError,
    refresh: refreshContextual,
    setTargetPatient,
  } = useContextualCapture();

  const refreshBehavioral = useCallback(async () => {
    try {
      const data = await getBehavioralCapture();
      setBehavioral(data);
      setBehavioralError(null);
    } catch (err) {
      setBehavioralError(err.message);
    }
  }, []);

  useEffect(() => {
    refreshBehavioral();
    refreshContextual().catch(() => {
      // surfaced via contextualError below
    });
  }, [refreshBehavioral, refreshContextual]);

  const handleRefreshBehavioral = async () => {
    if (flushNow) flushNow();
    await refreshBehavioral();
  };

  const handleSetTargetPatient = async (event) => {
    event.preventDefault();
    const patientId = Number(patientIdInput);
    if (!Number.isInteger(patientId) || patientId <= 0) return;
    try {
      await setTargetPatient(patientId);
    } catch {
      // error already captured in useContextualCapture's error state
    }
  };

  return (
    <div className="capture-dev-panel">
      <div className="dev-banner" role="note">
        TEMPORARY DEV-ONLY SCREEN — exercises the capture pipeline ahead of step 4's
        real search/record UI. Remove or hide once that lands.
      </div>

      <header className="dev-panel-header">
        <div>
          <h1>MedGuard capture dev panel</h1>
          {staff && (
            <p>
              Logged in as <strong>{staff.full_name}</strong> ({staff.role}, {staff.staff_id})
            </p>
          )}
        </div>
        <button type="button" onClick={onLogout}>
          Log out
        </button>
      </header>

      <section>
        <h2>Behavioral capture</h2>
        <p className="hint">
          Move the mouse, click, and type anywhere on this page, then flush + refresh
          to see events land server-side.
        </p>
        <button type="button" onClick={handleRefreshBehavioral}>
          Flush + refresh
        </button>
        {behavioralError && (
          <p role="alert" className="dev-error">
            {behavioralError}
          </p>
        )}
        {behavioral && (
          <>
            <ul className="counts">
              <li>
                Login rhythm consistency:{' '}
                {behavioral.keystroke_features?.login
                  ? behavioral.keystroke_features.login.rhythm_consistency.toFixed(2)
                  : '(no login keystrokes captured)'}
              </li>
              <li>
                Login error/correction rate:{' '}
                {behavioral.keystroke_features?.login
                  ? behavioral.keystroke_features.login.error_correction_rate.toFixed(2)
                  : '—'}
              </li>
              <li>
                Login automation flags:{' '}
                {behavioral.keystroke_features?.login?.automation_flags.length
                  ? behavioral.keystroke_features.login.automation_flags.join(', ')
                  : '(none)'}
              </li>
              <li>Session keystroke feature windows: {behavioral.keystroke_features?.session_windows?.length ?? 0}</li>
              <li>Mouse events: {behavioral.mouse_event_count}</li>
              <li>Touch events: {behavioral.touch_event_count}</li>
            </ul>
            <details>
              <summary>Raw BehavioralCapture JSON</summary>
              <pre>{JSON.stringify(behavioral, null, 2)}</pre>
            </details>
          </>
        )}
      </section>

      <section>
        <h2>Contextual capture</h2>
        <form onSubmit={handleSetTargetPatient} className="target-patient-form">
          <label htmlFor="patient-id">Patient ID (numeric)</label>
          <input
            id="patient-id"
            type="number"
            min="1"
            step="1"
            value={patientIdInput}
            onChange={(e) => setPatientIdInput(e.target.value)}
            placeholder="e.g. 1"
          />
          <button type="submit">Set target patient</button>
        </form>
        {contextualError && (
          <p role="alert" className="dev-error">
            {(contextualError.data && contextualError.data.detail) || contextualError.message}
          </p>
        )}
        {contextual && (
          <>
            <ul className="counts">
              <li>On duty at login: {String(contextual.on_duty_at_login)}</li>
              <li>Ward at login: {contextual.ward_assignment_at_login || '(none)'}</li>
              <li>Patient assignment status: {contextual.patient_assignment_status}</li>
            </ul>
            <details>
              <summary>Raw ContextualCapture JSON</summary>
              <pre>{JSON.stringify(contextual, null, 2)}</pre>
            </details>
          </>
        )}
      </section>
    </div>
  );
}

export default CaptureDevPanel;
