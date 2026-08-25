import { useState } from 'react';

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
  createStaff,
  deactivateStaff,
  reactivateStaff,
  searchStaff,
  updateStaffDuty,
} from '../api/staff';

const STAFF_ROLES = ['doctor', 'nurse', 'pharmacist', 'lab_technician', 'clerk', 'admin', 'security_officer'];
const ASSIGNMENT_ROLES = ['doctor', 'nurse'];

function errorMessage(err) {
  return (err.data && (err.data.detail || JSON.stringify(err.data))) || err.message;
}

function StaffPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [ward, setWard] = useState('');
  const [onDuty, setOnDuty] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const [newStaff, setNewStaff] = useState({
    username: '', password: '', staff_id: '', full_name: '', role: 'doctor', ward: '', on_duty: false,
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
    setNotice(null);
    setError(null);
  };

  const saveDuty = async () => {
    setError(null);
    try {
      const updated = await updateStaffDuty(selected.id, { ward, on_duty: onDuty });
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
      setNewStaff({ username: '', password: '', staff_id: '', full_name: '', role: 'doctor', ward: '', on_duty: false });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="admin-panel">
      <h2>Staff</h2>
      <form className="search-form" onSubmit={runSearch}>
        <input placeholder="Staff ID or name" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <ul className="result-list">
        {results.map((s) => (
          <li key={s.id}>
            <button type="button" onClick={() => select(s)}>
              {s.full_name} ({s.staff_id}, {s.role}) {s.account_active ? '' : '— deactivated'}
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="edit-panel">
          <h3>{selected.full_name} ({selected.staff_id})</h3>
          <label>
            Ward
            <input value={ward} onChange={(e) => setWard(e.target.value)} />
          </label>
          <label>
            <input type="checkbox" checked={onDuty} onChange={(e) => setOnDuty(e.target.checked)} />
            On duty
          </label>
          <div className="button-row">
            <button type="button" onClick={saveDuty}>Save ward/duty</button>
            <button type="button" onClick={toggleActive}>
              {selected.account_active ? 'Deactivate account' : 'Reactivate account'}
            </button>
          </div>
        </div>
      )}

      <h3>Create staff account</h3>
      <form className="create-form" onSubmit={handleCreate}>
        <label>
          Username
          <input value={newStaff.username} onChange={(e) => setNewStaff({ ...newStaff, username: e.target.value })} required />
        </label>
        <label>
          Password
          <input type="password" value={newStaff.password} onChange={(e) => setNewStaff({ ...newStaff, password: e.target.value })} required minLength={8} />
        </label>
        <label>
          Staff ID
          <input value={newStaff.staff_id} onChange={(e) => setNewStaff({ ...newStaff, staff_id: e.target.value })} required />
        </label>
        <label>
          Full name
          <input value={newStaff.full_name} onChange={(e) => setNewStaff({ ...newStaff, full_name: e.target.value })} required />
        </label>
        <label>
          Role
          <select value={newStaff.role} onChange={(e) => setNewStaff({ ...newStaff, role: e.target.value })}>
            {STAFF_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label>
          Ward
          <input value={newStaff.ward} onChange={(e) => setNewStaff({ ...newStaff, ward: e.target.value })} />
        </label>
        <label>
          <input type="checkbox" checked={newStaff.on_duty} onChange={(e) => setNewStaff({ ...newStaff, on_duty: e.target.checked })} />
          On duty
        </label>
        <button type="submit">Create staff account</button>
      </form>
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
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="admin-panel">
      <h2>Patients</h2>
      <form className="search-form" onSubmit={runSearch}>
        <input placeholder="Hospital number or name" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {error && <p role="alert" className="dev-error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <ul className="result-list">
        {results.map((p) => (
          <li key={p.id}>
            <button type="button" onClick={() => select(p)}>
              {p.full_name} ({p.hospital_number}) {p.ward ? `— ${p.ward}` : ''}
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="edit-panel">
          <h3>{selected.full_name} ({selected.hospital_number})</h3>
          <label>
            Ward
            <input value={ward} onChange={(e) => setWard(e.target.value)} />
          </label>
          <button type="button" onClick={saveWard}>Save ward</button>

          <h4>Assignments</h4>
          <ul className="result-list">
            {assignments.map((a) => (
              <li key={a.id}>
                {a.staff_full_name} ({a.staff_id}) — {a.role_in_assignment}{' '}
                <button type="button" onClick={() => removeAssignment(a.id)}>Unassign</button>
              </li>
            ))}
          </ul>
          <form className="assign-form" onSubmit={addAssignment}>
            <input
              placeholder="Staff ID"
              value={assignStaffId}
              onChange={(e) => setAssignStaffId(e.target.value)}
              required
            />
            <select value={assignRole} onChange={(e) => setAssignRole(e.target.value)}>
              {ASSIGNMENT_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button type="submit">Assign</button>
          </form>

          <h4>Categories</h4>
          {categoryRecords.map((r) => (
            <details key={r.category}>
              <summary>{r.category_name}</summary>
              <CategoryNotesEditor record={r} onSave={(notes) => saveCategoryNotes(r.category, notes)} />
            </details>
          ))}
        </div>
      )}

      <h3>Add patient</h3>
      <form className="create-form" onSubmit={handleCreate}>
        <label>
          Hospital number
          <input value={newPatient.hospital_number} onChange={(e) => setNewPatient({ ...newPatient, hospital_number: e.target.value })} required />
        </label>
        <label>
          Full name
          <input value={newPatient.full_name} onChange={(e) => setNewPatient({ ...newPatient, full_name: e.target.value })} required />
        </label>
        <label>
          Ward
          <input value={newPatient.ward} onChange={(e) => setNewPatient({ ...newPatient, ward: e.target.value })} />
        </label>
        <button type="submit">Add patient</button>
      </form>
    </div>
  );
}

function CategoryNotesEditor({ record, onSave }) {
  const [notes, setNotes] = useState(record.content?.notes || '');
  return (
    <div className="category-editor">
      <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button type="button" onClick={() => onSave(notes)}>Save</button>
    </div>
  );
}

function AdminDashboard({ staff, onLogout }) {
  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <h1>MedGuard admin</h1>
          {staff && <p><strong>{staff.full_name}</strong> ({staff.staff_id})</p>}
        </div>
        <button type="button" onClick={onLogout}>Log out</button>
      </header>

      <div className="admin-grid">
        <StaffPanel />
        <PatientPanel />
      </div>
    </div>
  );
}

export default AdminDashboard;
