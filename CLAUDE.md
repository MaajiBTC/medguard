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
| Doctor | 1–13 (full) | No conditions |
| Nurse | 1–13 (full) | **Two paths, different outcomes — see Nurse rule below** |
| Pharmacist | 1, 4, 5, 6, 7 (full) | No conditional access |
| Lab technician | 1 only | No conditional access |
| Clerk | 1, 2 only | No conditions |

**Nurse rule (specific override — implement exactly this logic, it does not follow the generic role-ceiling pattern above):**
1. Nurse is specifically assigned to this patient → full access (1–13) granted normally, processed through the standard score-band system like any other access.
2. Nurse is **not** specifically assigned to this patient, but is on the **same ward** as the patient → full access (1–13) is still granted, but this access is **always** logged as `AUDITED_DEVIATION`, regardless of what the aggregate score would otherwise indicate.
3. Nurse is neither assigned to the patient nor on the same ward → falls through to the standard scoring process using the generic bands below (this will typically score poorly on the ward/duty factors and land in reduced or denied territory).

**This does not bypass the hard behavioral-mismatch gate** (see Scoring Engine) — a proven behavioral mismatch still overrides and denies access even in cases 1 and 2 above. The gate always takes precedence over any role-specific ceiling rule.

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
- **Keystroke:** dwell time (per key), flight time (up→down between keys), down-down time, total duration. Capture via `keydown`/`keyup` listeners, store raw timestamped events — do not pre-compute derived features in this module.
- **Mouse:** movement trajectory (coordinate stream), speed, acceleration, click duration, click interval, double-click interval, idle time. Capture via `mousemove`/`mousedown`/`mouseup`, ~10–20ms sampling on movement.
- **Touch:** tap duration, swipe speed/path, interval between taps, pressure/contact size if hardware supports it. Capture via `touchstart`/`touchmove`/`touchend`.

Output format: a `BehavioralCapture` record per session containing raw event arrays for whichever signal types are relevant to that device (empty array for non-applicable types).

## Contextual Signal Capture Module — spec summary

Captures only, simple lookups, no scoring:
- Login timestamp
- Device ID/type/user-agent
- Location — network segment/ward (no GPS; hospital desktops)
- On-duty status — lookup against the staff table
- Ward assignment — lookup against the staff table (which ward the staff member is generally assigned to)
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
2. Combined Scoring Engine (needs both modules' output)
3. **Security Ledger — build immediately after the Scoring Engine, not last.** Every subsequent component should write into it as it's built, rather than retrofitting logging later.
4. Main UI with role-based category slicing (staff search → view flow: search by hospital number or name → display only the categories/access level the combined decision permits)
5. Emergency Override (wired to Ledger)
6. Offline Mode (wraps steps 1–5)
7. Bonus: MedGuard Identity — fingerprint matching, emergency/offline lookup only

**Do not populate the database with any staff, patient, or fingerprint data until the user supplies it** — see Enrollment data below.

## Tech stack (finalized with the user 2026-08-24)

- Backend: Python + Django (+ Django REST Framework for the API layer, since the frontend is a separate React app, not Django templates)
- Database: SQLite
- Frontend: React + three.js
  - three.js is scoped to two places only: the **Security Dashboard visualization** and the **login/landing page**. Do not use it in the functional record-access screens (search, category views, etc.) — keep those plain React for clarity and performance.
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
