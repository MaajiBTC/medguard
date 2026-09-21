import { request } from './client';

/** GET /api/patients/?q=...&ward=...&status=... — any authenticated staff,
 * matches hospital_number or full_name, optionally filtered to an exact
 * ward and/or status (Admin dashboard's ward/status chart slicers). */
function searchPatients(q, ward, patientStatus) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (ward) params.set('ward', ward);
  if (patientStatus) params.set('status', patientStatus);
  const qs = params.toString();
  return request(`/patients/${qs ? `?${qs}` : ''}`);
}

/** GET /api/patients/summary/ — admin-only real counts (total, by_ward) for the
 * Overview page and ward-category tiles. */
function getPatientSummary() {
  return request('/patients/summary/');
}

/** GET /api/patients/assigned-to-me/ — active PatientAssignment rows for the caller. */
function getMyAssignedPatients() {
  return request('/patients/assigned-to-me/');
}

/** POST /api/patients/create/ — admin-only. Also auto-creates the 13 empty category rows. */
function createPatient(data) {
  return request('/patients/create/', { method: 'POST', body: data });
}

/** PATCH /api/patients/<id>/ward/ — admin-only. */
function updatePatientWard(patientId, ward) {
  return request(`/patients/${patientId}/ward/`, { method: 'PATCH', body: { ward } });
}

/** PATCH /api/patients/<id>/status/ — admin-only. */
function updatePatientStatus(patientId, patientStatus) {
  return request(`/patients/${patientId}/status/`, { method: 'PATCH', body: { status: patientStatus } });
}

/** GET /api/patients/<id>/records/all/ — admin-only, unfiltered by any access decision. */
function getAllPatientCategoryRecords(patientId) {
  return request(`/patients/${patientId}/records/all/`);
}

/** PATCH /api/patients/<id>/records/<category>/ — admin-only. */
function updatePatientCategory(patientId, category, content) {
  return request(`/patients/${patientId}/records/${category}/`, { method: 'PATCH', body: { content } });
}

/** GET /api/patients/<id>/assignments/ — admin-only, active assignments. */
function getPatientAssignments(patientId) {
  return request(`/patients/${patientId}/assignments/`);
}

/** POST /api/patients/<id>/assignments/ — admin-only. {staff_id, role_in_assignment} */
function createPatientAssignment(patientId, staffId, roleInAssignment) {
  return request(`/patients/${patientId}/assignments/`, {
    method: 'POST',
    body: { staff_id: staffId, role_in_assignment: roleInAssignment },
  });
}

/** DELETE /api/patients/<id>/assignments/<assignmentId>/ — admin-only, soft-deactivate. */
function deactivatePatientAssignment(patientId, assignmentId) {
  return request(`/patients/${patientId}/assignments/${assignmentId}/`, { method: 'DELETE' });
}

/** GET /api/patients/staff/<staffPk>/assignments/ — admin-only, that staff
 * member's active assignments. The reverse lookup of getPatientAssignments —
 * lets the Admin dashboard's Staff panel assign a patient starting from the
 * staff side. */
function getStaffAssignments(staffPk) {
  return request(`/patients/staff/${staffPk}/assignments/`);
}

/** GET /api/patients/ward-emergency-summaries/ — Offline Mode's ward roster:
 * the minimal emergency summary for every patient on the caller's OWN ward
 * (plus anyone assigned to them). Doctors and nurses only; every other role
 * gets a 403, which the caller treats as "no roster", not an error. The ward
 * is derived server-side from the session — there is deliberately no ward
 * argument to pass. */
function getWardEmergencySummaries() {
  return request('/patients/ward-emergency-summaries/');
}

export {
  searchPatients,
  getPatientSummary,
  getMyAssignedPatients,
  createPatient,
  updatePatientWard,
  updatePatientStatus,
  getAllPatientCategoryRecords,
  updatePatientCategory,
  getPatientAssignments,
  createPatientAssignment,
  deactivatePatientAssignment,
  getStaffAssignments,
  getWardEmergencySummaries,
};
