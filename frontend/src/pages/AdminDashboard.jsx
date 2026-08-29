import { useEffect, useState } from 'react';

import {
  createPatient,
  createPatientAssignment,
  deactivatePatientAssignment,
  getAllPatientCategoryRecords,
  getPatientAssignments,
  searchPatients,
  updatePatientCategory,
  updatePatientWard,
} from '../api/patients';
import {
  activateDisasterMode,
  deactivateDisasterMode,
  getDisasterModeStatus,
} from '../api/scoring';
import {
  createStaff,
  deactivateStaff,
  reactivateStaff,
  searchStaff,
  updateStaffDuty,
} from '../api/staff';
import Modal from '../components/Modal';
import DashboardShell, { PatientsIcon, SearchIcon, StaffIcon } from './DashboardShell';

const STAFF_ROLES = ['doctor', 'nurse', 'pharmacist', 'lab_technician', 'clerk', 'admin', 'security_officer'];
const ASSIGNMENT_ROLES = ['doctor', 'nurse'];

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function formatRole(role) {
  return role.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

function StaffPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [roleFilter, setRoleFilter] = useState('all');
  const [selected, setSelected] = useState(null);
  const [ward, setWard] = useState('');
  const [onDuty, setOnDuty] = useState(false);
  const [onCall, setOnCall] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);

  const [newStaff, setNewStaff] = useState({
    username: '', password: '', staff_id: '', full_name: '', role: 'doctor', ward: '', on_duty: false, on_call: false,
  });

  const runSearch = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      setResults(await searchStaff(query));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const select = (s) => {
    setSelected(s);
    setWard(s.ward || '');
    setOnDuty(s.on_duty);
    setOnCall(s.on_call);
    setNotice(null);
    setError(null);
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

  const handleCreate = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createStaff(newStaff);
      setNotice(`Staff account "${newStaff.staff_id}" created.`);
      setNewStaff({ username: '', password: '', staff_id: '', full_name: '', role: 'doctor', ward: '', on_duty: false, on_call: false });
      setCreateOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const filteredResults = roleFilter === 'all' ? results : results.filter((s) => s.role === roleFilter);

  return (
    <div>
      <div className="search-row">
        <form className="search-bar" onSubmit={runSearch} role="search">
          <SearchIcon />
          <input placeholder="Staff ID or name" value={query} onChange={(e) => setQuery(e.target.value)} />
        </form>
        <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>
          + Add Staff
        </button>
      </div>

      <div className="role-tabs">
        <button
          type="button"
          className={`role-tab${roleFilter === 'all' ? ' active' : ''}`}
          onClick={() => setRoleFilter('all')}
        >
          All
        </button>
        {STAFF_ROLES.map((r) => (
          <button
            key={r}
            type="button"
            className={`role-tab${roleFilter === r ? ' active' : ''}`}
            onClick={() => setRoleFilter(r)}
          >
            {formatRole(r)}
          </button>
        ))}
      </div>

      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      {filteredResults.map((s) => (
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
              {s.ward ? ` · ${s.ward}` : ''}
            </div>
          </div>
          <div className="card-row-actions">
            <button type="button" className="btn-secondary" onClick={() => select(s)}>
              Manage
            </button>
          </div>
        </div>
      ))}

      {selected && (
        <div className="panel-card">
          <h3>{selected.full_name} ({selected.staff_id})</h3>
          <label className="form-label">
            Ward
            <input className="form-input" value={ward} onChange={(e) => setWard(e.target.value)} />
          </label>
          <label className="form-checkbox">
            <input type="checkbox" checked={onDuty} onChange={(e) => setOnDuty(e.target.checked)} />
            On duty
          </label>
          <label className="form-checkbox">
            <input type="checkbox" checked={onCall} onChange={(e) => setOnCall(e.target.checked)} />
            On call
          </label>
          <div className="button-row">
            <button type="button" className="btn-primary" onClick={saveDuty}>Save ward/duty</button>
            <button type="button" className="btn-secondary" onClick={toggleActive}>
              {selected.account_active ? 'Deactivate account' : 'Reactivate account'}
            </button>
          </div>
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
                {STAFF_ROLES.map((r) => <option key={r} value={r}>{formatRole(r)}</option>)}
              </select>
            </label>
            <label className="form-label">
              Ward
              <input className="form-input" value={newStaff.ward} onChange={(e) => setNewStaff({ ...newStaff, ward: e.target.value })} />
            </label>
            <label className="form-checkbox">
              <input type="checkbox" checked={newStaff.on_duty} onChange={(e) => setNewStaff({ ...newStaff, on_duty: e.target.checked })} />
              On duty
            </label>
            <label className="form-checkbox">
              <input type="checkbox" checked={newStaff.on_call} onChange={(e) => setNewStaff({ ...newStaff, on_call: e.target.checked })} />
              On call
            </label>
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
  const [selected, setSelected] = useState(null);
  const [ward, setWard] = useState('');
  const [categoryRecords, setCategoryRecords] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [assignStaffId, setAssignStaffId] = useState('');
  const [assignRole, setAssignRole] = useState('doctor');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);

  const [newPatient, setNewPatient] = useState({ hospital_number: '', full_name: '', ward: '' });

  const runSearch = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      setResults(await searchPatients(query));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const select = async (p) => {
    setSelected(p);
    setWard(p.ward || '');
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
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveCategoryNotes = async (category, notes) => {
    setError(null);
    try {
      const updated = await updatePatientCategory(selected.id, category, { notes });
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

  const handleCreate = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createPatient(newPatient);
      setNotice(`Patient "${newPatient.hospital_number}" created.`);
      setNewPatient({ hospital_number: '', full_name: '', ward: '' });
      setCreateOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div>
      <div className="search-row">
        <form className="search-bar" onSubmit={runSearch} role="search">
          <SearchIcon />
          <input placeholder="Hospital number or name" value={query} onChange={(e) => setQuery(e.target.value)} />
        </form>
        <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>
          + Add Patient
        </button>
      </div>

      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

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
            <button type="button" className="btn-secondary" onClick={() => select(p)}>
              Manage
            </button>
          </div>
        </div>
      ))}

      {selected && (
        <div className="panel-card">
          <h3>{selected.full_name} ({selected.hospital_number})</h3>
          <label className="form-label">
            Ward
            <input className="form-input" value={ward} onChange={(e) => setWard(e.target.value)} />
          </label>
          <div className="button-row">
            <button type="button" className="btn-primary" onClick={saveWard}>Save ward</button>
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

          <h4>Categories</h4>
          {categoryRecords.map((r) => (
            <details key={r.category} className="detail-block">
              <summary>{r.category_name}</summary>
              <CategoryNotesEditor record={r} onSave={(notes) => saveCategoryNotes(r.category, notes)} />
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
              <input className="form-input" value={newPatient.ward} onChange={(e) => setNewPatient({ ...newPatient, ward: e.target.value })} />
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

function CategoryNotesEditor({ record, onSave }) {
  const [notes, setNotes] = useState(record.content?.notes || '');
  return (
    <div className="category-editor">
      <textarea className="form-input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button type="button" className="btn-secondary" onClick={() => onSave(notes)}>Save</button>
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

  if (!status) return null;

  return (
    <div className="panel-card disaster-panel">
      <h2>Disaster / Mass Casualty Mode</h2>
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

function AdminDashboard({ staff, onLogout }) {
  const [activePage, setActivePage] = useState('staff');

  const navItems = [
    { key: 'staff', label: 'Staff', icon: <StaffIcon /> },
    { key: 'patients', label: 'Patients', icon: <PatientsIcon /> },
  ];

  return (
    <DashboardShell
      navItems={navItems}
      activeItem={activePage}
      onNavChange={setActivePage}
      staff={staff}
      onLogout={onLogout}
      title={activePage === 'staff' ? 'Staff Management' : 'Patient Records'}
      subtitle={
        activePage === 'staff'
          ? 'Monitor and manage staff accounts across roles.'
          : 'Search, view, and manage patient records.'
      }
    >
      <DisasterModePanel />
      {activePage === 'staff' ? <StaffPanel /> : <PatientPanel />}
    </DashboardShell>
  );
}

export default AdminDashboard;
