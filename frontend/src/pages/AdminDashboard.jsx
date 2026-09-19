import { useEffect, useState } from 'react';

import {
  createPatient,
  createPatientAssignment,
  deactivatePatientAssignment,
  getAllPatientCategoryRecords,
  getPatientAssignments,
  getPatientSummary,
  getStaffAssignments,
  searchPatients,
  updatePatientCategory,
  updatePatientStatus,
  updatePatientWard,
} from '../api/patients';
import { enrollFingerprint } from '../api/identity';
import {
  activateDisasterMode,
  deactivateDisasterMode,
  getDisasterModeStatus,
} from '../api/scoring';
import {
  createStaff,
  deactivateStaff,
  deleteStaff,
  unlockStaff,
  getStaffSummary,
  reactivateStaff,
  searchStaff,
  updateStaffDuty,
} from '../api/staff';
import Modal from '../components/Modal';
import { WARDS } from '../wards';
import DashboardShell, { DisasterIcon, OverviewIcon, PatientsIcon, SearchIcon, StaffIcon } from './DashboardShell';
import DonutChart2D from './DonutChart2D';
import { HorizontalBarChart, heatColor } from './LedgerCharts3D';

const STAFF_ROLES = ['doctor', 'nurse', 'pharmacist', 'lab_technician', 'clerk', 'admin', 'security_officer'];
// The Staff page's category browsing/search is scoped to clinical roles only --
// admin and security_officer accounts are shared system accounts an admin
// shouldn't be able to browse/manage from here (an admin manages only its own
// account, via the profile page); security officer accounts are likewise
// self-managed only. See ProfilePanel in DashboardShell.jsx.
const STAFF_BROWSE_ROLES = ['doctor', 'nurse', 'pharmacist', 'lab_technician', 'clerk'];
// Admins still cannot create other admin accounts -- that moved to the Security
// dashboard (only a Security Officer can create an admin account) -- but can
// still create a security_officer account (just can't browse/manage it after,
// per above).
const ADMIN_CREATABLE_ROLES = STAFF_ROLES.filter((r) => r !== 'admin');
// Shared accounts (admin/security officer) have no ward/on-duty/on-call concept.
const NO_WARD_DUTY_ROLES = new Set(['admin', 'security_officer']);

// Fixed distinct colors for the Patients-by-ward bar/donut (added
// 2026-09-18) -- a purple/plum family shade per ward plus a neutral gray
// for unassigned, deliberately not reusing the 5 exact severity hues
// (those are pinned to Ledger event types elsewhere and mean something
// different here).
const WARD_CHART_COLORS = [
  ...WARDS.map((w, i) => ({ ...w, color: ['#6528d9', '#c4b5fd', '#9b7fd4', '#2a0f5c'][i] })),
  { value: 'unassigned', label: 'Unassigned', color: '#c9c3d8' },
];

// Patient status options for the Patient panel's status chart/slicer (added
// 2026-09-19, per the user) -- a plain manually-set current-state label
// (see patients/models.py's PatientStatus), deliberately NOT an appointment/
// scheduling feature, which CLAUDE.md explicitly excludes. Own color family,
// distinct from both WARD_CHART_COLORS and the 5 pinned Ledger severity hues.
const PATIENT_STATUS_OPTIONS = [
  { value: 'admitted', label: 'Admitted', color: '#2a9d5c' },
  { value: 'discharged', label: 'Discharged', color: '#9b7fd4' },
  { value: 'outpatient', label: 'Outpatient', color: '#e0a83e' },
  { value: 'unassigned', label: 'Unassigned', color: '#c9c3d8' },
];

// Same 4 options SecurityDashboard.jsx's own duty-status slicer uses (added
// 2026-09-19, per the user) -- kept as its own local copy since that
// file's DUTY_OPTIONS isn't exported and the two slicers filter different
// things (Ledger entries there, the staff roster itself here).
const STAFF_DUTY_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'on_duty', label: 'On duty' },
  { value: 'off_duty', label: 'Off duty' },
  { value: 'on_call', label: 'On call' },
];
const ASSIGNMENT_ROLES = ['doctor', 'nurse'];

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function wardLabel(value) {
  return WARDS.find((w) => w.value === value)?.label || value;
}

function statusLabel(value) {
  return PATIENT_STATUS_OPTIONS.find((s) => s.value === value)?.label || value;
}

function OverviewPanel() {
  const [staffSummary, setStaffSummary] = useState(null);
  const [patientSummary, setPatientSummary] = useState(null);
  const [disasterStatus, setDisasterStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([getStaffSummary(), getPatientSummary(), getDisasterModeStatus()])
      .then(([staff, patients, disaster]) => {
        setStaffSummary(staff);
        setPatientSummary(patients);
        setDisasterStatus(disaster);
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  if (error) return <p role="alert" className="dev-error">{error}</p>;
  if (!staffSummary || !patientSummary || !disasterStatus) return <p>Loading overview…</p>;

  return (
    <div className="overview-grid">
      <div className="stat-card-group">
        <div className="stat-card-top">
          <span className="stat-label">Total Patients</span>
          <span className="stat-value">{patientSummary.total}</span>
        </div>
        <div className="stat-card-bottom">
          <div className="stat-sublist">
            {WARDS.map((w) => (
              <div className="stat-subrow" key={w.value}>
                <span>{w.label}</span>
                <span>{patientSummary.by_ward[w.value] ?? 0}</span>
              </div>
            ))}
            <div className="stat-subrow">
              <span>Unassigned</span>
              <span>{patientSummary.by_ward.unassigned ?? 0}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="stat-card-group">
        <div className="stat-card-top">
          <span className="stat-label">Total Staff</span>
          <span className="stat-value">{staffSummary.total}</span>
        </div>
        <div className="stat-card-bottom">
          <div className="stat-sublist">
            <div className="stat-subrow">
              <span>On duty</span>
              <span>{staffSummary.on_duty}</span>
            </div>
            <div className="stat-subrow">
              <span>On call</span>
              <span>{staffSummary.on_call}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="stat-card-group">
        <div className="stat-card-top">
          <span className="stat-label">Staff On Duty</span>
          <span className="stat-value">{staffSummary.on_duty}</span>
        </div>
        <div className="stat-card-bottom">
          <div className="stat-sublist">
            {Object.entries(staffSummary.on_duty_by_role).map(([role, count]) => (
              <div className="stat-subrow" key={role}>
                <span>{formatRole(role)}</span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="stat-card-group">
        <div className={`stat-card-top${disasterStatus.active ? ' stat-card-top-alert' : ''}`}>
          <span className="stat-label">Disaster Mode</span>
          <span className="stat-value">{disasterStatus.active ? 'ACTIVE' : 'Inactive'}</span>
        </div>
        <div className={`stat-card-bottom${disasterStatus.active ? ' stat-card-bottom-alert' : ''}`}>
          <div className="stat-sublist">
            {disasterStatus.last_event ? (
              <>
                <div className="stat-subrow">
                  <span>Last {disasterStatus.last_event.event_type}</span>
                  <span>{new Date(disasterStatus.last_event.occurred_at).toLocaleDateString()}</span>
                </div>
                <div className="stat-subrow">
                  <span>By</span>
                  <span>{disasterStatus.last_event.staff_full_name}</span>
                </div>
              </>
            ) : (
              <div className="stat-subrow">
                <span>No activity yet</span>
                <span></span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StaffPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selectedRole, setSelectedRole] = useState(null);
  const [roleCounts, setRoleCounts] = useState(null);
  const [selected, setSelected] = useState(null);
  const [ward, setWard] = useState('');
  const [onDuty, setOnDuty] = useState(false);
  const [onCall, setOnCall] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteConfirming, setDeleteConfirming] = useState(false);

  // "Staff by Role" chart slicers + the full roster list they filter,
  // shown below the search bar (added 2026-09-19, per the user) --
  // independent of the tile-drill-down `results` above so browsing here
  // never disturbs that flow. Mirrors SecurityDashboard.jsx's own role +
  // duty-status slicer pattern, but simpler: searchStaff() already returns
  // each row's own on_duty/on_call directly, no cross-referencing needed
  // the way filtering Ledger entries by duty does there.
  const [chartRoleFilter, setChartRoleFilter] = useState('');
  const [chartDutyFilter, setChartDutyFilter] = useState('');
  const [browseResults, setBrowseResults] = useState([]);
  const [browseLoading, setBrowseLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBrowseLoading(true);
    searchStaff('', chartRoleFilter || undefined)
      .then((data) => {
        if (cancelled) return;
        const filtered = data.filter((s) => {
          if (!STAFF_BROWSE_ROLES.includes(s.role)) return false;
          if (chartDutyFilter === 'on_duty') return s.on_duty;
          if (chartDutyFilter === 'off_duty') return !s.on_duty;
          if (chartDutyFilter === 'on_call') return s.on_call;
          return true;
        });
        setBrowseResults(filtered);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => !cancelled && setBrowseLoading(false));
    return () => {
      cancelled = true;
    };
  }, [chartRoleFilter, chartDutyFilter]);

  // Patient-assignment section (added 2026-09-03, per the user) -- only
  // applies to doctor/nurse (CLAUDE.md's Contextual module: patient
  // assignment isn't a concept for pharmacist/lab_technician/clerk).
  const [assignments, setAssignments] = useState([]);
  const [assignRole, setAssignRole] = useState('doctor');
  const [patientQuery, setPatientQuery] = useState('');
  const [patientResults, setPatientResults] = useState([]);

  const [newStaff, setNewStaff] = useState({
    username: '', password: '', staff_id: '', full_name: '', role: 'doctor', ward: '', on_duty: false, on_call: false,
  });

  const refreshCounts = () => {
    getStaffSummary().then(setRoleCounts).catch((err) => setError(errorMessage(err)));
  };

  useEffect(() => {
    refreshCounts();
  }, []);

  const runSearch = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      const data = await searchStaff(query, selectedRole || undefined);
      // Global search (no role selected) isn't scoped server-side, so filter out
      // admin/security_officer here too -- same reasoning as STAFF_BROWSE_ROLES.
      setResults(selectedRole ? data : data.filter((s) => STAFF_BROWSE_ROLES.includes(s.role)));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const selectRole = async (role) => {
    setSelectedRole(role);
    setQuery('');
    setSelected(null);
    setNotice(null);
    setError(null);
    try {
      setResults(await searchStaff('', role));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const backToCategories = () => {
    setSelectedRole(null);
    setQuery('');
    setResults([]);
    setSelected(null);
  };

  const select = async (s) => {
    setSelected(s);
    setWard(s.ward || '');
    setOnDuty(s.on_duty);
    setOnCall(s.on_call);
    setNotice(null);
    setError(null);
    setDeleteConfirming(false);
    setAssignRole(s.role === 'nurse' ? 'nurse' : 'doctor');
    setPatientQuery('');
    setPatientResults([]);
    if (s.role === 'doctor' || s.role === 'nurse') {
      try {
        setAssignments(await getStaffAssignments(s.id));
      } catch (err) {
        setError(errorMessage(err));
      }
    } else {
      setAssignments([]);
    }
  };

  const searchPatientsToAssign = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      setPatientResults(await searchPatients(patientQuery));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const assignPatient = async (patientId) => {
    setError(null);
    try {
      await createPatientAssignment(patientId, selected.staff_id, assignRole);
      setAssignments(await getStaffAssignments(selected.id));
      setPatientQuery('');
      setPatientResults([]);
      setNotice('Assignment added.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const removeAssignment = async (a) => {
    setError(null);
    try {
      await deactivatePatientAssignment(a.patient_id, a.id);
      setAssignments(await getStaffAssignments(selected.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveDuty = async () => {
    setError(null);
    try {
      const updated = await updateStaffDuty(selected.id, { ward, on_duty: onDuty, on_call: onCall });
      setSelected(updated);
      setNotice('Saved.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const toggleActive = async () => {
    setError(null);
    try {
      const updated = selected.account_active
        ? await deactivateStaff(selected.id)
        : await reactivateStaff(selected.id);
      setSelected(updated);
      setNotice(updated.account_active ? 'Account reactivated.' : 'Account deactivated — login now blocked.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleUnlock = async () => {
    setError(null);
    try {
      setSelected(await unlockStaff(selected.id));
      setNotice('Account unlocked — they can log in again now.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleCreate = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createStaff(newStaff);
      setNotice(`Staff account "${newStaff.staff_id}" created.`);
      setNewStaff({ username: '', password: '', staff_id: '', full_name: '', role: 'doctor', ward: '', on_duty: false, on_call: false });
      setCreateOpen(false);
      refreshCounts();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleDelete = async () => {
    setError(null);
    try {
      await deleteStaff(selected.id);
      setResults((prev) => prev.filter((s) => s.id !== selected.id));
      setSelected(null);
      setDeleteConfirming(false);
      setNotice(`"${selected.full_name}" was permanently deleted.`);
      refreshCounts();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const showingCategories = selectedRole === null && !query.trim();

  // Layout order (2026-09-18, per the user): in the default
  // (nothing-selected) view, chart -> role tiles -> search bar. Once a role
  // is picked or a search is active there's no chart to show first, so the
  // search bar moves back above the results list -- same searchRow/
  // feedback elements either way, just placed in a different position per
  // state rather than duplicated markup.
  const searchRow = (
    <div className="search-row">
      <form className="search-bar" onSubmit={runSearch} role="search">
        <SearchIcon />
        <input
          placeholder={selectedRole ? `Search within ${formatRole(selectedRole)}` : 'Staff ID or name'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>
      <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>
        + Add Staff
      </button>
    </div>
  );
  const feedback = (
    <>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
    </>
  );

  return (
    <div>
      {selectedRole !== null && (
        <button type="button" className="back-link" onClick={backToCategories}>
          ← Back to categories
        </button>
      )}

      {!showingCategories && searchRow}
      {feedback}

      {showingCategories ? (
        <>
          {roleCounts && (
            <div className="ledger-chart-row admin-summary-charts">
              <div className="ledger-chart-card">
                <div className="ledger-chart-card-header">
                  <h3>Staff by Role</h3>
                  <div className="ledger-slicers">
                    <select
                      className="slicer-input"
                      value={chartRoleFilter}
                      onChange={(e) => setChartRoleFilter(e.target.value)}
                      aria-label="Filter by role"
                    >
                      <option value="">All roles</option>
                      {STAFF_BROWSE_ROLES.map((r) => (
                        <option key={r} value={r}>{formatRole(r)}</option>
                      ))}
                    </select>
                    <select
                      className="slicer-input"
                      value={chartDutyFilter}
                      onChange={(e) => setChartDutyFilter(e.target.value)}
                      aria-label="Filter by duty status"
                    >
                      {STAFF_DUTY_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <HorizontalBarChart
                  rows={(() => {
                    // Driven by browseResults (already role/duty-filtered
                    // by the two slicers above), not the static summary --
                    // added 2026-09-19, per the user, so both charts in
                    // this card row move together with the slicers instead
                    // of only the roster list below reacting to them.
                    const counts = STAFF_BROWSE_ROLES.map(
                      (r) => browseResults.filter((s) => s.role === r).length
                    );
                    const max = Math.max(...counts, 1);
                    return STAFF_BROWSE_ROLES.map((r, i) => ({
                      key: r,
                      label: formatRole(r),
                      count: counts[i],
                      color: heatColor(counts[i] / max),
                    }));
                  })()}
                />
              </div>
              <div className="ledger-chart-card">
                <div className="ledger-chart-card-header">
                  <h3>Duty Status</h3>
                </div>
                <DonutChart2D
                  rows={(() => {
                    // Same browseResults source as the bar chart above --
                    // filtering to a specific duty status here will
                    // correctly collapse this donut toward that one
                    // segment, which is the expected effect of the slicer
                    // rather than a bug.
                    const onDuty = browseResults.filter((s) => s.on_duty).length;
                    const onCall = browseResults.filter((s) => s.on_call).length;
                    return [
                      { key: 'on_duty', label: 'On duty', count: onDuty, color: 'var(--color-notice)' },
                      { key: 'on_call', label: 'On call', count: onCall, color: 'var(--plum)' },
                      {
                        key: 'off_duty',
                        label: 'Off duty',
                        count: Math.max(0, browseResults.length - onDuty - onCall),
                        color: 'var(--lavender)',
                      },
                    ];
                  })()}
                />
              </div>
            </div>
          )}
          <div className="category-grid">
            {STAFF_BROWSE_ROLES.map((r) => (
              <button key={r} type="button" className="category-tile" onClick={() => selectRole(r)}>
                <span className="category-tile-label">{formatRole(r)}</span>
                <span className="category-tile-count">{roleCounts ? roleCounts.by_role[r] ?? 0 : '—'}</span>
              </button>
            ))}
          </div>
          {searchRow}

          {/* Full roster, filtered by the "Staff by Role" chart's own
              slicers above (added 2026-09-19, per the user) -- separate
              from the tile-drill-down `results` list, so it's always
              visible here regardless of whether a role tile is selected. */}
          {browseLoading && <p className="meta-line">Loading staff…</p>}
          {!browseLoading && browseResults.length === 0 && (
            <p className="meta-line">No staff match the current filters.</p>
          )}
          {browseResults.map((s) => (
            <div className="card-row" key={s.id}>
              <div className="card-row-main">
                <div className="name-line">
                  {s.full_name}
                  <span className={`badge ${s.account_active ? 'badge-active' : 'badge-inactive'}`}>
                    {s.account_active ? 'Active' : 'Deactivated'}
                  </span>
                </div>
                <div className="meta-line">
                  {formatRole(s.role)} · {s.staff_id}
                  {s.ward ? ` · ${wardLabel(s.ward)}` : ''}
                  {s.on_duty ? ' · On duty' : ''}
                  {s.on_call ? ' · On call' : ''}
                </div>
              </div>
              <div className="card-row-actions">
                <button type="button" className="btn-secondary" onClick={() => select(s)}>
                  Manage
                </button>
              </div>
            </div>
          ))}
        </>
      ) : (
        results.map((s) => (
          <div className="card-row" key={s.id}>
            <div className="card-row-main">
              <div className="name-line">
                {s.full_name}
                <span className={`badge ${s.account_active ? 'badge-active' : 'badge-inactive'}`}>
                  {s.account_active ? 'Active' : 'Deactivated'}
                </span>
              </div>
              <div className="meta-line">
                {formatRole(s.role)} · {s.staff_id}
                {s.ward ? ` · ${wardLabel(s.ward)}` : ''}
              </div>
            </div>
            <div className="card-row-actions">
              <button type="button" className="btn-secondary" onClick={() => select(s)}>
                Manage
              </button>
            </div>
          </div>
        ))
      )}

      {selected && (
        <div className="panel-card">
          <h3>
            {selected.full_name} ({selected.staff_id})
            {selected.is_locked_out && <span className="badge badge-open">Locked</span>}
          </h3>

          {/* Login lockout (added 2026-09-06). Step-up is self-service device
              biometric enrollment now (see the Profile page) -- nothing for
              an admin to set here. */}
          {selected.is_locked_out && (
            <p role="alert" className="access-reduced">
              This account is locked after too many failed login attempts. It unlocks on
              its own shortly, or you can clear it now.
            </p>
          )}

          {NO_WARD_DUTY_ROLES.has(selected.role) ? (
            <p className="meta-line">Shared account — no ward, on-duty, or on-call status.</p>
          ) : (
            <>
              <label className="form-label">
                Ward
                <select className="form-input" value={ward} onChange={(e) => setWard(e.target.value)}>
                  <option value="">— None —</option>
                  {WARDS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                </select>
              </label>
              <label className="form-checkbox">
                <input type="checkbox" checked={onDuty} onChange={(e) => setOnDuty(e.target.checked)} />
                On duty
              </label>
              <label className="form-checkbox">
                <input type="checkbox" checked={onCall} onChange={(e) => setOnCall(e.target.checked)} />
                On call
              </label>
            </>
          )}
          <div className="button-row">
            {!NO_WARD_DUTY_ROLES.has(selected.role) && (
              <button type="button" className="btn-primary" onClick={saveDuty}>Save ward/duty</button>
            )}
            <button type="button" className="btn-secondary" onClick={toggleActive}>
              {selected.account_active ? 'Deactivate account' : 'Reactivate account'}
            </button>
            {selected.is_locked_out && (
              <button type="button" className="btn-secondary" onClick={handleUnlock}>
                Unlock account
              </button>
            )}
            {!deleteConfirming && (
              <button type="button" className="btn-danger" onClick={() => setDeleteConfirming(true)}>
                Delete account
              </button>
            )}
          </div>

          {deleteConfirming && (
            <div className="danger-confirm">
              <p role="alert">
                This permanently deletes {selected.full_name}'s account and login — this cannot be
                undone. Their past Security Ledger history is kept (the Ledger doesn't reference
                staff accounts directly), but everything else about this account is gone for good.
              </p>
              <div className="button-row">
                <button type="button" className="btn-secondary" onClick={() => setDeleteConfirming(false)}>
                  Cancel
                </button>
                <button type="button" className="btn-danger" onClick={handleDelete}>
                  Yes, permanently delete
                </button>
              </div>
            </div>
          )}

          {(selected.role === 'doctor' || selected.role === 'nurse') && (
            <>
              <h4>Patient Assignments</h4>
              {assignments.length === 0 && <p className="meta-line">Not assigned to any patient.</p>}
              {assignments.map((a) => (
                <div className="detail-block" key={a.id}>
                  {a.full_name} ({a.hospital_number}) — {formatRole(a.role_in_assignment)}{' '}
                  <button type="button" className="btn-secondary" onClick={() => removeAssignment(a)}>Unassign</button>
                </div>
              ))}
              <form className="assign-form" onSubmit={searchPatientsToAssign}>
                <input
                  className="form-input"
                  placeholder="Hospital number or name"
                  value={patientQuery}
                  onChange={(e) => setPatientQuery(e.target.value)}
                />
                <select className="form-input" value={assignRole} onChange={(e) => setAssignRole(e.target.value)}>
                  <option value="doctor">Doctor</option>
                  <option value="nurse">Nurse</option>
                </select>
                <button type="submit" className="btn-secondary">Find Patient</button>
              </form>
              {patientResults.map((p) => (
                <div className="card-row" key={p.id}>
                  <div className="card-row-main">
                    <div className="name-line">{p.full_name}</div>
                    <div className="meta-line">
                      {p.hospital_number}
                      {p.ward ? ` · ${wardLabel(p.ward)}` : ''}
                    </div>
                  </div>
                  <div className="card-row-actions">
                    <button type="button" className="btn-secondary" onClick={() => assignPatient(p.id)}>Assign</button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {createOpen && (
        <Modal title="Add New Staff Member" onClose={() => setCreateOpen(false)}>
          <form onSubmit={handleCreate}>
            <label className="form-label">
              Username
              <input className="form-input" value={newStaff.username} onChange={(e) => setNewStaff({ ...newStaff, username: e.target.value })} required />
            </label>
            <label className="form-label">
              Password
              <input className="form-input" type="password" value={newStaff.password} onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })} required minLength={8} />
            </label>
            <label className="form-label">
              Staff ID
              <input className="form-input" value={newStaff.staff_id} onChange={(e) => setNewStaff({ ...newStaff, staff_id: e.target.value })} required />
            </label>
            <label className="form-label">
              Full name
              <input className="form-input" value={newStaff.full_name} onChange={(e) => setNewStaff({ ...newStaff, full_name: e.target.value })} required />
            </label>
            <label className="form-label">
              Role
              <select className="form-input" value={newStaff.role} onChange={(e) => setNewStaff({ ...newStaff, role: e.target.value })}>
                {ADMIN_CREATABLE_ROLES.map((r) => <option key={r} value={r}>{formatRole(r)}</option>)}
              </select>
            </label>
            {!NO_WARD_DUTY_ROLES.has(newStaff.role) && (
              <>
                <label className="form-label">
                  Ward
                  <select className="form-input" value={newStaff.ward} onChange={(e) => setNewStaff({ ...newStaff, ward: e.target.value })}>
                    <option value="">— None —</option>
                    {WARDS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                  </select>
                </label>
                <label className="form-checkbox">
                  <input type="checkbox" checked={newStaff.on_duty} onChange={(e) => setNewStaff({ ...newStaff, on_duty: e.target.checked })} />
                  On duty
                </label>
                <label className="form-checkbox">
                  <input type="checkbox" checked={newStaff.on_call} onChange={(e) => setNewStaff({ ...newStaff, on_call: e.target.checked })} />
                  On call
                </label>
              </>
            )}
            {error && <p role="alert" className="dev-error">{error}</p>}
            <div className="button-row">
              <button type="button" className="btn-secondary" onClick={() => setCreateOpen(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Save Staff</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function PatientPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selectedWard, setSelectedWard] = useState(null);
  const [wardCounts, setWardCounts] = useState(null);
  const [selected, setSelected] = useState(null);
  const [ward, setWard] = useState('');
  const [patientStatus, setPatientStatus] = useState('');
  const [categoryRecords, setCategoryRecords] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [assignStaffId, setAssignStaffId] = useState('');
  const [assignRole, setAssignRole] = useState('doctor');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [fingerprintBusy, setFingerprintBusy] = useState(false);

  const [newPatient, setNewPatient] = useState({ hospital_number: '', full_name: '', ward: WARDS[0].value });

  // "Patients by Ward" + "Patient Status" chart slicers + the full patient
  // list they filter, shown below the search bar -- mirrors StaffPanel's
  // own role/duty slicers + roster list (added 2026-09-19, per the user).
  // 'unassigned' isn't a real backend ward/status value (blank is), so it's
  // filtered client-side after fetching whatever server-side filter is a
  // concrete value; both dimensions are re-applied client-side regardless,
  // which keeps the two filters correct together in any combination.
  const [chartWardFilter, setChartWardFilter] = useState('');
  const [chartStatusFilter, setChartStatusFilter] = useState('');
  const [browseResults, setBrowseResults] = useState([]);
  const [browseLoading, setBrowseLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBrowseLoading(true);
    const wardParam = chartWardFilter && chartWardFilter !== 'unassigned' ? chartWardFilter : undefined;
    const statusParam = chartStatusFilter && chartStatusFilter !== 'unassigned' ? chartStatusFilter : undefined;
    searchPatients('', wardParam, statusParam)
      .then((data) => {
        if (cancelled) return;
        let filtered = data;
        if (chartWardFilter === 'unassigned') filtered = filtered.filter((p) => !p.ward);
        if (chartStatusFilter === 'unassigned') filtered = filtered.filter((p) => !p.status);
        setBrowseResults(filtered);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => !cancelled && setBrowseLoading(false));
    return () => {
      cancelled = true;
    };
  }, [chartWardFilter, chartStatusFilter]);

  const refreshCounts = () => {
    getPatientSummary().then(setWardCounts).catch((err) => setError(errorMessage(err)));
  };

  useEffect(() => {
    refreshCounts();
  }, []);

  const runSearch = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      if (selectedWard === 'unassigned') {
        const all = await searchPatients(query);
        setResults(all.filter((p) => !p.ward));
      } else {
        setResults(await searchPatients(query, selectedWard || undefined));
      }
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const selectWardCategory = async (wardValue) => {
    setSelectedWard(wardValue);
    setQuery('');
    setSelected(null);
    setNotice(null);
    setError(null);
    try {
      if (wardValue === 'unassigned') {
        const all = await searchPatients('');
        setResults(all.filter((p) => !p.ward));
      } else {
        setResults(await searchPatients('', wardValue));
      }
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const backToCategories = () => {
    setSelectedWard(null);
    setQuery('');
    setResults([]);
    setSelected(null);
  };

  const select = async (p) => {
    setSelected(p);
    setWard(p.ward || '');
    setPatientStatus(p.status || '');
    setNotice(null);
    setError(null);
    try {
      const [records, assigns] = await Promise.all([
        getAllPatientCategoryRecords(p.id),
        getPatientAssignments(p.id),
      ]);
      setCategoryRecords(records);
      setAssignments(assigns);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveWard = async () => {
    setError(null);
    try {
      const updated = await updatePatientWard(selected.id, ward);
      setSelected(updated);
      setNotice('Ward saved.');
      refreshCounts();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveStatus = async () => {
    setError(null);
    try {
      const updated = await updatePatientStatus(selected.id, patientStatus);
      setSelected(updated);
      setNotice('Status saved.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveCategoryContent = async (category, content) => {
    setError(null);
    try {
      const updated = await updatePatientCategory(selected.id, category, content);
      setCategoryRecords((prev) => prev.map((r) => (r.category === category ? updated : r)));
      setNotice('Category saved.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const addAssignment = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createPatientAssignment(selected.id, assignStaffId, assignRole);
      setAssignments(await getPatientAssignments(selected.id));
      setAssignStaffId('');
      setNotice('Assignment added.');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const removeAssignment = async (assignmentId) => {
    setError(null);
    try {
      await deactivatePatientAssignment(selected.id, assignmentId);
      setAssignments(await getPatientAssignments(selected.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  // MedGuard Identity (CLAUDE.md bonus, step 7, added 2026-09-14) --
  // enrolls/replaces this patient's fingerprint template. The raw image
  // never leaves this one request; only the derived, encrypted minutiae
  // template is stored server-side (identity.extraction/identity.crypto).
  const handleEnrollFingerprint = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file || !selected) return;
    setError(null);
    setNotice(null);
    setFingerprintBusy(true);
    try {
      const data = await enrollFingerprint(selected.id, file);
      setNotice(`Fingerprint enrolled (${data.minutiae_count} minutiae detected).`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setFingerprintBusy(false);
    }
  };

  const handleCreate = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createPatient(newPatient);
      setNotice(`Patient "${newPatient.hospital_number}" created.`);
      setNewPatient({ hospital_number: '', full_name: '', ward: WARDS[0].value });
      setCreateOpen(false);
      refreshCounts();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const showingCategories = selectedWard === null && !query.trim();

  // Layout order (2026-09-18, per the user) -- same reasoning as
  // StaffPanel above: chart -> ward tiles -> search bar by default, search
  // bar moves back to the top once a ward's picked or a search is active.
  const searchRow = (
    <div className="search-row">
      <form className="search-bar" onSubmit={runSearch} role="search">
        <SearchIcon />
        <input
          placeholder={selectedWard ? 'Search within this ward' : 'Hospital number or name'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>
      <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>
        + Add Patient
      </button>
    </div>
  );
  const feedback = (
    <>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
    </>
  );

  return (
    <div>
      {selectedWard !== null && (
        <button type="button" className="back-link" onClick={backToCategories}>
          ← Back to categories
        </button>
      )}

      {!showingCategories && searchRow}
      {feedback}

      {showingCategories ? (
        <>
          {wardCounts && (
            <div className="ledger-chart-row admin-summary-charts">
              <div className="ledger-chart-card">
                <div className="ledger-chart-card-header">
                  <h3>Patient Status</h3>
                  <div className="ledger-slicers">
                    <select
                      className="slicer-input"
                      value={chartStatusFilter}
                      onChange={(e) => setChartStatusFilter(e.target.value)}
                      aria-label="Filter by status"
                    >
                      <option value="">All statuses</option>
                      {PATIENT_STATUS_OPTIONS.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <HorizontalBarChart
                  rows={PATIENT_STATUS_OPTIONS.map((s) => ({
                    key: s.value,
                    label: s.label,
                    count:
                      s.value === 'unassigned'
                        ? browseResults.filter((p) => !p.status).length
                        : browseResults.filter((p) => p.status === s.value).length,
                    color: s.color,
                  }))}
                />
              </div>
              <div className="ledger-chart-card">
                <div className="ledger-chart-card-header">
                  <h3>Patients by Ward</h3>
                  <div className="ledger-slicers">
                    <select
                      className="slicer-input"
                      value={chartWardFilter}
                      onChange={(e) => setChartWardFilter(e.target.value)}
                      aria-label="Filter by ward"
                    >
                      <option value="">All wards</option>
                      {WARD_CHART_COLORS.map((w) => (
                        <option key={w.value} value={w.value}>{w.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <DonutChart2D
                  rows={WARD_CHART_COLORS.map((w) => ({
                    key: w.value,
                    label: w.label,
                    count:
                      w.value === 'unassigned'
                        ? browseResults.filter((p) => !p.ward).length
                        : browseResults.filter((p) => p.ward === w.value).length,
                    color: w.color,
                  }))}
                />
              </div>
            </div>
          )}
          <div className="category-grid">
            {WARDS.map((w) => (
              <button key={w.value} type="button" className="category-tile" onClick={() => selectWardCategory(w.value)}>
                <span className="category-tile-label">{w.label}</span>
                <span className="category-tile-count">{wardCounts ? wardCounts.by_ward[w.value] ?? 0 : '—'}</span>
              </button>
            ))}
            <button type="button" className="category-tile" onClick={() => selectWardCategory('unassigned')}>
              <span className="category-tile-label">Unassigned</span>
              <span className="category-tile-count">{wardCounts ? wardCounts.by_ward.unassigned ?? 0 : '—'}</span>
            </button>
          </div>
          {searchRow}
          {browseLoading && <p className="meta-line">Loading patients…</p>}
          {!browseLoading && browseResults.length === 0 && (
            <p className="meta-line">No patients match the current filter.</p>
          )}
          {browseResults.map((p) => (
            <div className="card-row" key={p.id}>
              <div className="card-row-main">
                <div className="name-line">{p.full_name}</div>
                <div className="meta-line">
                  {p.hospital_number}
                  {p.ward ? ` · ${wardLabel(p.ward)}` : ' · Unassigned'}
                  {p.status ? ` · ${statusLabel(p.status)}` : ''}
                </div>
              </div>
              <div className="card-row-actions">
                <button type="button" className="btn-secondary" onClick={() => select(p)}>
                  Manage
                </button>
              </div>
            </div>
          ))}
        </>
      ) : (
        results.map((p) => (
          <div className="card-row" key={p.id}>
            <div className="card-row-main">
              <div className="name-line">{p.full_name}</div>
              <div className="meta-line">
                {p.hospital_number}
                {p.ward ? ` · ${wardLabel(p.ward)}` : ' · Unassigned'}
              </div>
            </div>
            <div className="card-row-actions">
              <button type="button" className="btn-secondary" onClick={() => select(p)}>
                Manage
              </button>
            </div>
          </div>
        ))
      )}

      {selected && (
        <div className="panel-card">
          <h3>{selected.full_name} ({selected.hospital_number})</h3>
          <label className="form-label">
            Ward
            <select className="form-input" value={ward} onChange={(e) => setWard(e.target.value)}>
              <option value="">— Unassigned —</option>
              {WARDS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
            </select>
          </label>
          <div className="button-row">
            <button type="button" className="btn-primary" onClick={saveWard}>Save ward</button>
          </div>

          <label className="form-label">
            Status
            <select className="form-input" value={patientStatus} onChange={(e) => setPatientStatus(e.target.value)}>
              <option value="">— Not set —</option>
              {PATIENT_STATUS_OPTIONS.filter((s) => s.value !== 'unassigned').map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button type="button" className="btn-primary" onClick={saveStatus}>Save status</button>
          </div>

          <h4>Assignments</h4>
          {assignments.map((a) => (
            <div className="detail-block" key={a.id}>
              {a.staff_full_name} ({a.staff_id}) — {a.role_in_assignment}{' '}
              <button type="button" className="btn-secondary" onClick={() => removeAssignment(a.id)}>Unassign</button>
            </div>
          ))}
          <form className="assign-form" onSubmit={addAssignment}>
            <input
              className="form-input"
              placeholder="Staff ID"
              value={assignStaffId}
              onChange={(e) => setAssignStaffId(e.target.value)}
              required
            />
            <select className="form-input" value={assignRole} onChange={(e) => setAssignRole(e.target.value)}>
              {ASSIGNMENT_ROLES.map((r) => <option key={r} value={r}>{formatRole(r)}</option>)}
            </select>
            <button type="submit" className="btn-secondary">Assign</button>
          </form>

          <h4>Fingerprint (MedGuard Identity)</h4>
          <p className="meta-line">
            Used for emergency/offline patient lookup when a patient can't be
            identified another way. Re-enrolling replaces the existing
            template. The uploaded photo itself is never stored — only the
            derived, encrypted fingerprint template is.
          </p>
          <label className="btn-secondary file-label">
            {fingerprintBusy ? 'Enrolling…' : 'Enroll / replace fingerprint'}
            <input type="file" accept="image/*" onChange={handleEnrollFingerprint} disabled={fingerprintBusy} hidden />
          </label>

          <h4>Categories</h4>
          {categoryRecords.map((r) => (
            <details key={r.category} className="detail-block">
              <summary>{r.category_name}</summary>
              <CategoryFieldsEditor record={r} onSave={(content) => saveCategoryContent(r.category, content)} />
            </details>
          ))}
        </div>
      )}

      {createOpen && (
        <Modal title="Add New Patient" onClose={() => setCreateOpen(false)}>
          <form onSubmit={handleCreate}>
            <label className="form-label">
              Hospital number
              <input className="form-input" value={newPatient.hospital_number} onChange={(e) => setNewPatient({ ...newPatient, hospital_number: e.target.value })} required />
            </label>
            <label className="form-label">
              Full name
              <input className="form-input" value={newPatient.full_name} onChange={(e) => setNewPatient({ ...newPatient, full_name: e.target.value })} required />
            </label>
            <label className="form-label">
              Ward
              <select className="form-input" value={newPatient.ward} onChange={(e) => setNewPatient({ ...newPatient, ward: e.target.value })} required>
                {WARDS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
              </select>
            </label>
            {error && <p role="alert" className="dev-error">{error}</p>}
            <div className="button-row">
              <button type="button" className="btn-secondary" onClick={() => setCreateOpen(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Save Patient</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/** One labeled input per this category's structured field definitions
 * (record.field_defs, backend-owned -- see patients/category_fields.py),
 * replacing the old single free-text notes box (reversed 2026-09-03, per
 * the user). Local state is one object keyed by field name; Save posts the
 * whole object as the category's new content. */
function CategoryFieldsEditor({ record, onSave }) {
  const [values, setValues] = useState(() => {
    const initial = {};
    for (const field of record.field_defs) {
      initial[field.name] = record.content?.[field.name] || '';
    }
    return initial;
  });

  const setField = (name, value) => setValues((prev) => ({ ...prev, [name]: value }));

  return (
    <div className="category-editor">
      {record.field_defs.map((field) => (
        <label className="form-label" key={field.name}>
          {field.label}
          {field.type === 'textarea' ? (
            <textarea
              className="form-input"
              rows={3}
              value={values[field.name]}
              onChange={(e) => setField(field.name, e.target.value)}
            />
          ) : field.type === 'select' ? (
            <select
              className="form-input"
              value={values[field.name]}
              onChange={(e) => setField(field.name, e.target.value)}
            >
              <option value="">— None —</option>
              {field.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
            </select>
          ) : (
            <input
              className="form-input"
              type={field.type}
              value={values[field.name]}
              onChange={(e) => setField(field.name, e.target.value)}
            />
          )}
        </label>
      ))}
      <div className="button-row">
        <button type="button" className="btn-secondary" onClick={() => onSave(values)}>Save</button>
      </div>
    </div>
  );
}

function DisasterModePanel() {
  const [status, setStatus] = useState(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const refresh = () => {
    getDisasterModeStatus().then(setStatus).catch((err) => setError(errorMessage(err)));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleToggle = async (event) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (status.active) {
        await deactivateDisasterMode(reason);
        setNotice('Disaster Mode deactivated.');
      } else {
        await activateDisasterMode(reason);
        setNotice('Disaster Mode activated — the Doctor off-duty hard-deny rule and Break the Glass gate are suspended hospital-wide.');
      }
      setReason('');
      refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!status) {
    return error ? <p role="alert" className="dev-error">{error}</p> : <p>Loading…</p>;
  }

  return (
    <div className="panel-card disaster-panel">
      <p className={status.active ? 'access-override' : 'notice'}>
        {status.active ? 'ACTIVE' : 'Inactive'}
        {status.last_event &&
          ` — last ${status.last_event.event_type} by ${status.last_event.staff_full_name} (${status.last_event.staff_id})`}
      </p>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      <form onSubmit={handleToggle}>
        <label className="form-label" htmlFor="disaster-reason">
          Reason (required, min 10 characters)
          <textarea
            id="disaster-reason"
            className="form-input"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
            minLength={10}
          />
        </label>
        <div className="button-row">
          <button type="submit" className="btn-primary" disabled={submitting || reason.trim().length < 10}>
            {status.active ? 'Deactivate' : 'Activate'} Disaster Mode
          </button>
        </div>
      </form>
    </div>
  );
}

const PAGE_TITLES = {
  overview: 'Overview',
  staff: 'Staff',
  patients: 'Patients',
  disaster: 'Disaster Mode',
};

function AdminDashboard({ staff, onLogout }) {
  const [activePage, setActivePage] = useState('overview');

  const navItems = [
    { key: 'overview', label: 'Overview', icon: <OverviewIcon /> },
    { key: 'staff', label: 'Staff', icon: <StaffIcon /> },
    { key: 'patients', label: 'Patients', icon: <PatientsIcon /> },
    { key: 'disaster', label: 'Disaster Mode', icon: <DisasterIcon /> },
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
      {activePage === 'overview' && <OverviewPanel />}
      {activePage === 'staff' && <StaffPanel />}
      {activePage === 'patients' && <PatientPanel />}
      {activePage === 'disaster' && <DisasterModePanel />}
    </DashboardShell>
  );
}

export default AdminDashboard;
