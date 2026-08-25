import { request } from './client';

/** POST /api/captures/behavioral/events/ — append a batch of raw events to the
 * caller's own session capture. */
function postBehavioralEvents(batch) {
  return request('/captures/behavioral/events/', { method: 'POST', body: batch });
}

/** GET /api/captures/behavioral/ — debug: raw BehavioralCapture for the caller's
 * own session. */
function getBehavioralCapture() {
  return request('/captures/behavioral/');
}

/** POST /api/captures/contextual/target-patient/ — {patient_id} -> factual
 * assignment status, updates and returns the ContextualCapture. */
function setTargetPatient(patientId) {
  return request('/captures/contextual/target-patient/', {
    method: 'POST',
    body: { patient_id: patientId },
  });
}

/** GET /api/captures/contextual/ — debug: flattened ContextualCapture for the
 * caller's own session. */
function getContextualCapture() {
  return request('/captures/contextual/');
}

export { postBehavioralEvents, getBehavioralCapture, setTargetPatient, getContextualCapture };
