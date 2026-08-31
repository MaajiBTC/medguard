import { Fragment, useCallback, useEffect, useState } from 'react';

import { getLedgerEntries } from '../api/ledger';
import { getPatientSummary, searchPatients } from '../api/patients';
import { createStaff, getStaffSummary, searchStaff } from '../api/staff';
import Modal from '../components/Modal';
import { WARDS } from '../wards';
import DashboardShell, { LedgerIcon, PatientsIcon, SearchIcon, StaffIcon } from './DashboardShell';
import { EventTypeBarChart, LedgerDonutChart3D, LedgerRoleBarChart } from './LedgerCharts3D';

const POLL_INTERVAL_MS = 5000;

const EVENT_TYPE_OPTIONS = [
  { value: '', label: 'All events' },
  { value: 'STANDARD_ACCESS', label: 'Standard access' },
  { value: 'AUDITED_DEVIATION', label: 'Audited deviation' },
  { value: 'REDUCED_ACCESS', label: 'Reduced access' },
  { value: 'ACCESS_DENIED', label: 'Access denied' },
  { value: 'EMERGENCY_OVERRIDE', label: 'Emergency override' },
];

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

/** The entries list + row drilldown, shared by the live Ledger feed and the
 * Staff/Patient activity pages below -- same markup, just fed a different
 * (already-filtered) `entries` array. Each entry is its own white row-card
 * (added 2026-08-31, per the user) sitting on a tinted `.ledger-feed`
 * background, rather than one shared table sheet -- same "distinct card per
 * row" language as `.card-row` elsewhere in this app (Staff/Patient lists),
 * just with more columns. */
function LedgerEntriesFeed({ entries, error }) {
  const [expandedSequence, setExpandedSequence] = useState(null);

  return (
    <div className="ledger-feed">
      {error && <p role="alert" className="dev-error">{error}</p>}

      <div className="ledger-row-card ledger-row-card-header">
        <span>#</span>
        <span>Date/Time</span>
        <span>Event</span>
        <span>Staff</span>
        <span>Patient</span>
      </div>

      {entries.map((entry) => (
        <Fragment key={entry.sequence}>
          <div
            className={`ledger-row-card ledger-row-card-entry severity-${entry.event_type}`}
            onClick={() => setExpandedSequence(expandedSequence === entry.sequence ? null : entry.sequence)}
          >
            <span>{entry.sequence}</span>
            <span>{new Date(entry.occurred_at).toLocaleString()}</span>
            <span>{entry.event_type}</span>
            <span>{entry.staff_full_name} ({entry.staff_id})</span>
            <span>{entry.patient_hospital_number || '—'}</span>
          </div>
          {expandedSequence === entry.sequence && (
            <div className="ledger-row-card ledger-drilldown">
              <pre>{JSON.stringify(entry.details, null, 2)}</pre>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}

/** Ledger page: live, filterable feed of all 5 event types (including
 * STANDARD_ACCESS, shown by default again as of 2026-08-31 per the user) with
 * drill-down, plus the three.js visualization scoped to this screen (per
 * CLAUDE.md). Staff/patient lookup moved out to their own sidebar pages below
 * (added 2026-08-30) -- this page keeps only the event-type filter, which is
 * a property of the feed itself. */
function LedgerPanel() {
  const [eventType, setEventType] = useState('');
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  const fetchEntries = useCallback(async () => {
    try {
      const data = await getLedgerEntries({ event_type: eventType || undefined });
      setEntries(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [eventType]);

  useEffect(() => {
    fetchEntries();
    const intervalId = setInterval(fetchEntries, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchEntries]);

  return (
    <>
      <div className="ledger-chart-row">
        <div className="ledger-chart-card">
          <h3>Staff Role</h3>
          <LedgerRoleBarChart entries={entries} />
        </div>
        <div className="ledger-chart-card">
          <h3>Event breakdown</h3>
          <LedgerDonutChart3D entries={entries} />
        </div>
      </div>

      <section className="panel-card">
        <h2>Live feed</h2>
        <form className="ledger-filters" onSubmit={(e) => e.preventDefault()}>
          <select className="form-input" value={eventType} onChange={(e) => setEventType(e.target.value)}>
            {EVENT_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </form>

        <LedgerEntriesFeed entries={entries} error={error} />
      </section>
    </>
  );
}

/** Read-only staff details, per the user -- once a specific staff member is
 * selected on the Staff activity page, the left card switches from the
 * system-wide role breakdown to this. Only shows fields the search result
 * actually carries (StaffSummarySerializer) -- no new backend data needed. */
function StaffDetailsCard({ staff }) {
  return (
    <div>
      <p className="meta-line">{staff.full_name}</p>
      <p className="meta-line">{staff.staff_id} · {formatRole(staff.role)}</p>
      {staff.ward && <p className="meta-line">Ward: {staff.ward}</p>}
      {(staff.on_duty !== undefined || staff.on_call !== undefined) && (
        <p className="meta-line">
          {staff.on_duty ? 'On duty' : 'Off duty'}
          {staff.on_call ? ' · On call' : ''}
        </p>
      )}
    </div>
  );
}

/** How many distinct staff members have a Ledger entry against this patient
 * -- computed client-side from the entries already fetched for the selected
 * patient, no new backend endpoint needed. Per the user, this is the Patient
 * activity page's left card once a patient is selected. */
function StaffAccessCountCard({ entries }) {
  const count = new Set(entries.map((e) => e.staff_id)).size;
  return (
    <div className="big-stat">
      <div className="big-stat-number">{count}</div>
      <div className="big-stat-label">staff member{count === 1 ? '' : 's'} accessed this patient</div>
    </div>
  );
}

/** Shared shape for the Staff/Patient activity pages: two summary cards on
 * top (added 2026-08-31, per the user -- same two cards the Ledger page
 * itself has, system-wide, until something's selected, then both switch to
 * that entity's own numbers), then search, pick a result, see their
 * filtered Ledger history below. Deliberately search-only, not a role/ward
 * category-tile breakdown (per the user) -- this is a lookup tool, not a
 * management screen. `search(query)` resolves to a result list; `resultKey`/
 * `renderResult`/`describeSelected` customize per-entity display;
 * `buildFilter(selected)` produces the getLedgerEntries() filter object;
 * `cardOne` customizes the left card once something's selected. */
function ActivityLookupPanel({ label, search, resultKey, renderResult, describeSelected, buildFilter, cardOne }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  const runSearch = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      setResults(await search(query));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const fetchEntries = useCallback(async () => {
    try {
      setEntries(await getLedgerEntries(selected ? buildFilter(selected) : {}));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [selected, buildFilter]);

  useEffect(() => {
    fetchEntries();
    const intervalId = setInterval(fetchEntries, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchEntries]);

  return (
    <div>
      <div className="ledger-chart-row">
        <div className="ledger-chart-card">
          <h3>{selected ? cardOne.selectedTitle : 'Staff Role'}</h3>
          {selected ? cardOne.renderSelected(selected, entries) : <LedgerRoleBarChart entries={entries} />}
        </div>
        <div className="ledger-chart-card">
          <h3>Event breakdown</h3>
          {selected ? <EventTypeBarChart entries={entries} /> : <LedgerDonutChart3D entries={entries} />}
        </div>
      </div>

      {selected ? (
        <div>
          <button type="button" className="back-link" onClick={() => setSelected(null)}>
            ← Back to search
          </button>
          <section className="panel-card">
            <h2>{describeSelected(selected)}</h2>
            <LedgerEntriesFeed entries={entries} error={error} />
          </section>
        </div>
      ) : (
        <div>
          <div className="search-row">
            <form className="search-bar" onSubmit={runSearch} role="search">
              <SearchIcon />
              <input placeholder={label} value={query} onChange={(e) => setQuery(e.target.value)} />
            </form>
          </div>

          {error && <p role="alert" className="dev-error">{error}</p>}

          {results.map((r) => (
            <div className="card-row" key={r[resultKey]}>
              {renderResult(r)}
              <div className="card-row-actions">
                <button type="button" className="btn-secondary" onClick={() => setSelected(r)}>
                  View activity
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StaffActivityPanel() {
  return (
    <ActivityLookupPanel
      label="Staff ID or name"
      search={(q) => searchStaff(q)}
      resultKey="id"
      renderResult={(s) => (
        <div className="card-row-main">
          <div className="name-line">{s.full_name}</div>
          <div className="meta-line">{s.staff_id} · {formatRole(s.role)}</div>
        </div>
      )}
      describeSelected={(s) => `${s.full_name} (${s.staff_id})`}
      buildFilter={(s) => ({ staff_id: s.staff_id })}
      cardOne={{
        selectedTitle: 'Staff Details',
        renderSelected: (s) => <StaffDetailsCard staff={s} />,
      }}
    />
  );
}

function PatientActivityPanel() {
  return (
    <ActivityLookupPanel
      label="Hospital number or name"
      search={(q) => searchPatients(q)}
      resultKey="id"
      renderResult={(p) => (
        <div className="card-row-main">
          <div className="name-line">{p.full_name}</div>
          <div className="meta-line">{p.hospital_number}</div>
        </div>
      )}
      describeSelected={(p) => `${p.full_name} (${p.hospital_number})`}
      buildFilter={(p) => ({ patient_hospital_number: p.hospital_number })}
      cardOne={{
        selectedTitle: 'Staff Access',
        renderSelected: (_p, entries) => <StaffAccessCountCard entries={entries} />,
      }}
    />
  );
}

function wardLabel(value) {
  return WARDS.find((w) => w.value === value)?.label || value;
}

/** Big total + label:value breakdown rows -- used for the Admins page's two
 * summary cards (added 2026-08-31, per the user). Reuses the exact summary
 * data the Admin dashboard's own Overview page already shows
 * (getPatientSummary()/getStaffSummary()) since admin accounts don't
 * generate scoring-pipeline Ledger events for a role/event-type breakdown to
 * mean anything here -- see CLAUDE.md's Security Dashboard section. */
function SummaryCard({ total, totalLabel, breakdown }) {
  return (
    <div>
      <div className="big-stat">
        <div className="big-stat-number">{total}</div>
        <div className="big-stat-label">{totalLabel}</div>
      </div>
      <div className="ledger-chart-legend">
        {breakdown.map(([label, value]) => (
          <span className="ledger-chart-legend-item" key={label}>
            {label}: {value}
          </span>
        ))}
      </div>
    </div>
  );
}

const NEW_ADMIN_INITIAL = { username: '', password: '', staff_id: '', full_name: '' };

/** Admins page: the only place an admin account can be created (added
 * 2026-08-30, per the user) -- Admin dashboard's own "Add Staff" no longer
 * offers the admin role, so this is the sole path. Admin accounts are shared
 * (no ward/on-duty/on-call), so the form only asks for login + identity.
 * Gained two summary cards at the top 2026-08-31, per the user -- see
 * SummaryCard above. */
function AdminsPanel() {
  const [createOpen, setCreateOpen] = useState(false);
  const [newAdmin, setNewAdmin] = useState(NEW_ADMIN_INITIAL);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [patientSummary, setPatientSummary] = useState(null);
  const [staffSummary, setStaffSummary] = useState(null);

  useEffect(() => {
    getPatientSummary().then(setPatientSummary).catch((err) => setError(errorMessage(err)));
    getStaffSummary().then(setStaffSummary).catch((err) => setError(errorMessage(err)));
  }, []);

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
      <div className="ledger-chart-row">
        <div className="ledger-chart-card">
          <h3>Patients</h3>
          {patientSummary && (
            <SummaryCard
              total={patientSummary.total}
              totalLabel="total patients"
              breakdown={Object.entries(patientSummary.by_ward).map(
                ([ward, count]) => [ward === 'unassigned' ? 'Unassigned' : wardLabel(ward), count]
              )}
            />
          )}
        </div>
        <div className="ledger-chart-card">
          <h3>Staff</h3>
          {staffSummary && (
            <SummaryCard
              total={staffSummary.total}
              totalLabel="total staff"
              breakdown={[
                ['On duty', staffSummary.on_duty],
                ['On call', staffSummary.on_call],
                ...Object.entries(staffSummary.by_role)
                  .filter(([role]) => role !== 'admin' && role !== 'security_officer')
                  .map(([role, count]) => [formatRole(role), count]),
              ]}
            />
          )}
        </div>
      </div>

      {error && <p role="alert" className="dev-error">{error}</p>}

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

const PAGE_TITLES = {
  ledger: 'Security Ledger',
  staff: 'Staff Activity',
  patients: 'Patient Activity',
  admins: 'Admins',
};

/** CLAUDE.md's Security Dashboard: the Ledger live feed (its documented core
 * responsibility), staff/patient activity lookup (added 2026-08-30, split out
 * of the live feed's old inline filters), plus sole ownership of admin-account
 * creation (Admin dashboard's own staff creation excludes the admin role). */
function SecurityDashboard({ staff, onLogout }) {
  const [activePage, setActivePage] = useState('ledger');

  const navItems = [
    { key: 'ledger', label: 'Ledger', icon: <LedgerIcon /> },
    { key: 'staff', label: 'Staff', icon: <StaffIcon /> },
    { key: 'patients', label: 'Patients', icon: <PatientsIcon /> },
    { key: 'admins', label: 'Admins', icon: <StaffIcon /> },
  ];

  return (
    <DashboardShell
      navItems={navItems}
      activeItem={activePage}
      onNavChange={setActivePage}
      staff={staff}
      onLogout={onLogout}
      title={PAGE_TITLES[activePage]}
    >
      {activePage === 'ledger' && <LedgerPanel />}
      {activePage === 'staff' && <StaffActivityPanel />}
      {activePage === 'patients' && <PatientActivityPanel />}
      {activePage === 'admins' && <AdminsPanel />}
    </DashboardShell>
  );
}

export default SecurityDashboard;
