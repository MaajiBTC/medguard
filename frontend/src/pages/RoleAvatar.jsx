// One small flat-cartoon "mascot" avatar per role, hand-drawn as plain SVG
// shapes (no icon library, no downloaded/generated images -- per the user,
// 2026-08-31, after a stock-photo reference couldn't be reproduced due to
// copyright). Shown as the left-hand avatar on the Staff/Patients/Admins
// activity pages once a specific entity is selected. Each character shares
// the same face/head shapes; only hair, outfit color, and a small
// role-specific accessory differ.

function Head({ skin, hair }) {
  return (
    <>
      <circle cx="50" cy="42" r="22" fill={skin} />
      <ellipse cx="42" cy="35" rx="7" ry="5" fill="#ffffff" opacity="0.35" />
      <path
        d="M28 38 C27 18 73 18 72 38 C70 26 60 22 50 22 C40 22 30 26 28 38 Z"
        fill={hair}
      />
      <circle cx="42" cy="44" r="2.2" fill="#2a0f5c" />
      <circle cx="58" cy="44" r="2.2" fill="#2a0f5c" />
      <circle cx="40" cy="52" r="3.5" fill="#f28fa3" opacity="0.5" />
      <circle cx="60" cy="52" r="3.5" fill="#f28fa3" opacity="0.5" />
      <path d="M43 54 Q50 59 57 54" stroke="#8a4a2c" strokeWidth="1.6" fill="none" strokeLinecap="round" />
    </>
  );
}

function DoctorIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#e6e0fb" />
      <Head skin="#f0b98d" hair="#3b2b20" />
      <path d="M38 78 Q50 74 62 78 L62 70 Q50 66 38 70 Z" fill="#ffffff" />
      <path d="M45 72 L50 80 L55 72 L52 70 L48 70 Z" fill="#2f5fa8" />
      <circle cx="38" cy="86" r="4" fill="none" stroke="#8a97ab" strokeWidth="2.4" />
      <path d="M38 82 L38 76 Q38 72 44 72" fill="none" stroke="#8a97ab" strokeWidth="2.4" />
      <path d="M62 74 Q66 74 66 78" fill="none" stroke="#8a97ab" strokeWidth="2.4" />
    </svg>
  );
}

function NurseIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#ffd9e6" />
      <Head skin="#f0b98d" hair="#5a3a24" />
      <path d="M26 26 Q50 8 74 26 Q74 20 50 16 Q26 20 26 26 Z" fill="#ffffff" />
      <rect x="45" y="14" width="10" height="10" fill="#ffffff" />
      <rect x="47.5" y="11.5" width="5" height="15" fill="#e0435c" />
      <rect x="42.5" y="16.5" width="15" height="5" fill="#e0435c" />
    </svg>
  );
}

function PharmacistIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#dff5ea" />
      <Head skin="#e3a877" hair="#1f1a17" />
      <path d="M38 78 Q50 74 62 78 L62 70 Q50 66 38 70 Z" fill="#ffffff" />
      <g transform="translate(50 82) rotate(-40)">
        <rect x="-9" y="-3" width="18" height="6" rx="3" fill="#3fb3a3" />
        <line x1="-6" y1="0" x2="6" y2="0" stroke="#ffffff" strokeWidth="1.3" />
      </g>
    </svg>
  );
}

function LabTechnicianIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#ffffff" />
      <Head skin="#f0b98d" hair="#6b4a2f" />
      <rect x="33" y="41" width="14" height="9" rx="4" fill="none" stroke="#2a0f5c" strokeWidth="2" />
      <rect x="53" y="41" width="14" height="9" rx="4" fill="none" stroke="#2a0f5c" strokeWidth="2" />
      <line x1="47" y1="45.5" x2="53" y2="45.5" stroke="#2a0f5c" strokeWidth="2" />
      <path d="M38 78 Q50 74 62 78 L62 70 Q50 66 38 70 Z" fill="#ffffff" />
      <path d="M44 74 L38 80 L38 88 L44 84 Z" fill="#7ad1c4" />
      <path d="M56 74 L62 80 L62 88 L56 84 Z" fill="#7ad1c4" />
    </svg>
  );
}

function ClerkIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#e6e0fb" />
      <Head skin="#f0b98d" hair="#4a3223" />
      <path d="M40 78 L50 86 L60 78 L60 70 L50 74 L40 70 Z" fill="#6528d9" />
      <path d="M46 70 L50 82 L54 70 L52 68 L48 68 Z" fill="#ffffff" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#2a0f5c" />
      <Head skin="#e3a877" hair="#241a12" />
      <path d="M38 78 Q50 74 62 78 L62 70 Q50 66 38 70 Z" fill="#2a0f5c" />
      <path d="M50 72 L58 76 L58 84 Q50 90 42 84 L42 76 Z" fill="#c4b5fd" />
      <path d="M50 74 L55 77 L55 82 Q50 87 45 82 L45 77 Z" fill="#6528d9" />
    </svg>
  );
}

function PatientIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 78 L50 90 L65 78 L65 100 L35 100 Z" fill="#bfe3f0" />
      <Head skin="#f0b98d" hair="#7a5236" />
      <path d="M38 78 Q50 74 62 78 L62 70 Q50 66 38 70 Z" fill="#eef7fb" />
      <path d="M46 73 q4 3 8 0" stroke="#e0435c" strokeWidth="2" fill="none" strokeLinecap="round" />
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
