import { useEffect, useState } from 'react';

import { getCurrentSession } from '../api/auth';
import { getMyAssignedPatients, searchPatients } from '../api/patients';
import { decide, emergencyOverride, getPatientRecords } from '../api/scoring';
import { useContextualCapture } from '../capture/contextual/useContextualCapture';
import DashboardShell, { PatientsIcon, SearchIcon } from './DashboardShell';

const ASSIGNMENT_ROLES = new Set(['doctor', 'nurse']);

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
    try {
      await setTargetPatient(patient.id);
      const decisionData = await decide(patient.id);
      setDecision(decisionData);
      if (decisionData.decision_type !== 'ACCESS_DENIED') {
        const recordsData = await getPatientRecords(patient.id);
        setRecords(recordsData);
      }
    } catch (err) {
      setViewError(err.data || { detail: err.message });
    } finally {
      setViewLoading(false);
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
              categories are hidden and step-up verification is required for full access.
            </p>
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
