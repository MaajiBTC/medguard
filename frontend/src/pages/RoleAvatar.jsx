// One small flat icon per role, drawn in the same hand-rolled style as
// DashboardShell's sidebar icons (no icon library, no downloaded images --
// per the user, 2026-08-31). Shown as the left-hand avatar on the Staff/
// Patients/Admins activity pages once a specific entity is selected.

function DoctorIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

function NurseIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21.2l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" />
    </svg>
  );
}

function PharmacistIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="9" width="18" height="6" rx="3" transform="rotate(-45 12 12)" />
      <line x1="8" y1="16" x2="16" y2="8" />
    </svg>
  );
}

function LabTechnicianIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M9 3h6" />
      <path d="M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" />
      <path d="M7 15h10" />
    </svg>
  );
}

function ClerkIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="16" y2="17" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function PatientIcon() {
  return (
    <svg width="60%" height="60%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

const ICONS = {
  doctor: DoctorIcon,
  nurse: NurseIcon,
  pharmacist: PharmacistIcon,
  lab_technician: LabTechnicianIcon,
  clerk: ClerkIcon,
  admin: AdminIcon,
  patient: PatientIcon,
};

/** Circular role-badge avatar -- `role` is a Staff.Role value, 'admin', or
 * 'patient' (the one generic icon used for every patient, per the user). */
function RoleAvatar({ role }) {
  const Icon = ICONS[role] || PatientIcon;
  return (
    <div className="role-avatar" aria-hidden="true">
      <Icon />
    </div>
  );
}

export default RoleAvatar;
