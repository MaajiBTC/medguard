import { Fragment, useCallback, useEffect, useState } from 'react';

import { getLedgerEntries } from '../api/ledger';
import { createStaff } from '../api/staff';
import Modal from '../components/Modal';
import DashboardShell, { LedgerIcon, StaffIcon } from './DashboardShell';
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

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

/** Ledger page: live, filterable feed of AUDITED_DEVIATION/REDUCED_ACCESS/
 * ACCESS_DENIED/EMERGENCY_OVERRIDE events with drill-down, plus the three.js
 * visualization scoped to this screen (per CLAUDE.md). */
function LedgerPanel() {
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
    <>
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
    </>
  );
}

const NEW_ADMIN_INITIAL = { username: '', password: '', staff_id: '', full_name: '' };

/** Admins page: the only place an admin account can be created (added
 * 2026-08-30, per the user) -- Admin dashboard's own "Add Staff" no longer
 * offers the admin role, so this is the sole path. Admin accounts are shared
 * (no ward/on-duty/on-call), so the form only asks for login + identity. */
function AdminsPanel() {
  const [createOpen, setCreateOpen] = useState(false);
  const [newAdmin, setNewAdmin] = useState(NEW_ADMIN_INITIAL);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const handleCreate = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createStaff({ ...newAdmin, role: 'admin' });
      setNotice(`Admin account "${newAdmin.staff_id}" created.`);
      setNewAdmin(NEW_ADMIN_INITIAL);
      setCreateOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div>
      <div className="search-row">
        <p className="meta-line">Security officers are the only role that can create admin accounts.</p>
        <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>
          + Create Admin
        </button>
      </div>

      {notice && <p className="notice">{notice}</p>}

      {createOpen && (
        <Modal title="Create Admin Account" onClose={() => setCreateOpen(false)}>
          <form onSubmit={handleCreate}>
            <label className="form-label">
              Username
              <input className="form-input" value={newAdmin.username} onChange={(e) => setNewAdmin({ ...newAdmin, username: e.target.value })} required />
            </label>
            <label className="form-label">
              Password
              <input className="form-input" type="password" value={newAdmin.password} onChange={(e) => setNewAdmin({ ...newAdmin, password: e.target.value })} required minLength={8} />
            </label>
            <label className="form-label">
              Staff ID
              <input className="form-input" value={newAdmin.staff_id} onChange={(e) => setNewAdmin({ ...newAdmin, staff_id: e.target.value })} required />
            </label>
            <label className="form-label">
              Full name
              <input className="form-input" value={newAdmin.full_name} onChange={(e) => setNewAdmin({ ...newAdmin, full_name: e.target.value })} required />
            </label>
            {error && <p role="alert" className="dev-error">{error}</p>}
            <div className="button-row">
              <button type="button" className="btn-secondary" onClick={() => setCreateOpen(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Save Admin</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

const PAGE_META = {
  ledger: { title: 'Security Ledger', subtitle: 'Live feed of audited deviations, reduced access, denials, and emergency overrides.' },
  admins: { title: 'Admins', subtitle: 'Create admin accounts — the only role that manages this.' },
};

/** CLAUDE.md's Security Dashboard: the Ledger live feed (its documented core
 * responsibility) plus, added 2026-08-30, sole ownership of admin-account
 * creation (Admin dashboard's own staff creation excludes the admin role). */
function SecurityDashboard({ staff, onLogout }) {
  const [activePage, setActivePage] = useState('ledger');

  const navItems = [
    { key: 'ledger', label: 'Ledger', icon: <LedgerIcon /> },
    { key: 'admins', label: 'Admins', icon: <StaffIcon /> },
  ];

  return (
    <DashboardShell
      navItems={navItems}
      activeItem={activePage}
      onNavChange={setActivePage}
      staff={staff}
      onLogout={onLogout}
      title={PAGE_META[activePage].title}
      subtitle={PAGE_META[activePage].subtitle}
    >
      {activePage === 'ledger' && <LedgerPanel />}
      {activePage === 'admins' && <AdminsPanel />}
    </DashboardShell>
  );
}

export default SecurityDashboard;
