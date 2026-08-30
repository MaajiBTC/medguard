// Mirrors backend/staff/models.py's Staff.CLINICAL_ROLES -- the 5 roles that get
// patient-record category access via the Scoring Engine, and (added 2026-08-30)
// the one-device-per-account binding. Admin/security_officer are system roles and
// are deliberately excluded from both.
const CLINICAL_ROLES = new Set(['doctor', 'nurse', 'pharmacist', 'lab_technician', 'clerk']);

export { CLINICAL_ROLES };
