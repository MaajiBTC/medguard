// Mirrors backend staff/models.py's Ward TextChoices (shared by Staff.ward and
// Patient.ward) -- keep in sync by hand.
export const WARDS = [
  { value: 'general_male', label: 'General Male Ward' },
  { value: 'general_female', label: 'General Female Ward' },
  { value: 'surgical', label: 'Surgical Ward' },
  { value: 'emergency', label: 'Emergency Ward' },
];
