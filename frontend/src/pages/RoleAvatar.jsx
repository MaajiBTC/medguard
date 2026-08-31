// One small flat-cartoon "mascot" avatar per role, hand-drawn as plain SVG
// shapes (no icon library, no downloaded/generated images -- per the user,
// 2026-08-31, after two stock-photo references couldn't be reproduced due
// to copyright). Shown as the left-hand avatar on the Staff/Patients/Admins
// activity pages once a specific entity is selected. Each character shares
// the same face/head shapes; only hair, outfit color, and a small
// role-specific accessory differ. Face redrawn bigger/more expressive
// (larger eyes+highlight, visible eyebrows) the same day to get closer to
// the reference images' style within hand-drawn-SVG limits.

function Head({ skin, hair }) {
  return (
    <>
      <circle cx="50" cy="44" r="24" fill={skin} />
      <ellipse cx="41" cy="36" rx="8" ry="6" fill="#ffffff" opacity="0.35" />
      <path
        d="M25 40 C24 16 76 16 75 40 C75 26 64 20 50 20 C36 20 25 26 25 40 Z"
        fill={hair}
      />
      <path d="M35 40 Q39 36 44 40" stroke="#2a1810" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <path d="M56 40 Q61 36 65 40" stroke="#2a1810" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <ellipse cx="40" cy="46" rx="5" ry="6" fill="#ffffff" />
      <ellipse cx="60" cy="46" rx="5" ry="6" fill="#ffffff" />
      <circle cx="40.5" cy="47" r="3.4" fill="#4a2f18" />
      <circle cx="60.5" cy="47" r="3.4" fill="#4a2f18" />
      <circle cx="39.3" cy="45.6" r="1.1" fill="#ffffff" />
      <circle cx="59.3" cy="45.6" r="1.1" fill="#ffffff" />
      <circle cx="39" cy="55" r="3.8" fill="#f28fa3" opacity="0.45" />
      <circle cx="61" cy="55" r="3.8" fill="#f28fa3" opacity="0.45" />
      <path d="M42 58 Q50 63 58 58" stroke="#8a4a2c" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </>
  );
}

function DoctorIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#e6e0fb" />
      <Head skin="#f0b98d" hair="#3b2b20" />
      <path d="M36 80 Q50 75 64 80 L64 71 Q50 66 36 71 Z" fill="#ffffff" />
      <path d="M44 73 L50 82 L56 73 L53 71 L47 71 Z" fill="#2f5fa8" />
      <circle cx="36" cy="88" r="4.5" fill="none" stroke="#8a97ab" strokeWidth="2.6" />
      <path d="M36 83.5 L36 77 Q36 72 43 72" fill="none" stroke="#8a97ab" strokeWidth="2.6" />
      <path d="M64 75 Q68 75 68 79" fill="none" stroke="#8a97ab" strokeWidth="2.6" />
    </svg>
  );
}

function NurseIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#ffd9e6" />
      <path d="M63 32 C82 36 84 60 70 76 C78 62 76 44 62 36 Z" fill="#6a3d28" />
      <circle cx="66" cy="34" r="4" fill="#8a5a3a" />
      <Head skin="#f0b98d" hair="#6a3d28" />
      <path d="M36 80 Q50 75 64 80 L64 71 Q50 66 36 71 Z" fill="#ffffff" />
      <path d="M42 74 Q50 78 58 74" fill="none" stroke="#3fb3a3" strokeWidth="2.5" />
      <circle cx="36" cy="88" r="4.5" fill="none" stroke="#8a97ab" strokeWidth="2.6" />
      <path d="M36 83.5 L36 77 Q36 72 43 72" fill="none" stroke="#8a97ab" strokeWidth="2.6" />
      <path d="M64 75 Q68 75 68 79" fill="none" stroke="#8a97ab" strokeWidth="2.6" />
    </svg>
  );
}

function PharmacistIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#dff5ea" />
      <Head skin="#e3a877" hair="#1f1a17" />
      <path d="M36 80 Q50 75 64 80 L64 71 Q50 66 36 71 Z" fill="#ffffff" />
      <g transform="translate(50 84) rotate(-40)">
        <rect x="-9" y="-3" width="18" height="6" rx="3" fill="#3fb3a3" />
        <line x1="-6" y1="0" x2="6" y2="0" stroke="#ffffff" strokeWidth="1.3" />
      </g>
    </svg>
  );
}

function LabTechnicianIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#ffffff" />
      <Head skin="#f0b98d" hair="#6b4a2f" />
      <rect x="32" y="42" width="15" height="9" rx="4" fill="none" stroke="#2a0f5c" strokeWidth="2" />
      <rect x="53" y="42" width="15" height="9" rx="4" fill="none" stroke="#2a0f5c" strokeWidth="2" />
      <line x1="47" y1="46.5" x2="53" y2="46.5" stroke="#2a0f5c" strokeWidth="2" />
      <path d="M36 80 Q50 75 64 80 L64 71 Q50 66 36 71 Z" fill="#ffffff" />
      <path d="M43 74 L36 81 L36 90 L43 85 Z" fill="#7ad1c4" />
      <path d="M57 74 L64 81 L64 90 L57 85 Z" fill="#7ad1c4" />
    </svg>
  );
}

function ClerkIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#e6e0fb" />
      <Head skin="#f0b98d" hair="#4a3223" />
      <path d="M39 80 L50 88 L61 80 L61 71 L50 76 L39 71 Z" fill="#6528d9" />
      <path d="M46 71 L50 84 L54 71 L52 69 L48 69 Z" fill="#ffffff" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#2a0f5c" />
      <Head skin="#e3a877" hair="#241a12" />
      <path d="M36 80 Q50 75 64 80 L64 71 Q50 66 36 71 Z" fill="#2a0f5c" />
      <path d="M50 73 L59 77 L59 86 Q50 92 41 86 L41 77 Z" fill="#c4b5fd" />
      <path d="M50 75 L56 78 L56 84 Q50 89 44 84 L44 78 Z" fill="#6528d9" />
    </svg>
  );
}

function PatientIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M35 80 L50 92 L65 80 L65 102 L35 102 Z" fill="#bfe3f0" />
      <Head skin="#f0b98d" hair="#7a5236" />
      <path d="M36 80 Q50 75 64 80 L64 71 Q50 66 36 71 Z" fill="#eef7fb" />
      <path d="M45 74 q5 4 10 0" stroke="#e0435c" strokeWidth="2" fill="none" strokeLinecap="round" />
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
