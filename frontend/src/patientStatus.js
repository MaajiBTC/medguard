// Mirrors backend patients/models.py's PatientStatus TextChoices -- keep in
// sync by hand, same convention as wards.js. 'unassigned' is not a backend
// value: it's the blank/not-yet-set bucket, exactly as wards.js's equivalent
// is handled in the summary endpoint.
//
// Colors are a distinct family from both WARD_CHART_COLORS and the 5 pinned
// Ledger severity hues, which mean something else entirely.
export const PATIENT_STATUS_OPTIONS = [
  { value: 'admitted', label: 'Admitted', color: '#2a9d5c' },
  { value: 'discharged', label: 'Discharged', color: '#9b7fd4' },
  { value: 'outpatient', label: 'Outpatient', color: '#e0a83e' },
  { value: 'unassigned', label: 'Unassigned', color: '#c9c3d8' },
];
