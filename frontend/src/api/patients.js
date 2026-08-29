import { request } from './client';

/** GET /api/patients/?q=...&ward=... — any authenticated staff, matches
 * hospital_number or full_name, optionally filtered to an exact ward (Admin
 * dashboard's ward-category drill-down). */
function searchPatients(q, ward) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (ward) params.set('ward', ward);
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

export {
  searchPatients,
  getPatientSummary,
  getMyAssignedPatients,
  createPatient,
  updatePatientWard,
  getAllPatientCategoryRecords,
  updatePatientCategory,
  getPatientAssignments,
  createPatientAssignment,
  deactivatePatientAssignment,
};
