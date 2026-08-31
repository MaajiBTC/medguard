// One small flat-cartoon "mascot" avatar per role, hand-drawn as plain SVG
// shapes (no icon library, no downloaded/generated images -- per the user,
// 2026-08-31, after several stock-photo/clip-art references couldn't be
// reproduced due to copyright, or because they used a real-looking human
// face/likeness). Shown as the left-hand avatar on the Staff/Patients/
// Admins activity pages once a specific entity is selected. Each character
// shares the same face/head shapes; only hair, outfit color, and a small
// role-specific accessory differ. Redrawn with bold dark outlines on every
// shape the same day to get closer to a flat-vector-clip-art reference's
// style (still hand-drawn, not the reference image itself).

const OUTLINE = "#241a30";

function Head({ skin, hair, hairPath }) {
  return (
    <>
      <circle cx="50" cy="44" r="24" fill={skin} stroke={OUTLINE} strokeWidth="1.6" />
      <ellipse cx="41" cy="36" rx="8" ry="6" fill="#ffffff" opacity="0.3" />
      <path d={hairPath} fill={hair} stroke={OUTLINE} strokeWidth="1.4" />
      <path d="M34 39 Q39 35 45 39" stroke={OUTLINE} strokeWidth="1.8" fill="none" strokeLinecap="round" />
      <path d="M55 39 Q61 35 66 39" stroke={OUTLINE} strokeWidth="1.8" fill="none" strokeLinecap="round" />
      <ellipse cx="40" cy="46" rx="5" ry="6" fill="#ffffff" stroke={OUTLINE} strokeWidth="1" />
      <ellipse cx="60" cy="46" rx="5" ry="6" fill="#ffffff" stroke={OUTLINE} strokeWidth="1" />
      <circle cx="40.5" cy="47" r="3.4" fill="#3b2412" />
      <circle cx="60.5" cy="47" r="3.4" fill="#3b2412" />
      <circle cx="39.3" cy="45.6" r="1.1" fill="#ffffff" />
      <circle cx="59.3" cy="45.6" r="1.1" fill="#ffffff" />
      <circle cx="39" cy="55" r="3.8" fill="#f28fa3" opacity="0.45" />
      <circle cx="61" cy="55" r="3.8" fill="#f28fa3" opacity="0.45" />
      <path d="M42 58 Q50 63 58 58" stroke="#8a4a2c" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </>
  );
}

const SIDE_PART_HAIR =
  "M25 40 C24 15 76 15 75 40 C74 28 65 19 50 19 C57 21 63 26 65 33 C58 24 48 20 38 23 C44 22 49 25 51 29 C43 22 32 24 27 34 C26 30 25 35 25 40 Z";

function DoctorIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#ffffff" stroke={OUTLINE} strokeWidth="1.6" />
      <path d="M40 78 L50 90 L50 74 Z" fill="#f4f2fb" stroke={OUTLINE} strokeWidth="1.4" />
      <path d="M60 78 L50 90 L50 74 Z" fill="#f4f2fb" stroke={OUTLINE} strokeWidth="1.4" />
      <path d="M45 76 L50 84 L55 76 L53 73 L47 73 Z" fill="#2f5fa8" stroke={OUTLINE} strokeWidth="1.2" />
      <rect x="55" y="86" width="12" height="10" rx="1.5" fill="#ffffff" stroke={OUTLINE} strokeWidth="1.3" />
      <rect x="57" y="82" width="1.6" height="7" fill="#e0435c" />
      <rect x="60" y="82" width="1.6" height="7" fill="#2f5fa8" />
      <rect x="63" y="82" width="1.6" height="7" fill="#2a2a2a" />
      <path d="M37 82 Q37 70 50 70 Q63 70 63 82" fill="none" stroke="#4a4a52" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M37 82 Q35 92 42 96" fill="none" stroke="#4a4a52" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="43" cy="97" r="3.6" fill="#8a97ab" stroke={OUTLINE} strokeWidth="1.2" />
      <Head skin="#f0b98d" hair="#5b4636" hairPath={SIDE_PART_HAIR} />
    </svg>
  );
}

function NurseIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#ffffff" stroke={OUTLINE} strokeWidth="1.6" />
      <path d="M63 32 C82 36 84 60 70 76 C78 62 76 44 62 36 Z" fill="#6a3d28" stroke={OUTLINE} strokeWidth="1.4" />
      <circle cx="66" cy="34" r="4" fill="#8a5a3a" stroke={OUTLINE} strokeWidth="1" />
      <path d="M42 78 Q50 82 58 78" fill="none" stroke="#3fb3a3" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M37 80 Q37 68 50 68 Q63 68 63 80" fill="none" stroke="#4a4a52" strokeWidth="2.4" strokeLinecap="round" />
      <Head skin="#f0b98d" hair="#6a3d28" hairPath={SIDE_PART_HAIR} />
    </svg>
  );
}

function PharmacistIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#ffffff" stroke={OUTLINE} strokeWidth="1.6" />
      <Head skin="#e3a877" hair="#1f1a17" hairPath={SIDE_PART_HAIR} />
      <g transform="translate(50 84) rotate(-40)">
        <rect x="-9" y="-3" width="18" height="6" rx="3" fill="#3fb3a3" stroke={OUTLINE} strokeWidth="1.2" />
        <line x1="-6" y1="0" x2="6" y2="0" stroke="#ffffff" strokeWidth="1.3" />
      </g>
    </svg>
  );
}

function LabTechnicianIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#ffffff" stroke={OUTLINE} strokeWidth="1.6" />
      <Head skin="#f0b98d" hair="#6b4a2f" hairPath={SIDE_PART_HAIR} />
      <rect x="32" y="42" width="15" height="9" rx="4" fill="none" stroke={OUTLINE} strokeWidth="2" />
      <rect x="53" y="42" width="15" height="9" rx="4" fill="none" stroke={OUTLINE} strokeWidth="2" />
      <line x1="47" y1="46.5" x2="53" y2="46.5" stroke={OUTLINE} strokeWidth="2" />
      <path d="M43 76 L36 83 L36 92 L43 87 Z" fill="#7ad1c4" stroke={OUTLINE} strokeWidth="1.2" />
      <path d="M57 76 L64 83 L64 92 L57 87 Z" fill="#7ad1c4" stroke={OUTLINE} strokeWidth="1.2" />
    </svg>
  );
}

function ClerkIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#ffffff" stroke={OUTLINE} strokeWidth="1.6" />
      <Head skin="#f0b98d" hair="#4a3223" hairPath={SIDE_PART_HAIR} />
      <path d="M39 80 L50 88 L61 80 L61 71 L50 76 L39 71 Z" fill="#6528d9" stroke={OUTLINE} strokeWidth="1.3" />
      <path d="M46 71 L50 84 L54 71 L52 69 L48 69 Z" fill="#ffffff" stroke={OUTLINE} strokeWidth="1" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#2a0f5c" stroke={OUTLINE} strokeWidth="1.6" />
      <Head skin="#e3a877" hair="#241a12" hairPath={SIDE_PART_HAIR} />
      <path d="M50 73 L59 77 L59 86 Q50 92 41 86 L41 77 Z" fill="#c4b5fd" stroke={OUTLINE} strokeWidth="1.3" />
      <path d="M50 75 L56 78 L56 84 Q50 89 44 84 L44 78 Z" fill="#6528d9" />
    </svg>
  );
}

function PatientIcon() {
  return (
    <svg viewBox="0 0 100 100">
      <path d="M30 80 Q50 72 70 80 L72 102 L28 102 Z" fill="#eef7fb" stroke={OUTLINE} strokeWidth="1.6" />
      <Head skin="#f0b98d" hair="#7a5236" hairPath={SIDE_PART_HAIR} />
      <path d="M45 80 q5 4 10 0" stroke="#e0435c" strokeWidth="2" fill="none" strokeLinecap="round" />
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
