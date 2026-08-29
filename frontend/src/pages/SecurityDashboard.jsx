import { Fragment, useCallback, useEffect, useState } from 'react';

import { getLedgerEntries } from '../api/ledger';
import DashboardShell, { LedgerIcon } from './DashboardShell';
import LedgerVisualization from './LedgerVisualization';

const POLL_INTERVAL_MS = 5000;

const EVENT_TYPE_OPTIONS = [
  { value: '', label: 'All flagged events' },
  { value: 'AUDITED_DEVIATION', label: 'Audited deviation' },
  { value: 'REDUCED_ACCESS', label: 'Reduced access' },
  { value: 'ACCESS_DENIED', label: 'Access denied' },
  { value: 'EMERGENCY_OVERRIDE', label: 'Emergency override' },
  { value: 'STANDARD_ACCESS', label: 'Standard access (not normally shown)' },
];

/** CLAUDE.md's Security Dashboard: a live, filterable feed of AUDITED_DEVIATION /
 * REDUCED_ACCESS / ACCESS_DENIED / EMERGENCY_OVERRIDE events with drill-down, plus
 * the three.js visualization scoped to this screen. The table is the functional
 * core (filters, drill-down); the three.js panel is a live visual layer on top. */
function SecurityDashboard({ staff, onLogout }) {
  const [eventType, setEventType] = useState('');
  const [staffIdFilter, setStaffIdFilter] = useState('');
  const [patientFilter, setPatientFilter] = useState('');
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);
  const [expandedSequence, setExpandedSequence] = useState(null);

  const fetchEntries = useCallback(async () => {
    try {
      const data = await getLedgerEntries({
        event_type: eventType || undefined,
        staff_id: staffIdFilter || undefined,
        patient_hospital_number: patientFilter || undefined,
      });
      setEntries(eventType ? data : data.filter((e) => e.event_type !== 'STANDARD_ACCESS'));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [eventType, staffIdFilter, patientFilter]);

  useEffect(() => {
    fetchEntries();
    const intervalId = setInterval(fetchEntries, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchEntries]);

  return (
    <DashboardShell
      navItems={[{ key: 'ledger', label: 'Ledger', icon: <LedgerIcon /> }]}
      activeItem="ledger"
      onNavChange={() => {}}
      staff={staff}
      onLogout={onLogout}
      title="Security Ledger"
      subtitle="Live feed of audited deviations, reduced access, denials, and emergency overrides."
    >
      <LedgerVisualization entries={entries} />

      <section className="panel-card">
        <h2>Live feed</h2>
        <form className="ledger-filters" onSubmit={(e) => e.preventDefault()}>
          <select className="form-input" value={eventType} onChange={(e) => setEventType(e.target.value)}>
            {EVENT_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <input
            className="form-input"
            placeholder="Staff ID"
            value={staffIdFilter}
            onChange={(e) => setStaffIdFilter(e.target.value)}
          />
          <input
            className="form-input"
            placeholder="Patient hospital number"
            value={patientFilter}
            onChange={(e) => setPatientFilter(e.target.value)}
          />
        </form>

        {error && <p role="alert" className="dev-error">{error}</p>}

        <table className="ledger-table">
          <thead>
            <tr>
              <th>#</th>
              <th>When</th>
              <th>Event</th>
              <th>Staff</th>
              <th>Patient</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <Fragment key={entry.sequence}>
                <tr
                  className={`ledger-row severity-${entry.event_type}`}
                  onClick={() => setExpandedSequence(expandedSequence === entry.sequence ? null : entry.sequence)}
                >
                  <td>{entry.sequence}</td>
                  <td>{new Date(entry.occurred_at).toLocaleString()}</td>
                  <td>{entry.event_type}</td>
                  <td>{entry.staff_full_name} ({entry.staff_id})</td>
                  <td>{entry.patient_hospital_number || '—'}</td>
                </tr>
                {expandedSequence === entry.sequence && (
                  <tr className="ledger-drilldown">
                    <td colSpan={5}>
                      <pre>{JSON.stringify(entry.details, null, 2)}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>
    </DashboardShell>
  );
}

export default SecurityDashboard;
