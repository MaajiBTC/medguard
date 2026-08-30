# CLAUDE.md — MedGuard Project Context

This file is read automatically at the start of every Claude Code session in this project. It is the ground truth for scope, architecture, and constraints. Do not deviate from what's specified here without asking the user first. Claude Code is building the entire system — there is no team split; build every component described below in the order specified.

## Project identity

**MedGuard** — a security and access-control layer for patient records, built for Track C ("Safe Access to Patient Records") of the ICSC 2026 Universities Hackathon, scoped to Nigerian hospitals and Nigerian law (National Health Act 2014, Nigeria Data Protection Act 2023, Patients' Bill of Rights).

**Critical scope boundary:** this is a security *layer*, not a hospital management system. It sits in front of a minimal, custom-built demo records system. Do not build booking, scheduling, billing workflows, or any general hospital feature. Every feature request should be checked against "does this serve access control, authentication, or audit" — if not, it's out of scope.

## Explicit exclusions — do not build these

- Appointment booking or scheduling
- General print/report features on the staff/clerk UI
- A dynamic staff shift-scheduling system — on-duty status and ward assignment come from a manually populated staff table (populated with user-supplied data, not generated), not a computed scheduler
- Any matching/scoring/decision logic inside the two capture modules (behavioral, contextual) — those modules only capture and store raw data; the Scoring Engine is a separate component
- Patient self-access — fingerprint identity is used for staff-facing emergency/offline patient lookup only (see Bonus Layer section). Do not build a patient-facing self-request flow.
- **No auto-generated or placeholder demo data of any kind** — see "Enrollment data" section below

## Patient record categories (13 total — use these exact categories and numbers throughout the codebase)

1. Identity — name, DOB, sex, address, phone, next of kin, marital status, occupation
2. Administrative/Billing — folder number, insurance/NHIS, billing/payment history, admission/discharge dates
3. Vital Signs & Routine Observations — height, weight, BP, temperature, pulse
4. Diagnosis & Medical History — current/past diagnoses, chronic conditions
5. Medication & Prescriptions — current meds, prescription history, dosages
6. Allergies — drug and other allergies
7. General Lab Results — routine bloodwork, urinalysis, standard panels
8. Highly Sensitive Test Results — HIV status, genotype, STI results, pregnancy status, genetic testing
9. Mental Health Records — psychiatric history, therapy/counseling notes
10. Reproductive Health Records — pregnancy/obstetric history, family planning
11. Surgical/Procedure History — operations performed, procedure notes
12. Nursing & Care Notes — day-to-day nursing observations, care plan
13. Imaging/Radiology — X-rays, scans, imaging reports

## Role → category access (the ceiling — see Scoring section for how much of this ceiling is granted per session)

| Role | Access | Rule |
|---|---|---|
| Doctor | 1–13 (full) | No conditions, **except one hard-deny carve-out — see Doctor rule below** |
| Nurse | 1–13 (full) | **Two paths, different outcomes — see Nurse rule below** |
| Pharmacist | 1, 4, 5, 6, 7 (full) | No conditional access |
| Lab technician | 1 only | No conditional access |
| Clerk | 1, 2 only | No conditions |

**Two additional roles exist outside this table (added 2026-08-25, step 4):** `admin` and
`security_officer`. Both are system roles, not clinical ones — they never request patient
record categories through the Scoring Engine at all (`scoring.views.DecideView` rejects
them with 403), so they have no row here by design, not by omission. Admin manages
staff/patient/assignment data (its own role-gated endpoints, `staff.permissions.IsAdmin`);
security officer reads the Security Ledger (`staff.permissions.IsSecurityOfficer`). Both
log in through the same shared login page/session mechanism as the five clinical roles
above — see step 4.

**Who can create which role (added 2026-08-30):** `staff.permissions.IsAdminOrSecurityOfficer`
gates `POST /api/staff/create/`, but which target role each side may actually create is
further restricted inside the view — an Admin can create any role *except* another admin
account; a Security Officer can *only* create admin accounts (self-attested, not
system-verified, same trust model as the rest of this project's manual-entry fields).
This is why admin-account creation lives on the Security dashboard's own "Admins" page,
not the Admin dashboard's "Add Staff" form (which no longer offers the admin role at
all). Both `admin` and `security_officer` are shared accounts with no ward/on-duty/
on-call concept — `Staff.NO_WARD_DUTY_ROLES` — so `StaffCreateView` forces those three
fields blank/false for them regardless of what's submitted, and `StaffDutyWardUpdateView`
rejects any attempt to set them for an existing admin/security-officer row (400).

**Nurse rule (specific override — implement exactly this logic, it does not follow the generic role-ceiling pattern above):**
1. Nurse is specifically assigned to this patient → full access (1–13) granted normally, processed through the standard score-band system like any other access.
2. Nurse is **not** specifically assigned to this patient, but is on the **same ward** as the patient → full access (1–13) is still granted, but this access is **always** logged as `AUDITED_DEVIATION`, regardless of what the aggregate score would otherwise indicate.
3. Nurse is neither assigned to the patient nor on the same ward → **hard-denied** (`ACCESS_DENIED`, no categories granted), regardless of score — standard scoring does not apply to this case (revised 2026-08-25: the original wording let this case fall through to standard scoring, which could still land in `AUDITED_DEVIATION` territory if other factors scored well despite the ward mismatch; the user wants zero ambiguity here). The intended path to access in this case is Emergency Override ("Break the Glass") — **but see the 2026-08-29 note below: BTG itself now has its own duty-status gate**, so this rescue path is only open while the nurse is on duty *or* on call.

**This does not bypass the hard behavioral-mismatch gate** (see Scoring Engine) — a proven behavioral mismatch still overrides and denies access even in cases 1 and 2 above. The gate always takes precedence over any role-specific ceiling rule.

**Doctor rule (added 2026-08-29, one carve-out — not a full path structure like the Nurse rule above):** a doctor who is **off duty and not on call** *and* has no connection to the patient at all (not specifically assigned, and not even on the patient's ward) → hard-denied (`ACCESS_DENIED`, no categories granted), regardless of score — same standard the Nurse rule's worst case already applies. Every other doctor combination (on duty/on call regardless of assignment; off duty but same ward; off duty but assigned) is untouched and still goes through standard weighted scoring exactly as before — this was confirmed live: an off-duty doctor with no ward/assignment connection previously only dropped to `REDUCED_ACCESS` (65%, sensitive categories hidden), never a hard deny. The hard behavioral gate still takes precedence over this rule, same as it does over the Nurse rule. **Suspended hospital-wide while Disaster/Mass Casualty Mode is active** (see its own section below).

## Two-dimensional access model

Access to a record on any given session is determined by:
1. **Role** sets the ceiling (table above) — which categories this role could ever see. For nurses specifically, the patient-assignment status (see Contextual module below) determines which of the two nurse paths applies.
2. **Score band** (below) determines how much of that ceiling is actually granted this session — except where a role-specific rule (like the nurse same-ward case) forces a specific outcome regardless of band.

## Scoring Engine specification

**Hard gate (checked first, before any weighted scoring, and before any role-specific rule above):** severe behavioral mismatch (keystroke/touch rhythm wildly unlike the stored baseline) overrides everything else regardless of score or role rule. This is the one factor nothing else can compensate for.

**Weighted factors (only evaluated if the gate passes):**

| Factor | Weight |
|---|---|
| On-duty status | 20% |
| Ward assignment | 15% |
| Keystroke/touch dynamics match | 30% |
| Mouse dynamics match | 15% |
| Device recognition | 10% |
| Login time normalcy | 7% |
| Location/network match | 3% |

On touch-only devices, drop mouse dynamics and redistribute its weight proportionally across the remaining factors.

**Access bands:**

| Score | Result |
|---|---|
| 90–100% | Full role-permitted access, silent |
| 70–89% | Full role-permitted access, logged as `AUDITED_DEVIATION` |
| 40–69% | Reduced access (exclude highest-sensitivity categories 8–11, 13 even if role would normally allow them) + step-up verification required |
| Below 40%, or gate failed | `ACCESS_DENIED`, security alert triggered |

**Worked example (confirmed correct):** doctor on duty (20% intact), everything else passing, only ward assignment fails (−15%) → 85% → 70–89% band → full access, logged as an audited deviation.

## Behavioral Signal Capture Module — spec summary

Captures only, no matching/scoring. Three signal families:
- **Keystroke (revised 2026-08-25):** derived, anonymized timing features only — never raw key identity. Computed client-side from `keydown`/`keyup` timestamps: flight time (down[i+1] − up[i]), digraph latency (down[i+1] − down[i]) and trigraph latency (down[i+2] − down[i]) indexed by **keystroke position**, never by which character was pressed; error/correction rate (Backspace/Delete presses ÷ total keystrokes — the only key identity ever inspected, since those are control keys, not password characters); rhythm consistency (inverse coefficient of variation of flight times); automation flags (heuristic tags like "impossibly_fast", "zero_variance", "paste_detected"). This is why capture now runs **on the login page too** (previously excluded entirely) — since no raw key identity is ever stored or transmitted, typing the password no longer risks recording the password itself. Position-indexed digraphs/trigraphs work because a person retypes the same credential in the same order every login, so position carries the same matching value character-labeling would, without the leak. Computing these features is still just capture/data-reduction, not a matching or access decision — comparing them against a stored baseline and deciding access is still entirely the Scoring Engine's job (see explicit exclusions above).
- **Mouse:** movement trajectory (coordinate stream), speed, acceleration, click duration, click interval, double-click interval, idle time. Capture via `mousemove`/`mousedown`/`mouseup`, ~10–20ms sampling on movement. Runs on the login page too — coordinates never revealed key identity, so there was never a reason to exclude it.
- **Touch:** tap duration, swipe speed/path, interval between taps, pressure/contact size if hardware supports it. Capture via `touchstart`/`touchmove`/`touchend`.

Output format: a `BehavioralCapture` record per session. `keystroke_features` holds `{"login": {...} | null, "session_windows": [...]}` (derived features, computed once at login and periodically thereafter). `mouse_events`/`touch_events` stay raw event arrays for whichever signal types are relevant to that device (empty array for non-applicable types).

## Contextual Signal Capture Module — spec summary

Captures only, simple lookups, no scoring:
- Login timestamp
- Device ID/type/user-agent
- Location — network segment/ward (no GPS; hospital desktops)
- On-duty status — lookup against the staff table
- **On-call status (added 2026-08-29)** — lookup against the staff table (`Staff.on_call`), same manually-set-never-computed pattern as on-duty. Treated as fully equivalent to on-duty by the Doctor rule and BTG's availability gate (see below) — a staff member who's off duty but reachable isn't treated as disconnected from the hospital. Snapshotted at login as `ContextualCapture.on_call_at_login`, same historical-accuracy reasoning as `on_duty_at_login`.
- Ward assignment — lookup against the staff table (which ward the staff member is generally assigned to). **Fixed ward taxonomy (added 2026-08-29):** `ward` on both `Staff` and `Patient` is a shared, backend-enforced choice field (`staff.models.Ward`) with exactly four values — General Male Ward, General Female Ward, Surgical Ward, Emergency Ward — not free text. This was needed so the Nurse/Doctor "same ward" rules below compare against a fixed value space instead of relying on admins typing identical free text on both sides.
- **Patient-assignment status (new)** — is this doctor or nurse *specifically* assigned to the patient currently being accessed, as distinct from general ward assignment above. Captured via lookup against a patient-assignment table (e.g., "Dr. A is the assigned doctor for Patient #1042," "Nurse B is the assigned nurse for Patient #1042"). Required for doctors and nurses; not applicable to pharmacist, lab technician, or clerk roles under the current access rules. This field is what determines which of the two Nurse-rule paths applies above.

Output format: a `ContextualCapture` record per session.

## Security Ledger

Independent, hash-chained, append-only. Every decision from every component (role/score decision, emergency override) writes here. Event types — use exactly these five:
- `STANDARD_ACCESS`
- `AUDITED_DEVIATION`
- `REDUCED_ACCESS`
- `ACCESS_DENIED`
- `EMERGENCY_OVERRIDE`

Each entry includes a hash of the previous entry (`hashlib` is sufficient — no blockchain). Store separately from the main application's database/permission system so a compromised main system can't edit its own trail.

## Emergency Override

Always available regardless of score or role match. One action grants immediate access. Always logged as `EMERGENCY_OVERRIDE`, and that log entry can never be edited or deleted, including by the triggering user.

**User-facing name: "Break the Glass" (BTG)** (decided 2026-08-28) — the internal `decision_type`/ledger `event_type` stays the literal string `EMERGENCY_OVERRIDE` (required exactly, per the Security Ledger's five event types above); BTG is the UI label only.

**What "regardless of score or role match" bypasses (decided 2026-08-28, step 5):** the hard behavioral gate, the score band, and the Nurse rule's assignment/ward matching — **not** the role ceiling table. A clerk invoking BTG still only gets categories 1–2 (their ceiling); a nurse gets the full 1–13 nurse ceiling. This is what makes BTG "the only path to access" for the Nurse rule's case 3 (neither assigned nor same ward) without also letting every role see all 13 categories in an emergency. Still requires a logged-in session (`IsClinicalStaff` — same authenticated-session boundary as everything else; BTG is not a way around login). A reason (min 10 characters) is required and stored in the Ledger entry's `details`, since an always-logged bypass with no justification text would defeat the audit purpose.

**BTG is no longer unconditional (added 2026-08-29):** it is blocked for a doctor or nurse who is **both** off duty (and not on call) **and** has no connection to the patient at all (not assigned, not even on their ward) — the one combination where the system has already concluded there's no legitimate reason to be looking at this patient (it's also the exact combination that now hard-denies normal access — see the Doctor rule and the Nurse rule's case 3 above). Every other combination for both roles still has BTG available, including a nurse's "neither assigned nor same-ward but on duty/on call" case — her rescue path stays open. This check uses **live**, current `staff.on_duty`/`staff.on_call` and a fresh assignment/ward lookup (`captures.services.compute_patient_assignment_status`) computed at the moment BTG is invoked — not a session snapshot — since BTG must keep working even when a session never went through the normal capture flow at all. Pharmacist/lab tech/clerk are unaffected (no assignment/ward concept for those roles, so the gate never applies to them).

**`on_call` (added 2026-08-29):** a manual, admin-set `Staff` field (never computed — same as `on_duty`/`ward`). Per the user, on-call is *"just like on duty status but virtually"* — treated as fully equivalent to `on_duty` everywhere the Doctor rule and the BTG gate above check duty status.

**BTG cross-coverage (added 2026-08-29):** no automated "hospital workstation + clinical hours" detection was built — the user explicitly rejected that in favor of a simpler, human-attested approach. Instead, BTG's `reason` becomes two required fields: a `reason_category` (`clinical_emergency` / `cross_coverage` / `other`) plus the existing free-text `reason` detail. Selecting **`cross_coverage`** is itself what lets BTG through the off-duty(+not on call)+unconnected block above (e.g. a doctor covering a colleague's unrostered shift, roster not yet updated) — self-attested and permanently logged with the category, same trust model the free-text reason always used, not a system-verified check. The other two categories do not affect the block.

**Disaster/Mass Casualty Mode (added 2026-08-29):** a hospital-wide switch, `POST /api/scoring/disaster-mode/activate/` and `.../deactivate/` (`{reason}`, min 10 characters, `staff.permissions.IsAdmin`-gated — UI lives on the Admin dashboard only). While active, it suspends **both** the Doctor off-duty+unconnected hard-deny rule **and** BTG's availability gate hospital-wide (does not touch the hard behavioral gate, role ceilings, or the Nurse rule's own original assignment/ward logic — only the two 2026-08-29 additions). Manual on/off only, no auto-expiry; activating while already active (or deactivating while already inactive) is rejected. Audited in its own `scoring.DisasterModeEvent` history table (`scoring.disaster_mode.is_disaster_mode_active()` derives current status from the latest event) — **deliberately not routed through the Security Ledger**, since CLAUDE.md pins the Ledger to exactly five event types above and "the mode itself changed" doesn't fit any of them; stretching that spec was explicitly rejected in favor of a separate, purpose-built audit trail.

## Security Dashboard

A monitoring screen showing a live feed of `AUDITED_DEVIATION`, `REDUCED_ACCESS`, `ACCESS_DENIED`, and `EMERGENCY_OVERRIDE` events, filterable by staff member/patient/date, with drill-down into which specific factor(s) caused a deviation.

## Offline Mode

- Role/score decisioning and Emergency Override continue to work locally using the last-synced cache.
- Ledger queues events locally, still hash-chained in real time (not only checked at sync), verified against the central ledger before merging once connectivity returns.
- All locally cached data (patient summaries, templates, local ledger) encrypted at rest.
- Each device has its own registered signing key; unsigned/unregistered device batches are rejected at sync.
- Devices still require local staff login — offline never means unrestricted.
- For vendor-hosted/cloud clinics without their own server room: the offline layer runs as a lightweight local agent per workstation (SQLite or encrypted browser storage), not a dedicated server — the device is a temporary bridge, syncing back to the vendor's existing cloud system once online.

## Bonus layer: MedGuard Identity (fingerprint patient identification)

**Build this last — nothing else in the system depends on it. See "Timeline & scope commitment" above: the user has committed to attempting this, not just building it opportunistically.**

- Purpose: identify the *patient* for staff performing emergency or offline lookup — not authentication, not a patient-facing feature. Operates in "identification mode" (which patient is this) not "authentication mode" (prove a claim) — the fingerprint is a pointer to a record, not a secret/password.
- Extraction/matching library: **SourceAFIS** (open-source) — minutiae extraction + similarity matching. Do not hash the raw scan directly; two genuine scans are never bit-identical.
- Store encrypted templates (AES), never raw images.
- Card remains a parallel fallback path — either resolves to the same record.
- Use case: **emergency/offline patient lookup only** — a staff member scans the patient's fingerprint (e.g., unconscious patient, or network down) and it resolves instantly from a locally cached template, pulling a minimal summary (blood type, allergies, current meds, major diagnoses, emergency contact).

## Build order (follow this sequence)

1. ✅ **Done (2026-08-24).** Behavioral capture module and Contextual capture module — no dependency between them, build in either order. Implemented as a Django+DRF backend (`staff`/`patients`/`access`/`captures` apps) and a React frontend, per the plan at the time: `.claude/plans/tidy-questing-dahl.md`. 47/47 backend tests passing; manually verified login → capture flow in-browser. No staff/patient/fingerprint data exists in the real database (confirmed empty) — automated tests use Django's isolated test DB only. `CaptureDevPanel.jsx` in the frontend is a **temporary dev-only screen** exercising the capture pipeline before step 4's real search UI exists — remove/hide it once step 4 lands.
2. ✅ **Done (2026-08-25).** Combined Scoring Engine. Implemented as a new `scoring` Django app: hard behavioral-mismatch gate, the 7 weighted factors (with touch-only weight redistribution), role ceilings, the 40–69% reduced-band category exclusion, and the full 3-path Nurse rule (including the 2026-08-25 correction making the "neither assigned nor same-ward" case a hard `ACCESS_DENIED`). Staff behavioral baselines are rolling {mean, stdev} stats updated via Welford's algorithm, reinforced only on non-denied decisions. Exposed via `POST /api/scoring/decide/`. 62/62 backend tests passing (13 new). No staff/patient/fingerprint data exists in the real database — tests use Django's isolated test DB only.
3. ✅ **Done (2026-08-25).** Security Ledger. New `ledger` Django app, routed to its own database via a Django database router (`ledger/db_router.py`) — separate from the main app's database even locally (a second SQLite file today; swap in a real second Postgres instance later by setting `LEDGER_DATABASE_URL`, no code changes needed). `LedgerEntry` rows are hash-chained (`hashlib.sha256` over each entry plus the previous entry's hash) and append-only (`save()`/`delete()` raise on an existing row, and — added 2026-08-25 after manual testing surfaced the gap — a custom `LedgerQuerySet` also blocks bulk `.update()`/`.delete()`, which otherwise bypass instance methods entirely; admin registered read-only). `ledger.services.record_event()` is the only write path; `scoring.views.DecideView` now calls it for every decision (grants and denials alike) right after computing it, unguarded so a ledger-write failure fails the request rather than returning an unaudited decision. `ledger.verification.verify_chain()` walks and re-validates the whole chain — covered by tests, and reusable as-is by step 6's offline-sync verification. 69/69 backend tests passing (7 new).
4. ✅ **Done (2026-08-25).** Main UI: one shared login page for every role (`LoginPage.jsx`, unchanged — it was already role-agnostic), routed by `staff.role` to one of three dashboards in `App.jsx`. New `PatientCategoryRecord` model (13 rows per patient, one per category, generic `{"notes": ...}` content — deliberately not a structured EMR) gives the category-slicing something real to display, auto-created empty alongside a new patient. **Clinical dashboard** (`ClinicalDashboard.jsx`): search → set target patient → `/api/scoring/decide/` → renders only the granted categories, plus own duty/ward status and (doctor/nurse) assigned patients. **Admin dashboard** (`AdminDashboard.jsx`, new `admin`/`security_officer` roles, new `staff`/`patients` API endpoints gated by `staff.permissions.IsAdmin`): staff search/create/deactivate-reactivate (deactivate = `user.is_active = False`, never a hard delete) and ward/duty updates; patient search/create/ward updates/category-content edits/doctor+nurse assignment. **Security dashboard** (`SecurityDashboard.jsx`, `staff.permissions.IsSecurityOfficer`, new read-only `GET /api/ledger/entries/`): filterable live feed table with drill-down into `factor_breakdown`, plus the three.js visualization CLAUDE.md scopes to this screen (`LedgerVisualization.jsx` — `three` now an installed dependency). `CaptureDevPanel.jsx` removed. 89/89 backend tests passing (20 new); manually verified all three dashboards end-to-end in-browser (login → dashboard routing, patient/staff creation, assignment, category editing, the full decide→records flow at an audited-deviation score, and the live ledger feed + 3D panel updating from a real decision) — all test fixtures created during that manual pass were deleted from the real database afterward. Manual testing also surfaced and fixed a real gap: bulk queryset `.update()`/`.delete()` bypassed the Ledger's append-only guards (see step 3's entry above).
   **Amended (2026-08-29, dashboard visual/IA rework):** all three dashboards moved
   from the dark-mode-aware `--bg`/`--text`/`--accent` look to the login page's fixed
   light plum/lavender/off-white brand palette (tokens promoted from
   `.login-page`-scoped to `:root` in `App.css`), and picked up a shared
   `DashboardShell.jsx` (off-canvas drawer nav behind a hamburger button, closed by
   default) plus a `Modal.jsx` primitive for "Add New" forms. Admin dashboard
   specifically: new landing `OverviewPanel` (real total patients/staff/on-duty
   counts + Disaster Mode status, replacing the old default-to-Staff-panel
   behavior); `StaffPanel`/`PatientPanel` now show category tiles first (by role,
   by ward) and drill into a filtered list rather than one flat searchable list;
   Disaster Mode moved from an always-visible banner above Staff/Patients to its own
   drawer destination. Added a fixed, shared **ward taxonomy**
   (`staff.models.Ward`: General Male Ward, General Female Ward, Surgical Ward,
   Emergency Ward) enforced on both `Staff.ward` and `Patient.ward` (see Contextual
   module above) — required so the Nurse/Doctor same-ward rules compare a fixed
   value space instead of independently-typed free text. New `GET /api/staff/summary/`
   and `GET /api/patients/summary/` (`IsAdmin`) for the overview/category counts, and
   optional `role=`/`ward=` filters on the existing search endpoints so category
   drill-down isn't limited by the 50-row search cap. 133/133 backend tests passing.
   **Known gap surfaced by this change, not yet resolved:** the two pre-existing real
   staff rows in the dev database had `ward` set to the display label text (e.g.
   `"General Male Ward"`) rather than the new choice key (`general_male`) — typed
   before this taxonomy existed. They'll need their ward re-saved via the Admin UI's
   new ward dropdown for ward-matching to work correctly for them; not fixed
   automatically since that's real user-entered data, not a fixture.

   **Amended (2026-08-30):** admin-account creation moved off the Admin dashboard
   entirely (see Role → category access above) -- `AdminDashboard.jsx`'s "Add Staff"
   role dropdown no longer offers `admin`, and a new "Admins" page on
   `SecurityDashboard.jsx` is the only place one can be created. Both `admin` and
   `security_officer` creation forms (and the existing-staff "Manage" edit panel)
   now hide ward/on-duty/on-call entirely for those two roles, matching the new
   backend enforcement (`Staff.NO_WARD_DUTY_ROLES`). 139/139 backend tests passing.

   **Amended (2026-08-30, header restyle + Profile page):** the sticky header
   (`DashboardShell.jsx`) switched from the light `--off-white` background to
   `--plum-deep` (matching the login page's brand panel and the nav drawer), and
   was rearranged into three fixed slots via CSS grid (not flex, so the middle
   slot stays exactly centered regardless of how wide the other two are): the
   hamburger button + a short per-page label (e.g. "Staff", "Security Ledger") on
   the left in `--lavender`; an enlarged MedGuard brand mark (flat SVG shield —
   still no three.js outside the login page and the Security Dashboard
   visualization) centered; a profile icon-only button on the right (the staff
   name/staff_id text that used to sit there is gone). The header's descriptive
   subtitle line is gone site-wide — `ClinicalDashboard.jsx`'s on-duty/ward status
   (documented above as part of this dashboard's job) moved into the page content
   itself instead of being dropped, since it's live status, not just a
   description.

   New: clicking the profile icon opens a Profile page (managed as
   `DashboardShell`'s own `profileOpen` state, independent of whatever page each
   dashboard has active, so it works the same from Admin/Clinical/Security) —
   read-only name/staff_id/role plus a change-password form (password only,
   nothing else editable there). New backend endpoint
   `POST /api/access/change-password/` (`access.views.ChangePasswordView`, default
   `IsAuthenticated` — any logged-in staff member changes their own password, no
   role restriction) verifies the current password via `user.check_password()`
   before calling `set_password()`. 143/143 backend tests passing (4 new).
5. ✅ **Done (2026-08-28).** Emergency Override ("Break the Glass" / BTG in the UI — see the Emergency Override section above for naming and scope decisions). New `POST /api/scoring/emergency-override/` (`scoring.views.EmergencyOverrideView`, `IsClinicalStaff`-gated): takes `{patient_id, reason}` (reason min 10 chars), grants the caller's full role ceiling (`ROLE_CEILINGS[staff.role]`) regardless of the hard gate/score band/Nurse rule, writes an `AccessDecision` row (`decision_type=EMERGENCY_OVERRIDE`; `gate_passed`/`score`/`score_band` now nullable on that model — an override never ran the scoring pipeline, so "not applicable" is more honest than a sentinel score) and an `EMERGENCY_OVERRIDE` Ledger entry (`reason` in `details`). Does not check `contextual.target_patient_id` the way `DecideView` does (must still work if capture/contextual state is missing or itself the reason normal access failed) and does not reinforce the behavioral baseline (an override is by definition an abnormal session). `scoring.views.PatientRecordView` needed no changes — it already treats any non-`ACCESS_DENIED` decision type the same way. Frontend: `ClinicalDashboard.jsx` gained a "Break the Glass" button in the patient-view section (always visible once a patient is selected, not gated behind a denial) that reveals an inline reason textarea before submitting — no native `confirm()` dialog. `SecurityDashboard.jsx` needed no changes (its event-type filter/severity coloring/drill-down already handled `EMERGENCY_OVERRIDE` rows from step 4). 105/105 backend tests passing (8 new); verified end-to-end via direct API calls against the real dev database using the real Admin and doctor accounts (Chrome browser extension wasn't connected for a live UI click-through) — confirmed the full round trip (override → granted all 13 categories → records endpoint returns content → a correctly hash-chained `EMERGENCY_OVERRIDE` Ledger entry with the reason). The temporary QA patient and sessions were deleted afterward; the Ledger entry itself was left in place since it's append-only by design.

   **Amended 2026-08-29** (after a live demo surfaced a real gap): added the Doctor rule (see Role → category access above) and BTG's own availability gate (see Emergency Override above). `AccessDecision.nurse_path` renamed to `role_rule_path` (now used by both roles' rule paths; migration `scoring/0003_rename_nurse_path_to_role_rule_path.py`). New `captures/services.py` (`compute_patient_assignment_status`) extracted from `captures.views.TargetPatientView` so both the normal capture flow and BTG's fresh gate check share one implementation instead of two.

   **Amended again 2026-08-29** (same-day follow-up, real-world refinement of the above): added `Staff.on_call`/`ContextualCapture.on_call_at_login` (treated as equivalent to on-duty everywhere the Doctor rule/BTG gate check duty status — see Contextual module and Emergency Override above), BTG's `reason_category` field (`clinical_emergency`/`cross_coverage`/`other` — `cross_coverage` self-attests through the off-duty+unconnected block), and Disaster/Mass Casualty Mode (`scoring.DisasterModeEvent`, `scoring.disaster_mode.is_disaster_mode_active()`, `IsAdmin`-gated `POST /api/scoring/disaster-mode/activate|deactivate/`, Admin-dashboard-only `DisasterModePanel` — see Emergency Override above for full scope/reasoning, including why it's audited outside the Security Ledger). Frontend: `ClinicalDashboard.jsx`'s BTG form gained a required category `<select>` above the existing reason textarea; `AdminDashboard.jsx`'s `StaffPanel` gained an "On call" checkbox alongside "On duty".
6. Offline Mode (wraps steps 1–5)
7. Bonus: MedGuard Identity — fingerprint matching, emergency/offline lookup only

**Do not populate the database with any staff, patient, or fingerprint data until the user supplies it** — see Enrollment data below.

## Tech stack (finalized with the user 2026-08-24)

- Backend: Python + Django (+ Django REST Framework for the API layer, since the frontend is a separate React app, not Django templates)
- Database: SQLite
- Frontend: React + three.js
  - three.js is scoped to two places only: the **Security Dashboard visualization** and the **login/landing page**. Do not use it in the functional record-access screens (search, category views, etc.) — keep those plain React for clarity and performance. Login page's three.js piece implemented 2026-08-29 (`LoginScene.jsx`, revised three times same day): a plum shield body (extruded `THREE.Shape`, its own silhouette — not a coin) with a hospital cross emblem on its front face and a smaller shield emblem on its back — the entrance spins it a full 360° (decelerating ease) while it pops in (overshoot ease on scale), revealing both emblems before it settles front-facing (cross forward); idles afterward with a gentle sway + bob and an orbiting lavender ring. Respects `prefers-reduced-motion`. Was a bare placeholder div before 2026-08-29.
  - **Login page color palette (added 2026-08-29):** plum `#6528D9`, lavender `#C4B5FD`, off-white `#FAF7FF` — a fixed brand palette for the split-screen login layout (dark plum brand panel, off-white form panel), deliberately independent of the `--accent` purple the authenticated dashboards use (see `App.css`'s `.login-page` custom properties).
- Ledger: Python's built-in `hashlib`
- Behavioral matching reference: adapt `abhijeet3922/User-Verification-based-on-Keystroke-Dynamics` (GitHub) rather than building matching math from scratch
- Fingerprint matching: SourceAFIS
- Hosting: originally scoped as local-only demo; superseded 2026-08-24 — user opted for free cloud hosting so teammates can reach it remotely, not just on local Wi-Fi. Backend on Render (Postgres, not SQLite — Render's free disk is ephemeral), frontend on Vercel. `backend/.env.example` documents the env vars Render needs (`SECRET_KEY`, `DEBUG=False`, `DATABASE_URL` auto-set by Render's Postgres link). Frontend reads the backend URL from `VITE_API_BASE_URL` (Vercel env var) — see `frontend/src/api/client.js`.
- Dev environment: Windows. Use the `py` launcher for Python, not `python` (Windows Store alias intercepts the bare command). Node.js LTS + npm installed via winget on 2026-08-24.

## Timeline & scope commitment

- User has roughly 2–4 weeks until the hackathon deadline (as of 2026-08-24).
- The bonus fingerprint layer (MedGuard Identity, step 7) is **committed to, not conditional** — the user explicitly wants to attempt it. Scope steps 1–6 tightly enough to leave real time for it, but still do not start step 7 before steps 1–6 are solid — nothing in step 7 depends on it, but everything else has no dependency on step 7 either, so build order stays as specified below.

## Enrollment data — do not generate, wait for the user

The user will supply their own staff, patient, and fingerprint enrollment data directly. **Do not create synthetic, placeholder, or example datasets for any of these** — no example staff rows, no generated patient records, no public fingerprint datasets (e.g. do not use SOCOFing, Synthea, or similar substitutes). Build the schemas and the code paths that will consume this data, but leave the actual data population until the user provides it. If a schema decision is needed before the user's data arrives, ask rather than inventing example rows to fill the gap.

## Pending — not yet provided by the user

- Staff, patient, and fingerprint enrollment data (see above — will be supplied directly by the user)

## Working style for this project

- This is the user's first time coding a real project. Prefer plain-English explanations of what changed and why over dense technical jargon in your responses back to them.
- Use Plan Mode before implementing non-trivial features — this project has many interlocking pieces (role access × score bands × ledger × offline sync), and getting the plan reviewed first matters more here than on a simple app.
- When a decision isn't covered by this file, ask rather than assume — do not silently expand scope beyond what's specified above.
