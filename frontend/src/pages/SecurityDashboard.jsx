import { Fragment, useCallback, useEffect, useState } from 'react';

import { getLedgerEntries } from '../api/ledger';
import { searchPatients } from '../api/patients';
import { createStaff, getAdminActions, searchStaff } from '../api/staff';
import Modal from '../components/Modal';
import DashboardShell, { LedgerIcon, PatientsIcon, SearchIcon, StaffIcon } from './DashboardShell';
import { EventTypeBarChart, LedgerDonutChart3D, LedgerRoleBarChart, ROLES } from './LedgerCharts3D';
import RoleAvatar from './RoleAvatar';

const DUTY_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'on_duty', label: 'On duty' },
  { value: 'off_duty', label: 'Off duty' },
  { value: 'on_call', label: 'On call' },
];

/** Cross-references Ledger `entries` against each acting staff member's
 * CURRENT live on-duty/on-call status (not their status back when the
 * historical event happened -- per the user, 2026-08-31). `LedgerEntry` has
 * no duty field of its own, so this is client-side post-filtering rather
 * than a query param. Shared by `ActivityLookupPanel` and `AdminsPanel`. */
async function filterEntriesByDuty(entries, dutyFilter, roleFilter) {
  if (!dutyFilter) return entries;
  const staffList = await searchStaff('', roleFilter || undefined);
  const dutyById = Object.fromEntries(staffList.map((s) => [s.staff_id, s]));
  return entries.filter((e) => {
    const s = dutyById[e.staff_id];
    if (!s) return false;
    if (dutyFilter === 'on_duty') return s.on_duty;
    if (dutyFilter === 'off_duty') return !s.on_duty;
    if (dutyFilter === 'on_call') return s.on_call;
    return true;
  });
}

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
 * a property of the feed itself.
 *
 * Gained 3 "slicers" 2026-08-31, per the user -- role + event type (left
 * card) and a date range (right card) -- one shared filter set that narrows
 * `entries`, which already feeds both cards and the live-feed table below,
 * so no other wiring changes were needed. */
function LedgerPanel() {
  const [eventType, setEventType] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  const fetchEntries = useCallback(async () => {
    try {
      const data = await getLedgerEntries({
        event_type: eventType || undefined,
        staff_role: roleFilter || undefined,
        since: dateFrom ? `${dateFrom}T00:00:00` : undefined,
        until: dateTo ? `${dateTo}T23:59:59` : undefined,
      });
      setEntries(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [eventType, roleFilter, dateFrom, dateTo]);

  useEffect(() => {
    fetchEntries();
    const intervalId = setInterval(fetchEntries, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchEntries]);

  return (
    <>
      <div className="ledger-chart-row">
        <div className="ledger-chart-card">
          <div className="ledger-chart-card-header">
            <h3>Staff Role</h3>
            <div className="ledger-slicers">
              <select className="slicer-input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option value="">All roles</option>
                {ROLES.map((role) => (
                  <option key={role} value={role}>{formatRole(role)}</option>
                ))}
              </select>
              <select className="slicer-input" value={eventType} onChange={(e) => setEventType(e.target.value)}>
                {EVENT_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
          <LedgerRoleBarChart entries={entries} />
        </div>
        <div className="ledger-chart-card">
          <div className="ledger-chart-card-header">
            <h3>Event breakdown</h3>
            <div className="ledger-slicers">
              <input
                type="date"
                className="slicer-input"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                aria-label="From date"
              />
              <input
                type="date"
                className="slicer-input"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                aria-label="To date"
              />
            </div>
          </div>
          <LedgerDonutChart3D entries={entries} />
        </div>
      </div>

      <section className="panel-card">
        <h2>Live feed</h2>
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

/** Read-only patient details, per the user (2026-08-31) -- once a specific
 * patient is selected on the Patients activity page, the left card switches
 * from the system-wide role breakdown to this. Only shows fields the search
 * result actually carries (`PatientSummarySerializer`: hospital_number/
 * full_name/ward) -- phone number and address live in category 1 (Identity)
 * behind the full scoring/access-decision flow, not this lightweight lookup
 * endpoint, so they're deliberately not shown here. The distinct-staff-access
 * count (this card's old sole content, before the rename) is folded in as
 * an extra line, computed client-side from the entries already fetched for
 * this patient -- no new backend endpoint needed. */
function PatientDetailsCard({ patient, entries }) {
  const count = new Set(entries.map((e) => e.staff_id)).size;
  return (
    <div>
      <p className="meta-line">{patient.full_name}</p>
      <p className="meta-line">{patient.hospital_number}</p>
      {patient.ward && <p className="meta-line">Ward: {patient.ward}</p>}
      <p className="meta-line">{count} staff member{count === 1 ? '' : 's'} accessed this record</p>
    </div>
  );
}

/** Shared shape for the Staff/Patient activity pages: two summary cards on
 * top (added 2026-08-31, per the user -- same two cards the Ledger page
 * itself has, system-wide, until something's selected), then search, pick a
 * result, see their filtered Ledger history below. Deliberately search-only,
 * not a role/ward category-tile breakdown (per the user) -- this is a
 * lookup tool, not a management screen. `search(query)` resolves to a
 * result list; `resultKey`/`renderResult`/`describeSelected` customize
 * per-entity display; `buildFilter(selected)` produces the
 * getLedgerEntries() filter object; `cardOne` (`defaultTitle`, falls back
 * to "Staff Role"; `renderSelected(selected, entries)` returns just the
 * vertical detail fields, no avatar; optional `avatarRole(selected)`, falls
 * back to `selected.role`) customizes the left card.
 *
 * `activityFilters` (Staff/Patients pages) opts a page into a role select +
 * on-duty-status select on the left card and a date-range select on the
 * right, narrowing the `entries` feeding both cards. Amended 2026-08-31,
 * per the user: once something's selected the role/date slicers stop
 * applying (role is "of no importance" for one already-identified entity)
 * but the duty-status slicer keeps working in both states -- and the left
 * card's title disappears entirely, replaced by a `RoleAvatar` (~30% width)
 * beside `cardOne.renderSelected`'s vertical detail fields. On-duty status
 * has no field on `LedgerEntry` itself, so it's resolved by
 * `filterEntriesByDuty` cross-referencing each entry's `staff_id` against a
 * live `searchStaff()` lookup -- current status, not status at the time of
 * that historical event. */
function ActivityLookupPanel({ label, search, resultKey, renderResult, describeSelected, buildFilter, cardOne, activityFilters }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  const [roleFilter, setRoleFilter] = useState('');
  const [dutyFilter, setDutyFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

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
      const baseFilter = selected ? buildFilter(selected) : {};
      if (!activityFilters) {
        setEntries(await getLedgerEntries(baseFilter));
        setError(null);
        return;
      }
      const queryFilter = { ...baseFilter };
      if (!selected) {
        queryFilter.staff_role = roleFilter || undefined;
        queryFilter.since = dateFrom ? `${dateFrom}T00:00:00` : undefined;
        queryFilter.until = dateTo ? `${dateTo}T23:59:59` : undefined;
      }
      const data = await getLedgerEntries(queryFilter);
      setEntries(await filterEntriesByDuty(data, dutyFilter, selected ? undefined : roleFilter));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [selected, buildFilter, activityFilters, roleFilter, dutyFilter, dateFrom, dateTo]);

  useEffect(() => {
    fetchEntries();
    const intervalId = setInterval(fetchEntries, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchEntries]);

  return (
    <div>
      <div className="ledger-chart-row">
        <div className="ledger-chart-card">
          <div className="ledger-chart-card-header">
            {!selected && <h3>{cardOne.defaultTitle || 'Staff Role'}</h3>}
            {activityFilters && (
              <div className="ledger-slicers">
                {!selected && (
                  <select className="slicer-input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="Filter by role">
                    <option value="">All roles</option>
                    {ROLES.map((role) => (
                      <option key={role} value={role}>{formatRole(role)}</option>
                    ))}
                  </select>
                )}
                <select className="slicer-input" value={dutyFilter} onChange={(e) => setDutyFilter(e.target.value)} aria-label="Filter by duty status">
                  {DUTY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          {selected ? (
            <div className="entity-detail-row">
              <div className="entity-detail-avatar">
                <RoleAvatar role={cardOne.avatarRole ? cardOne.avatarRole(selected) : selected.role} />
              </div>
              <div className="entity-detail-info">{cardOne.renderSelected(selected, entries)}</div>
            </div>
          ) : (
            <LedgerRoleBarChart entries={entries} />
          )}
        </div>
        <div className="ledger-chart-card">
          <div className="ledger-chart-card-header">
            <h3>Event breakdown</h3>
            {activityFilters && !selected && (
              <div className="ledger-slicers">
                <input
                  type="date"
                  className="slicer-input"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  aria-label="From date"
                />
                <input
                  type="date"
                  className="slicer-input"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  aria-label="To date"
                />
              </div>
            )}
          </div>
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
        defaultTitle: 'Staff Activity',
        renderSelected: (s) => <StaffDetailsCard staff={s} />,
      }}
      activityFilters
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
        defaultTitle: 'Patient Record Activity',
        renderSelected: (p, entries) => <PatientDetailsCard patient={p} entries={entries} />,
        avatarRole: () => 'patient',
      }}
      activityFilters
    />
  );
}

/** Read-only admin details -- no ward/duty/on-call, admins are
 * Staff.NO_WARD_DUTY_ROLES (shared accounts), so there's nothing beyond
 * identity to show. */
function AdminDetailsCard({ admin }) {
  return (
    <div>
      <p className="meta-line">{admin.full_name}</p>
      <p className="meta-line">{admin.staff_id} · Admin</p>
    </div>
  );
}

const ADMIN_ACTION_LABEL = {
  staff_created: 'Created',
  staff_deactivated: 'Deactivated',
  staff_reactivated: 'Reactivated',
  staff_deleted: 'Deleted',
};

/** That admin's own logged actions (AdminActionLog, added 2026-08-31, per
 * the user) -- a simple list of discrete events (who/what/when), not count
 * data, so a list reads better here than a chart. */
function AdminActivityCard({ actions }) {
  if (actions === null) return <p className="meta-line">Loading…</p>;
  if (actions.length === 0) return <p className="meta-line">No actions logged yet.</p>;
  return (
    <div className="admin-action-list">
      {actions.map((a) => (
        <div className="admin-action-row" key={a.id}>
          <span className="admin-action-label">{ADMIN_ACTION_LABEL[a.action] || a.action}</span>
          <span className="admin-action-target">
            {a.target_full_name} ({a.target_staff_id}{a.target_role ? ` · ${formatRole(a.target_role)}` : ''})
          </span>
          <span className="admin-action-time">{new Date(a.occurred_at).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

const NEW_ADMIN_INITIAL = { username: '', password: '', staff_id: '', full_name: '' };

/** Admins page: system-wide bar+donut cards (same Staff Role/Event breakdown
 * cards Staff/Patients show, added 2026-08-31) until an admin is selected,
 * then those two cards switch to that admin's Details + Activity (added
 * 2026-08-31, replacing the previous Patients/Staff summary-only version --
 * there was no way to actually see existing admins before that). Reverted
 * back to the bar+donut default the same day, per the user, once they
 * clarified they wanted both: the same default look as Staff/Patients, and
 * still able to click into one admin. Also the only place an admin account
 * can be created (added 2026-08-30) -- Admin dashboard's own "Add Staff" no
 * longer offers the admin role, so this is the sole path. Not built on
 * ActivityLookupPanel above -- the selected-state data source (AdminActionLog
 * via getAdminActions) is different enough from Ledger entries that reusing
 * it would need more indirection than it'd save.
 *
 * Amended 2026-08-31 (same day): gained the role + on-duty-status slicers
 * on its unselected "Staff Role" card, matching Staff/Patients (this was
 * the one page that had been missing them). Once an admin is selected the
 * title disappears and the left card becomes a `RoleAvatar` (role="admin")
 * beside `AdminDetailsCard`'s vertical fields, same layout as the other two
 * pages -- but with no duty slicer in that state, unlike Staff/Patients:
 * admin accounts are `Staff.NO_WARD_DUTY_ROLES` (no on-duty/on-call concept
 * at all), and the right card here is `AdminActivityCard` (that admin's own
 * `AdminActionLog` entries), not Ledger data a duty slicer could narrow. */
function AdminsPanel() {
  const [createOpen, setCreateOpen] = useState(false);
  const [newAdmin, setNewAdmin] = useState(NEW_ADMIN_INITIAL);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [actions, setActions] = useState(null);
  const [entries, setEntries] = useState([]);

  const [roleFilter, setRoleFilter] = useState('');
  const [dutyFilter, setDutyFilter] = useState('');

  const runSearch = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      setResults(await searchStaff(query, 'admin'));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const fetchActions = useCallback(async () => {
    if (!selected) return;
    try {
      setActions(await getAdminActions(selected.staff_id));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [selected]);

  const fetchEntries = useCallback(async () => {
    if (selected) return;
    try {
      const data = await getLedgerEntries({ staff_role: roleFilter || undefined });
      setEntries(await filterEntriesByDuty(data, dutyFilter, roleFilter));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [selected, roleFilter, dutyFilter]);

  useEffect(() => {
    if (!selected) return undefined;
    setActions(null);
    fetchActions();
    const intervalId = setInterval(fetchActions, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [selected, fetchActions]);

  useEffect(() => {
    if (selected) return undefined;
    fetchEntries();
    const intervalId = setInterval(fetchEntries, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [selected, fetchEntries]);

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
          <div className="ledger-chart-card-header">
            {!selected && <h3>Staff Role</h3>}
            {!selected && (
              <div className="ledger-slicers">
                <select className="slicer-input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="Filter by role">
                  <option value="">All roles</option>
                  {ROLES.map((role) => (
                    <option key={role} value={role}>{formatRole(role)}</option>
                  ))}
                </select>
                <select className="slicer-input" value={dutyFilter} onChange={(e) => setDutyFilter(e.target.value)} aria-label="Filter by duty status">
                  {DUTY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          {selected ? (
            <div className="entity-detail-row">
              <div className="entity-detail-avatar">
                <RoleAvatar role="admin" />
              </div>
              <div className="entity-detail-info">
                <AdminDetailsCard admin={selected} />
              </div>
            </div>
          ) : (
            <LedgerRoleBarChart entries={entries} />
          )}
        </div>
        <div className="ledger-chart-card">
          <h3>{selected ? 'Activity' : 'Event breakdown'}</h3>
          {selected ? <AdminActivityCard actions={actions} /> : <LedgerDonutChart3D entries={entries} />}
        </div>
      </div>

      {selected ? (
        <button type="button" className="back-link" onClick={() => setSelected(null)}>
          ← Back to search
        </button>
      ) : (
        <div>
          <p className="meta-line">Security officers are the only role that can create admin accounts.</p>
          <div className="search-row">
            <form className="search-bar" onSubmit={runSearch} role="search">
              <SearchIcon />
              <input placeholder="Admin ID or name" value={query} onChange={(e) => setQuery(e.target.value)} />
            </form>
            <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>
              + Create Admin
            </button>
          </div>
        </div>
      )}

      {error && <p role="alert" className="dev-error">{error}</p>}

      {!selected && results.map((a) => (
        <div className="card-row" key={a.id}>
          <div className="card-row-main">
            <div className="name-line">{a.full_name}</div>
            <div className="meta-line">{a.staff_id} · Admin</div>
          </div>
          <div className="card-row-actions">
            <button type="button" className="btn-secondary" onClick={() => setSelected(a)}>
              View activity
            </button>
          </div>
        </div>
      ))}

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
