import { startAuthentication } from '@simplewebauthn/browser';
import { useCallback, useEffect, useState } from 'react';

import { getCurrentSession } from '../api/auth';
import { getMyAssignedPatients, searchPatients } from '../api/patients';
import {
  approveStepUpAssist,
  declineStepUpAssist,
  decide,
  emergencyOverride,
  getPatientRecords,
  getStepUpAssistRequests,
  getStepUpWebAuthnOptions,
  requestStepUpAssist,
  verifyStepUpWebAuthn,
} from '../api/scoring';
import { useContextualCapture } from '../capture/contextual/useContextualCapture';
import DashboardShell, { PatientsIcon, SearchIcon } from './DashboardShell';

const ASSIGNMENT_ROLES = new Set(['doctor', 'nurse']);
// Any-other-colleague's pending assist requests -- same cadence
// DashboardShell already uses for the pending-device badge.
const ASSIST_BANNER_POLL_MS = 10000;
// While waiting for a colleague to vouch for MY OWN request, same cadence
// the rest of this app already polls a live feed at.
const ASSIST_WAIT_POLL_MS = 5000;

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function timeAgo(isoString) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(isoString).getTime()) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes === 1) return '1 minute ago';
  return `${minutes} minutes ago`;
}

/** Any *other* clinical colleague's pending step-up assist requests (added
 * 2026-09-06) -- the fallback path for a device with no enrolled biometric.
 * Lives at the top of this dashboard, independent of whatever patient (if
 * any) the viewing clinician has open, since a colleague could need help at
 * any moment. */
function AssistRequestsBanner() {
  const [requests, setRequests] = useState([]);
  const [error, setError] = useState(null);
  const [actioningId, setActioningId] = useState(null);

  const fetchRequests = useCallback(async () => {
    try {
      setRequests(await getStepUpAssistRequests());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    fetchRequests();
    const intervalId = setInterval(fetchRequests, ASSIST_BANNER_POLL_MS);
    return () => clearInterval(intervalId);
  }, [fetchRequests]);

  const respond = async (id, action) => {
    setActioningId(id);
    try {
      await action(id);
      await fetchRequests();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActioningId(null);
    }
  };

  if (requests.length === 0 && !error) return null;

  return (
    <section className="panel-card assist-banner">
      <h3>Colleagues asking for step-up verification</h3>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {requests.map((r) => (
        <div className="card-row" key={r.id}>
          <div className="card-row-main">
            <div className="name-line">
              {r.requesting_staff_name} ({formatRole(r.requesting_staff_role)})
            </div>
            <div className="meta-line">
              Patient {r.patient_hospital_number} · requested {timeAgo(r.requested_at)}
            </div>
          </div>
          <div className="card-row-actions">
            <button
              type="button"
              className="btn-primary"
              disabled={actioningId === r.id}
              onClick={() => respond(r.id, approveStepUpAssist)}
            >
              Approve
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={actioningId === r.id}
              onClick={() => respond(r.id, declineStepUpAssist)}
            >
              Decline
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}

/**
 * The real step-4 search -> view flow: search a patient, set them as the session's
 * target (useContextualCapture, already built for step 1), request a decision
 * (scoring.decide), then render only the categories that decision actually granted.
 */
function ClinicalDashboard({ staff, onLogout }) {
  const [session, setSession] = useState(null);
  const [assignedPatients, setAssignedPatients] = useState([]);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  const [selectedPatient, setSelectedPatient] = useState(null);
  const [decision, setDecision] = useState(null);
  const [records, setRecords] = useState(null);
  const [viewError, setViewError] = useState(null);
  const [viewLoading, setViewLoading] = useState(false);

  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideCategory, setOverrideCategory] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideSubmitting, setOverrideSubmitting] = useState(false);
  const [overrideError, setOverrideError] = useState(null);

  // stepUpMode: null (choosing a method) | 'assist-waiting' (request sent,
  // polling for a colleague's response).
  const [stepUpMode, setStepUpMode] = useState(null);
  const [stepUpSubmitting, setStepUpSubmitting] = useState(false);
  const [stepUpError, setStepUpError] = useState(null);

  const { setTargetPatient } = useContextualCapture();

  useEffect(() => {
    getCurrentSession().then(setSession).catch(() => {});
    if (staff && ASSIGNMENT_ROLES.has(staff.role)) {
      getMyAssignedPatients().then(setAssignedPatients).catch(() => {});
    }
  }, [staff]);

  const handleSearch = async (event) => {
    event.preventDefault();
    setSearching(true);
    try {
      const data = await searchPatients(query);
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const openPatient = async (patient) => {
    setSelectedPatient(patient);
    setDecision(null);
    setRecords(null);
    setViewError(null);
    setViewLoading(true);
    setOverrideOpen(false);
    setOverrideCategory('');
    setOverrideReason('');
    setOverrideError(null);
    setStepUpMode(null);
    setStepUpError(null);
    try {
      await setTargetPatient(patient.id);
      const decisionData = await decide(patient.id);
      setDecision(decisionData);
      // A reduced-access decision releases nothing until the step-up PIN is
      // entered (CLAUDE.md's 40-69% band). The backend enforces this too --
      // getPatientRecords() would 403 -- so we simply don't ask yet.
      if (decisionData.decision_type !== 'ACCESS_DENIED' && !decisionData.step_up_required) {
        const recordsData = await getPatientRecords(patient.id);
        setRecords(recordsData);
      }
    } catch (err) {
      setViewError(err.data || { detail: err.message });
    } finally {
      setViewLoading(false);
    }
  };

  // Poll while waiting for a colleague to vouch (added 2026-09-06) -- reuses
  // the existing records endpoint rather than a dedicated poll endpoint: it
  // starts returning 200 the instant step_up_verified flips, same as any
  // other 5s-poll pattern already used in this app.
  useEffect(() => {
    if (stepUpMode !== 'assist-waiting' || !selectedPatient) return undefined;
    const intervalId = setInterval(async () => {
      try {
        const recordsData = await getPatientRecords(selectedPatient.id);
        setRecords(recordsData);
        setDecision((d) => (d ? { ...d, step_up_required: false, step_up_verified: true } : d));
        setStepUpMode(null);
      } catch {
        /* still waiting -- not an error worth surfacing on every poll tick */
      }
    }, ASSIST_WAIT_POLL_MS);
    return () => clearInterval(intervalId);
  }, [stepUpMode, selectedPatient]);

  const handleWebAuthnStepUp = async () => {
    if (!decision || !selectedPatient) return;
    setStepUpSubmitting(true);
    setStepUpError(null);
    try {
      const optionsJSON = await getStepUpWebAuthnOptions(decision.id);
      const credential = await startAuthentication({ optionsJSON });
      await verifyStepUpWebAuthn(decision.id, credential);
      setDecision({ ...decision, step_up_required: false, step_up_verified: true });
      const recordsData = await getPatientRecords(selectedPatient.id);
      setRecords(recordsData);
    } catch (err) {
      setStepUpError(err.data || { detail: err.message });
    } finally {
      setStepUpSubmitting(false);
    }
  };

  const handleRequestAssist = async () => {
    if (!decision) return;
    setStepUpError(null);
    try {
      await requestStepUpAssist(decision.id);
      setStepUpMode('assist-waiting');
    } catch (err) {
      setStepUpError(err.data || { detail: err.message });
    }
  };

  const handleEmergencyOverride = async (event) => {
    event.preventDefault();
    if (!selectedPatient) return;
    setOverrideSubmitting(true);
    setOverrideError(null);
    try {
      const decisionData = await emergencyOverride(selectedPatient.id, overrideCategory, overrideReason);
      setDecision(decisionData);
      setViewError(null);
      const recordsData = await getPatientRecords(selectedPatient.id);
      setRecords(recordsData);
      setOverrideOpen(false);
      setOverrideCategory('');
      setOverrideReason('');
    } catch (err) {
      setOverrideError(err.data || { detail: err.message });
    } finally {
      setOverrideSubmitting(false);
    }
  };

  return (
    <DashboardShell
      navItems={[{ key: 'patients', label: 'Patients', icon: <PatientsIcon /> }]}
      activeItem="patients"
      onNavChange={() => {}}
      staff={staff}
      onLogout={onLogout}
      title="Patients"
    >
      {session && (
        <p className="meta-line">
          {session.on_duty ? 'On duty' : 'Off duty'}
          {session.ward ? ` · ${session.ward}` : ''}
        </p>
      )}

      <AssistRequestsBanner />

      {assignedPatients.length > 0 && (
        <section>
          <h2>Assigned to you</h2>
          {assignedPatients.map((p) => (
            <div className="card-row" key={`${p.patient_id}-${p.role_in_assignment}`}>
              <div className="card-row-main">
                <div className="name-line">{p.full_name}</div>
                <div className="meta-line">
                  {p.hospital_number} · {p.role_in_assignment}
                </div>
              </div>
              <div className="card-row-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => openPatient({ id: p.patient_id, hospital_number: p.hospital_number, full_name: p.full_name })}
                >
                  View
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      <section>
        <h2>Search patients</h2>
        <div className="search-row">
          <form className="search-bar" onSubmit={handleSearch} role="search">
            <SearchIcon />
            <input
              type="text"
              placeholder="Hospital number or name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          <button type="button" className="btn-primary" onClick={handleSearch} disabled={searching}>
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>
        {results.map((p) => (
          <div className="card-row" key={p.id}>
            <div className="card-row-main">
              <div className="name-line">{p.full_name}</div>
              <div className="meta-line">
                {p.hospital_number}
                {p.ward ? ` · ${p.ward}` : ''}
              </div>
            </div>
            <div className="card-row-actions">
              <button type="button" className="btn-secondary" onClick={() => openPatient(p)}>
                View
              </button>
            </div>
          </div>
        ))}
      </section>

      {selectedPatient && (
        <section className="panel-card">
          <h2>
            {selectedPatient.full_name} ({selectedPatient.hospital_number})
          </h2>

          {viewLoading && <p>Checking access…</p>}

          {viewError && (
            <p role="alert" className="dev-error">
              {viewError.detail || 'Access could not be determined.'}
              {typeof viewError.score === 'number' && ` (score: ${viewError.score.toFixed(0)}%)`}
            </p>
          )}

          {decision && decision.decision_type === 'ACCESS_DENIED' && (
            <p role="alert" className="access-denied">
              Access denied. Score: {decision.score.toFixed(0)}%.
            </p>
          )}

          {decision && decision.decision_type === 'REDUCED_ACCESS' && (
            <p role="alert" className="access-reduced">
              Reduced access (score: {decision.score.toFixed(0)}%). Highly sensitive
              categories are hidden, and step-up verification is required before any
              records will open.
            </p>
          )}

          {/* Step-up challenge (added 2026-09-06, mechanism replaced the same
              day -- was a typed PIN, now device biometrics with a
              colleague-vouches fallback; see CLAUDE.md). The backend
              enforces this too (the records endpoint 403s until it's done),
              so this UI isn't the security boundary, just where the
              clinician satisfies it. */}
          {decision && decision.step_up_required && (
            <div className="step-up-control">
              {stepUpMode !== 'assist-waiting' ? (
                <>
                  <div className="button-row">
                    {session?.has_webauthn_credential && (
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={stepUpSubmitting}
                        onClick={handleWebAuthnStepUp}
                      >
                        {stepUpSubmitting ? 'Waiting for your device…' : 'Verify with your device'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={stepUpSubmitting}
                      onClick={handleRequestAssist}
                    >
                      Ask a colleague to verify
                    </button>
                  </div>
                  {!session?.has_webauthn_credential && (
                    <p className="meta-line">
                      This device has no biometric enrolled yet — set one up from your
                      Profile page, or ask a logged-in colleague to verify this session
                      for you now.
                    </p>
                  )}
                </>
              ) : (
                <p className="meta-line">
                  Waiting for a colleague to verify this session — this checks
                  automatically.{' '}
                  <button type="button" className="link-button" onClick={() => setStepUpMode(null)}>
                    Cancel and try something else
                  </button>
                </p>
              )}
              {stepUpError && (
                <p role="alert" className="dev-error">
                  {stepUpError.detail || 'Verification failed.'}
                  {typeof stepUpError.attempts_remaining === 'number' &&
                    ` ${stepUpError.attempts_remaining} attempt${stepUpError.attempts_remaining === 1 ? '' : 's'} remaining.`}
                </p>
              )}
            </div>
          )}

          {decision && decision.decision_type === 'AUDITED_DEVIATION' && (
            <p className="access-audited">
              Access granted, but this session has been flagged for audit (score:{' '}
              {decision.score.toFixed(0)}%).
            </p>
          )}

          {decision && decision.decision_type === 'EMERGENCY_OVERRIDE' && (
            <p className="access-override">
              Break the Glass: emergency access granted and permanently logged to the
              Security Ledger.
            </p>
          )}

          <div className="override-control">
            {!overrideOpen ? (
              <button type="button" className="override-button" onClick={() => setOverrideOpen(true)}>
                Break the Glass (Emergency Override)
              </button>
            ) : (
              <form className="override-form" onSubmit={handleEmergencyOverride}>
                <label className="form-label" htmlFor="override-category">
                  Reason category (required)
                  <select
                    id="override-category"
                    className="form-input"
                    value={overrideCategory}
                    onChange={(e) => setOverrideCategory(e.target.value)}
                    required
                  >
                    <option value="" disabled>
                      Select a reason category…
                    </option>
                    <option value="clinical_emergency">Clinical emergency / direct patient care</option>
                    <option value="cross_coverage">Cross-coverage (covering an unrostered shift)</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label className="form-label" htmlFor="override-reason">
                  Reason detail (required, min 10 characters)
                  <textarea
                    id="override-reason"
                    className="form-input"
                    value={overrideReason}
                    onChange={(e) => setOverrideReason(e.target.value)}
                    rows={3}
                    required
                    minLength={10}
                  />
                </label>
                {overrideError && (
                  <p role="alert" className="dev-error">
                    {overrideError.detail || 'Could not grant emergency access.'}
                  </p>
                )}
                <div className="button-row">
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={overrideSubmitting || !overrideCategory || overrideReason.trim().length < 10}
                  >
                    {overrideSubmitting ? 'Granting…' : 'Confirm Break the Glass'}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setOverrideOpen(false);
                      setOverrideCategory('');
                      setOverrideReason('');
                      setOverrideError(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>

          {records && (
            <div className="category-list">
              {records.records.map((r) => (
                <details key={r.category} className="detail-block" open>
                  <summary>{r.category_name}</summary>
                  <p>{r.content?.notes || '(no notes recorded)'}</p>
                </details>
              ))}
            </div>
          )}
        </section>
      )}
    </DashboardShell>
  );
}

export default ClinicalDashboard;
