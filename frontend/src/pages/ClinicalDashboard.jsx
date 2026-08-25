import { useEffect, useState } from 'react';

import { getCurrentSession } from '../api/auth';
import { getMyAssignedPatients, searchPatients } from '../api/patients';
import { decide, getPatientRecords } from '../api/scoring';
import { useContextualCapture } from '../capture/contextual/useContextualCapture';

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

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <h1>MedGuard</h1>
          {staff && (
            <p>
              <strong>{staff.full_name}</strong> ({staff.role}, {staff.staff_id})
            </p>
          )}
          {session && (
            <p className="duty-status">
              {session.on_duty ? 'On duty' : 'Off duty'}
              {session.ward ? ` · ${session.ward}` : ''}
            </p>
          )}
        </div>
        <button type="button" onClick={onLogout}>
          Log out
        </button>
      </header>

      {assignedPatients.length > 0 && (
        <section>
          <h2>Assigned to you</h2>
          <ul className="patient-list">
            {assignedPatients.map((p) => (
              <li key={`${p.patient_id}-${p.role_in_assignment}`}>
                <button type="button" onClick={() => openPatient({ id: p.patient_id, hospital_number: p.hospital_number, full_name: p.full_name })}>
                  {p.full_name} ({p.hospital_number}) — {p.role_in_assignment}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2>Search patients</h2>
        <form className="search-form" onSubmit={handleSearch}>
          <input
            type="text"
            placeholder="Hospital number or name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" disabled={searching}>
            {searching ? 'Searching…' : 'Search'}
          </button>
        </form>
        {results.length > 0 && (
          <ul className="patient-list">
            {results.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => openPatient(p)}>
                  {p.full_name} ({p.hospital_number}) {p.ward ? `— ${p.ward}` : ''}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selectedPatient && (
        <section className="patient-view">
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

          {records && (
            <div className="category-list">
              {records.records.map((r) => (
                <details key={r.category} open>
                  <summary>{r.category_name}</summary>
                  <p>{r.content?.notes || '(no notes recorded)'}</p>
                </details>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default ClinicalDashboard;
