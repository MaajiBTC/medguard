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

/** POST /api/scoring/emergency-override/ — {patient_id, reason_category, reason} ->
 * the granted AccessDecision (decision_type EMERGENCY_OVERRIDE, "Break the Glass").
 * Available to any logged-in clinical staff member, still capped at the caller's
 * role ceiling. Blocked (403) for a doctor/nurse who is off duty (and not on call)
 * with no connection (assignment/ward) to the patient — unless reasonCategory is
 * "cross_coverage" (self-attested bypass) or Disaster Mode is active. reason is
 * required (min 10 characters) since every call is permanently logged. */
function emergencyOverride(patientId, reasonCategory, reason) {
  return request('/scoring/emergency-override/', {
    method: 'POST',
    body: { patient_id: patientId, reason_category: reasonCategory, reason },
  });
}

/** GET /api/scoring/my-baseline/ — Offline Mode: the caller's own frozen
 * behavioral baseline snapshot + the current Disaster Mode flag, cached
 * client-side (see frontend/src/offline/) so decisions can still be
 * computed locally when the network drops mid-session. */
function getMyBaseline() {
  return request('/scoring/my-baseline/');
}

/** GET /api/scoring/disaster-mode/ — {active, last_event}. Admin-only. */
function getDisasterModeStatus() {
  return request('/scoring/disaster-mode/');
}

/** POST /api/scoring/disaster-mode/activate/ — {reason}. Admin-only; suspends the
 * Doctor off-duty+unconnected hard-deny rule and BTG's availability gate
 * hospital-wide until deactivated. */
function activateDisasterMode(reason) {
  return request('/scoring/disaster-mode/activate/', { method: 'POST', body: { reason } });
}

/** POST /api/scoring/disaster-mode/deactivate/ — {reason}. Admin-only. */
function deactivateDisasterMode(reason) {
  return request('/scoring/disaster-mode/deactivate/', { method: 'POST', body: { reason } });
}

/** POST /api/scoring/decisions/<id>/step-up/webauthn/options/ — first step of
 * verifying with THIS device's enrolled biometric (CLAUDE.md's 40–69% band).
 * 400s with {webauthn_available: false} if this device has no credential —
 * the caller should fall back to requestStepUpAssist() in that case. */
function getStepUpWebAuthnOptions(decisionId) {
  return request(`/scoring/decisions/${decisionId}/step-up/webauthn/options/`, { method: 'POST' });
}

/** POST /api/scoring/decisions/<id>/step-up/webauthn/verify/ — {credential}.
 * Second step: verifies @simplewebauthn/browser's startAuthentication()
 * response. Three failures spend the decision and the clinician has to call
 * decide() again. */
function verifyStepUpWebAuthn(decisionId, credential) {
  return request(`/scoring/decisions/${decisionId}/step-up/webauthn/verify/`, {
    method: 'POST',
    body: { credential },
  });
}

/** POST /api/scoring/decisions/<id>/step-up/assist/request/ — the fallback
 * for a device with no biometric, or before one's enrolled: asks any other
 * logged-in clinical colleague to vouch. */
function requestStepUpAssist(decisionId) {
  return request(`/scoring/decisions/${decisionId}/step-up/assist/request/`, { method: 'POST' });
}

/** GET /api/scoring/step-up/assist-requests/ — every *other* clinical
 * colleague's pending assist requests (never the caller's own), for the
 * approve/decline banner. */
function getStepUpAssistRequests() {
  return request('/scoring/step-up/assist-requests/');
}

/** POST /api/scoring/step-up/assist-requests/<id>/approve/ — vouches for a
 * colleague's reduced-access session, flipping its step_up_verified. */
function approveStepUpAssist(requestId) {
  return request(`/scoring/step-up/assist-requests/${requestId}/approve/`, { method: 'POST' });
}

/** POST /api/scoring/step-up/assist-requests/<id>/decline/ */
function declineStepUpAssist(requestId) {
  return request(`/scoring/step-up/assist-requests/${requestId}/decline/`, { method: 'POST' });
}

export {
  decide,
  getPatientRecords,
  getMyBaseline,
  emergencyOverride,
  getStepUpWebAuthnOptions,
  verifyStepUpWebAuthn,
  requestStepUpAssist,
  getStepUpAssistRequests,
  approveStepUpAssist,
  declineStepUpAssist,
  getDisasterModeStatus,
  activateDisasterMode,
  deactivateDisasterMode,
};
