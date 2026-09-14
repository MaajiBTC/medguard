import { request } from './client';

/** POST /api/identity/enroll/ (multipart) — admin-only. Extracts real
 * minutiae from the image server-side and stores an encrypted template for
 * this patient, replacing any existing one. The raw image is never
 * persisted anywhere. */
function enrollFingerprint(patientId, file) {
  const formData = new FormData();
  formData.append('patient_id', patientId);
  formData.append('image', file);
  return request('/identity/enroll/', { method: 'POST', body: formData });
}

/** POST /api/identity/identify/ (multipart) — any clinical staff member,
 * deliberately no patient_id (that's the point — this identifies an
 * *unknown* patient for emergency lookup). Returns {matched: false, score}
 * or {matched: true, score, patient, summary} — summary is a MINIMAL
 * emergency subset (blood type, allergies, current meds, diagnoses, next of
 * kin), not the full record. */
function identifyFingerprint(file) {
  const formData = new FormData();
  formData.append('image', file);
  return request('/identity/identify/', { method: 'POST', body: formData });
}

export { enrollFingerprint, identifyFingerprint };
