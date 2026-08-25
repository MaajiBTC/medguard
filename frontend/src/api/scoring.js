import { request } from './client';

/** POST /api/scoring/decide/ — {patient_id} -> the computed AccessDecision.
 * Requires setTargetPatient(patientId) (see api/captures.js) to have been called
 * first for this same patient. */
function decide(patientId) {
  return request('/scoring/decide/', { method: 'POST', body: { patient_id: patientId } });
}

/** GET /api/scoring/patients/<id>/records/ — the caller's own most recent decision's
 * granted categories, content included. Requires decide(patientId) to have been
 * called first; throws (403) if the latest decision was ACCESS_DENIED. */
function getPatientRecords(patientId) {
  return request(`/scoring/patients/${patientId}/records/`);
}

export { decide, getPatientRecords };
