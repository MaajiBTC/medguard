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

**Amended (2026-08-30, sidebar restructure):** the Ledger live feed's old
inline staff-ID/patient-hospital-number text filters moved out into two new
sidebar destinations, **Staff** and **Patients** (`SecurityDashboard.jsx`'s
`navItems` becomes Ledger / Staff / Patients / Admins). Both are search-only,
not a role/ward category-tile breakdown like the Admin dashboard's equivalent
pages — search, pick a result, see their "activity": the same
`GET /api/ledger/entries/` feed the old filters produced, filtered to that one
staff member or patient and rendered through a shared `LedgerEntriesFeed`
component (also reused by the Ledger page itself). A patient's "activity" is
really the staff-access events that targeted them, since patients don't log
events of their own — kept as its own page anyway, per the user.
`staff.views.StaffSearchView` widened from `IsAdmin` to
`IsAdminOrSecurityOfficer` so the new Staff page can reuse it directly.
`LedgerVisualization.jsx`'s 3D panel also moved (same day) from placing
markers by their index in the entries array to a real-time-based spiral/helix
— a marker's angle, radius, and height driven by how long ago
`entry.occurred_at` actually was, so recency read as physical distance along
the spiral instead of just color brightness.

**Amended again (2026-08-30, chart cards replace the spiral):** the spiral
above was itself replaced the same day, per the user — `LedgerVisualization.jsx`
is deleted. In its place, the Ledger page shows two `.ledger-chart-card`s side
by side (`frontend/src/pages/LedgerCharts3D.jsx`, still three.js, still one of
CLAUDE.md's two sanctioned three.js spots): a 3D donut (`LedgerDonutChart3D`,
extruded annulus segments sized by each of the 4 non-`STANDARD_ACCESS` event
types' share of the current feed, using the same severity colors already used
elsewhere on this page) and, on the left, an HTML legend underneath each
chart since this is the first place on the page that needed one explicitly.
Both grow in on first mount and pulse when the polled data actually changes
(compared via a cheap entries signature, so an unchanged re-poll doesn't
visibly re-trigger anything) — same `easeOutBack` entrance easing already
used for the login shield in `LoginScene.jsx`.

**Amended a third time (2026-08-30, role bar chart + white/plum cards):** the
left card changed again the same day, per the user — it's now a horizontal
bar chart of Ledger activity broken down by **staff role** (Doctor/Nurse/
Pharmacist/Lab Technician/Clerk), not event type over time. This needed a
small `ledger` app addition: `LedgerEntry.staff_role` (new denormalized
field, same reasoning as `staff_full_name` — the Ledger can't hold a foreign
key to `Staff`, and **not** part of `_compute_entry_hash()`'s payload,
matching how `staff_full_name` was never hashed either), populated by
`ledger.services.record_event()` alongside the other denormalized staff
fields. Both `.ledger-chart-card`s also switched from lavender to **white
with a 1px `var(--plum)` border**.

**Amended a fourth time (2026-08-31, 2D + heat-scale coloring):** the bar
chart itself changed the very next day, per the user — `LedgerRoleBarChart`
(`frontend/src/pages/LedgerCharts3D.jsx`) is now plain 2D CSS (a
`div`-and-width-percentage bar per role, `transition: width` for the
grow-in), not three.js — so this panel now holds one three.js visual
(`LedgerDonutChart3D`) and one plain-CSS one side by side. Bar color is a
red/orange/yellow/green heat scale keyed to that role's count relative to
the busiest role in the current feed (red = busiest), not the flat plum used
before — a deliberate departure from the severity palette, chosen by the
user specifically for this chart.

**Amended a fifth time (2026-08-31, STANDARD_ACCESS shown + exact severity
palette):** `STANDARD_ACCESS` is no longer hidden from the Ledger live feed
by default (`SecurityDashboard.jsx`'s `LedgerPanel` used to filter it out
client-side unless explicitly selected; that filter is gone, and the
event-type dropdown's "not normally shown" label is gone too, per the user).
The 5-event-type severity palette is now an exact fixed set the user
specified: `STANDARD_ACCESS` `#00CC00`, `AUDITED_DEVIATION` `#FFFF00`,
`REDUCED_ACCESS` `#FF9300`, `ACCESS_DENIED` `#FF0000`, `EMERGENCY_OVERRIDE`
`#0000FF` — used as-is for `LedgerDonutChart3D`'s slices/legend
(`LedgerCharts3D.jsx`'s `SEVERITY_COLOR`/`SEVERITY_LABEL`, now including
`STANDARD_ACCESS`) and, in `App.css`, as a **left-edge border stripe** on
each live-feed row rather than text color — `#FFFF00` as running body text
on a white row would be close to unreadable, so the exact hex still shows
(as a stripe) but body text stays its normal readable color.

**Amended a sixth time (2026-08-31, distinct row-cards):** `LedgerEntriesFeed`
(`SecurityDashboard.jsx`, shared by the Ledger live feed and the Staff/Patient
activity pages) is no longer a single `<table>` sheet — each entry renders as
its own white, rounded `.ledger-row-card`, with a gap between rows, sitting
inside a light-tinted `.ledger-feed` tray (`#f3effc`) so the individual cards
read as visually distinct from each other and from the header row above them
— same "one card per row" language `.card-row` already uses for Staff/Patient
lists elsewhere in this app, just with more columns (CSS grid, not flex).
Column alignment (`#`/Date-Time/Event/Staff/Patient) comes from a shared
`grid-template-columns` on `.ledger-row-card` rather than table cells; the
severity stripe from the previous amendment moved from `td:first-child` to
the row-card's own `border-left`.

**Amended a seventh time (2026-08-31, chart card titles + donut layout):** the
two `.ledger-chart-card`s' background/border stay the original white/plum
(an in-session attempt to make the whole card plum was corrected by the
user — only the **title text** gets a small plum background chip
(`.ledger-chart-card h3`: `display:inline-block`, plum background, white
text), not the card itself. The bar chart's title changed to "Staff Role"
(Title Case, per the user); the donut's stays "Event breakdown". The donut
card's `Legend` and its three.js mount now sit side by side in one row
(`.donut-chart-row`, new) — legend on the left, donut shifted right into the
freed space — rather than the legend stacked underneath, mirroring how the
bar chart already puts each role's label beside its bar in one row. The
donut itself is sized up (`OUTER_R`/`INNER_R` from 1.7/0.9 to 1.95/1.05 in
`LedgerCharts3D.jsx`) without changing `.ledger-chart-mount`'s footprint.

**Amended an eighth time (2026-08-31, two summary cards on Staff/Patients/
Admins):** the Ledger page's own two cards now also appear at the top of the
other three Security-dashboard pages, updating based on what's selected.
`LedgerCharts3D.jsx`'s `LedgerRoleBarChart` was split into a generic
`HorizontalBarChart({ rows })` plus a new `EventTypeBarChart` (same bars,
event-type data + the exact severity colors instead of role data + the heat
scale). On the **Staff**/**Patients** pages (`ActivityLookupPanel` in
`SecurityDashboard.jsx`), before anything's selected both cards are
system-wide and identical to the Ledger page's (`LedgerRoleBarChart` +
`LedgerDonutChart3D`, fetched via `getLedgerEntries({})` unfiltered); once a
specific staff member or patient is selected, Card 2 switches to
`EventTypeBarChart` (bars, not the donut, per the user's explicit
correction) scoped to that entity, and Card 1 switches to something
per-page-specific: Staff gets `StaffDetailsCard` (name/ID/role/ward/duty from
the already-available search result, no new backend data), Patients gets
`StaffAccessCountCard` (count of *distinct* `staff_id`s among that patient's
entries, computed client-side — `new Set(entries.map(e => e.staff_id)).size`,
no new backend endpoint). The existing search box now renders below the two
cards instead of above (this is what "drop it down a little" meant). On
**Admins** (`AdminsPanel`), the two cards are unrelated to the Ledger — per
the user, admin accounts don't generate scoring-pipeline Ledger events for a
role/event-type breakdown to mean anything there, so both cards reuse the
exact summary data the Admin dashboard's own Overview page already shows
(`getPatientSummary()`/`getStaffSummary()`, both already-built endpoints, no
backend changes): "Patients" (total + `by_ward`) and "Staff" (total, on-duty/
on-call, `by_role` excluding admin/security_officer). New small
`SummaryCard`/`big-stat` presentational pattern shared by both.

**Amended a ninth time (2026-08-31, admin activity audit trail + Ledger page
slicers):** two changes, confirmed via `AskUserQuestion`. First, a new
`staff.AdminActionLog` model (denormalized actor/target fields, no FK — same
reasoning as `ledger.LedgerEntry` and `scoring.DisasterModeEvent`: a target
row can be deleted, one of the four actions being logged, without losing the
record, and an actor can't erase evidence of their own action by later being
deleted) records **staff account lifecycle only** — create, deactivate,
reactivate, delete — via a single writer, `staff.services.record_admin_action()`,
called from `StaffCreateView`/`StaffDeactivateView`/`StaffReactivateView`/
`StaffDeleteView`. Lives on the default database, not the Ledger's separate
one — this is staff-management audit, not the security-critical access-decision
trail, so it doesn't need the Ledger's hash-chain/append-only machinery.
Logging starts from when this shipped; past actions aren't recoverable. New
`GET /api/staff/admin-actions/?actor_staff_id=` (`IsAdminOrSecurityOfficer`).
The **Admins** page (`AdminsPanel`, replacing the eighth amendment's
Patient/Staff-summary-reuse version above, since the user actually wanted to
see individual admin accounts, not aggregate counts) now works like the
Staff/Patients pages: search (`searchStaff(q, 'admin')`) → select → two cards
— `AdminDetailsCard` (name/staff_id, no ward/duty, admins are
`NO_WARD_DUTY_ROLES`) and `AdminActivityCard` (that admin's own
`AdminActionLog` entries as actor, newest first, a plain list not a
chart — discrete events, not count data). Second, the **Ledger** page's two
cards gained three filter "slicers" forming **one shared filter set**
(confirmed) that narrows the same `entries` feeding both cards *and* the live
feed table below: a role `<select>` (`ROLES`, now exported from
`LedgerCharts3D.jsx`) plus the pre-existing event-type `<select>` moved into
the "Staff Role" card's header, and two `<input type="date">` (from/to) in
the "Event breakdown" card's header. Backend: `ledger.views.LedgerFeedView`
gained a `staff_role` query param filter (mirrors the existing `staff_id`
filter pattern); `since`/`until` already existed. 46/46 new/scoped backend
tests passing, full suite green; migration applied to the real dev database
(default connection this time, not `ledger` — no `--database=ledger` needed).

**Amended a tenth time (2026-08-31, Admins page default cards restored):**
same day, the user asked to bring back the eighth amendment's bar+donut
default look on **Admins** — confirmed via `AskUserQuestion` that they
wanted both: the system-wide bar+donut cards by default (matching
Staff/Patients exactly), *and* to keep clicking into one admin's Details +
Activity from the ninth amendment. `AdminsPanel` now fetches `entries` via
`getLedgerEntries({})` (unfiltered, system-wide) whenever nothing's
selected and renders `LedgerRoleBarChart`/`LedgerDonutChart3D` under the
"Staff Role"/"Event breakdown" titles — same component, same data, same
titles as `ActivityLookupPanel`'s unselected state — then swaps to
`AdminDetailsCard`/`AdminActivityCard` under "Admin Details"/"Activity" once
an admin is selected, exactly as the ninth amendment already had it. Not
merged into `ActivityLookupPanel` itself, for the same reason the ninth
amendment gave: the selected-state data source (`AdminActionLog`) doesn't
fit that component's Ledger-entries-only shape.

**Amended an eleventh time (2026-08-31, Staff page slicers + rename):**
same day, per the user, confirmed via `AskUserQuestion`. The **Staff**
page's default left card (previously "Staff Role", same as every other
page's) is renamed to **"Staff Activity"** — Staff-page-only, via a new
`cardOne.defaultTitle` override on `ActivityLookupPanel` (falls back to
"Staff Role" everywhere else, so Ledger/Patients/Admins are unaffected).
`ActivityLookupPanel` gained an opt-in `activityFilters` prop (Staff page
only) adding, in its unselected system-wide state: a role `<select>` +
on-duty-status `<select>` (All / On duty / Off duty / On call) in the
"Staff Activity" card's header, and the same from/to date `<input
type="date">`s the Ledger page's "Event breakdown" card already has in
this card's header — no event-type filter here, per the user's explicit
scope (just role + duty on the left, dates on the right). Role and date
narrow the `getLedgerEntries()` call itself (`staff_role`/`since`/`until`,
same as the Ledger page). On-duty status has no equivalent field on
`LedgerEntry`, so per the user's explicit choice it filters by each
matching staff member's **current** live on-duty/on-call status (looked up
via `searchStaff('', roleFilter)` and cross-referenced by `staff_id`) —
not their duty status back when each historical event happened. These
slicers only render and apply in the unselected state; once a specific
staff member is selected the cards behave exactly as before (unaffected by
this change).

**Amended a twelfth time (2026-08-31, Patients page slicers + rename):**
same day, per the user, confirmed via `AskUserQuestion`. The **Patients**
page's left card is renamed to **"Patient Record Activity"** — via
`cardOne.defaultTitle` *and* `cardOne.selectedTitle` both set to that same
string, so unlike the Staff page (title changes on selection) this one
stays constant whether browsing system-wide or looking at one patient.
Gets the same role + on-duty-status slicers (left) and date-range slicers
(right) the eleventh amendment added to the Staff page, via the same
`activityFilters` prop — but here they're also live once a patient is
selected (new `filtersApplyWhenSelected` prop on `ActivityLookupPanel`,
Patients-only), per the user's explicit choice: narrowing to "just doctors"
or "just on-duty staff" who accessed that one patient's record, not only
the system-wide default view. `ActivityLookupPanel`'s `fetchEntries`
unified around one `filtersActive = activityFilters && (!selected ||
filtersApplyWhenSelected)` flag so both pages share the same fetch/filter
code path. Already-existing `buildFilter` scoping
(`patient_hospital_number`) is what keeps this page's entries limited to
record-access events on that one patient in the first place — no change
needed there, per the user's own confirmation this already matched what
they wanted ("just the activity on a patient's record").

**Amended a thirteenth time (2026-08-31, avatar detail layout on
selection):** same day, per the user, confirmed via `AskUserQuestion`.
Once a specific staff member, patient, or admin is selected on the
Staff/Patients/Admins pages, that left card's **title disappears entirely**
and its content becomes a `RoleAvatar` (new `frontend/src/pages/
RoleAvatar.jsx` — one small flat SVG icon per role plus 'admin' and a
single generic 'patient' icon, hand-drawn in the same style as
`DashboardShell.jsx`'s sidebar icons, no downloaded images per the user) at
~30% width beside that entity's vertically-stacked detail fields (`.entity-
detail-row`/`.entity-detail-avatar`/`.entity-detail-info` in `App.css`).
This **replaces** the twelfth amendment's `selectedTitle`/
`filtersApplyWhenSelected` mechanism (now removed) with a simpler, uniform
rule applied identically across all three pages: the **role** slicer only
shows/applies in the unselected system-wide view ("of no importance" once
one specific entity is already picked, per the user) while the **duty-
status** slicer stays visible and functional in both states (new shared
`filterEntriesByDuty()` helper + `DUTY_OPTIONS`, used by both
`ActivityLookupPanel` and `AdminsPanel`); the date-range slicers stay
unselected-only, unchanged. The Patients page's card title is simplified
back to always reading "Patient Record Activity" via `cardOne.defaultTitle`
alone (no more separate `selectedTitle`). Its `renderSelected` also
changed: `StaffAccessCountCard` (the old sole content) is replaced by a new
`PatientDetailsCard` showing the patient's own identity fields (full
name/hospital number/ward from `PatientSummarySerializer` — **phone number
and address are deliberately not shown**, since those live in category 1
behind the full scoring/access-decision flow, not this lightweight search
endpoint, and exposing them here would let a Security Officer see patient
PII without going through access control) plus the old distinct-staff-count
line folded in underneath. The **Admins** page gained the same role+duty
slicers on its previously-slicer-less unselected view, and the same
avatar-layout treatment on selection (`RoleAvatar role="admin"` beside
`AdminDetailsCard`) — but with **no duty slicer** in its selected state,
a deliberate exception: admin accounts are `Staff.NO_WARD_DUTY_ROLES` (no
on-duty/on-call concept at all), and that page's right card in the selected
state is `AdminActivityCard` (`AdminActionLog` entries), not Ledger data a
duty slicer could narrow in the first place.

**Amended a fourteenth time (2026-08-31, mascot-style avatars):** same day,
per the user, confirmed via `AskUserQuestion`. The user shared a 3D-rendered
stock photo (a cartoon doctor character) as a reference for what they
wanted `RoleAvatar` to look like — since that exact image is a watermarked,
copyrighted stock illustration and there's no way to generate a real 3D
render, `RoleAvatar.jsx` was rebuilt as hand-drawn flat-cartoon "mascot"
SVGs instead (still no downloaded/generated images): a shared `Head`
(skin-tone circle, gloss highlight, hair shape, dot eyes, blush cheeks,
smile) reused across all 7 characters, each varying only hair color, an
outfit-colored collar/coat shape, and a small role prop — stethoscope
(doctor), nurse cap with a cross (nurse), a small pill capsule (pharmacist),
safety goggles (lab technician), a purple tie (clerk), a shield pin on a
dark suit (admin), a plain gown with a small heart stitch (patient, the one
generic icon per the existing rule). Prototyped and visually tweaked in a
standalone HTML file served locally before porting into the component, to
avoid iterating blind. Verified live in-browser (Claude-in-Chrome, logged
in as the real security officer account): the doctor mascot renders
correctly on the Staff page for the real `282828` account, and the admin
mascot renders correctly on the Admins page for the real `ADMIN-1` account.
No console errors.

**Amended a fifteenth time (2026-08-31, avatar face v2 + bigger + resized
layout):** same day, the user shared two more reference images (a 3D
doctor and nurse) and asked for a closer match plus a much bigger avatar
with the details column pushed further right. The two reference images are
also watermarked stock illustrations (pngtree) — same copyright block as
the fourteenth amendment — so `RoleAvatar.jsx`'s shared `Head` component
was instead redrawn bigger/more expressive within the existing hand-drawn-
SVG approach: larger two-tone eyes (white sclera + iris + highlight dot)
and visible eyebrow arcs, applied to all 7 characters. The **nurse**
specifically dropped her cap in favor of a side ponytail (a simple curved
shape trailing from behind the head) plus a stethoscope like the doctor's,
matching the reference's no-cap look. `App.css`: `.role-avatar`'s
`max-width` raised from 84px to 190px (more than double, per the user) and
`.entity-detail-avatar`'s flex-basis raised from 30% to 46% so the details
column starts further right to match. Prototyped in the same local-HTML-
preview workflow as the fourteenth amendment before porting in. Verified
live in-browser against the real `282828` doctor account — bigger avatar,
new face, details shifted right, no console errors.

**Amended a sixteenth time (2026-08-31, bold-outline redesign):** same day,
the user shared two more references (a photorealistic doctor photo, then a
flat-vector clip-art doctor illustration) and asked to "use" each. The
photo was declined for the same copyright reasons as before, plus a
second, distinct concern this file hadn't previously recorded: a real (or
realistic) human likeness raises publicity/consent issues beyond copyright,
independent of any watermark. The clip-art illustration was also declined
(same copyright reasoning — professional stock clip art, licensing
unverifiable, regardless of whether a watermark happens to be visible in
a given crop), but its bold-outline flat-vector style was judged genuinely
achievable by hand, unlike the photo. `RoleAvatar.jsx` was redrawn with a
consistent dark outline (`OUTLINE = "#241a30"`, stroke-width ~1.2–1.8) on
every shape across all 7 characters, plus a shared `hairPath` (a cleaner
side-part swoop, extracted as `SIDE_PART_HAIR` and passed into `Head`
alongside `hair`/`skin`, replacing the single inline hair path each
character drew before) and, on the **doctor** specifically, a chest pocket
with three pens and a redraped stethoscope resting closer to the pocket,
matching the reference's composition. The user then asked for "a much more
realistic" avatar; declined on hard technical grounds (this project only
produces SVG markup — vector shapes and gradients — with no image-
generation capability available, so pixel-level photorealism isn't
reachable regardless of how much the vector style is refined) rather than
a preference call, and offered gradient-based shading as the closest
achievable next step if pursued further. Prototyped in the same local-
HTML-preview workflow before porting in; verified live in-browser against
the real `282828` doctor account, no console errors.

**Amended a seventeenth time (2026-08-31, full-bleed avatar):** same day,
per the user — each avatar was floating in the middle of its circular
badge with a visible flat seam at the chest/shoulders where the coat shape
ended short of the badge's edge, leaving the plain `--lavender` background
showing around it. `RoleAvatar.jsx`'s per-character body/coat path (was a
narrow, fixed-width shape only spanning roughly the middle 44% of the
viewBox) replaced with one shared `BODY_PATH` whose shoulders rise all the
way to the viewBox's left/right edges before dipping to the neckline, so
the outfit bleeds fully under the badge with no gap regardless of the
badge's render size. `App.css`: `.role-avatar` gained `overflow: hidden`
(so it now genuinely clips to the circle rather than relying on the SVG's
own bounds) and its `svg` rule changed from `width/height: 62%` to `100%`
so the character fills the whole badge instead of floating with padding on
every side; each character's `<svg>` also gained
`preserveAspectRatio="xMidYMid slice"` for robustness. Prototyped in the
same local-HTML-preview workflow before porting in; verified live
in-browser against both the real `282828` doctor and `ADMIN-1` admin
accounts — full bleed, no seam, no console errors.

**Amended an eighteenth time (2026-08-31, labeled detail fields + list
shown by default):** same day, per the user, confirmed via
`AskUserQuestion`. Two changes to the Staff/Patients/Admins pages:

1. Every field on the three detail cards (`StaffDetailsCard`,
   `PatientDetailsCard`, `AdminDetailsCard`) now gets its own "Label:
   value" line via a new shared `DetailField({ label, value })` component
   — previously some fields (name, staff ID + role combined) had no label
   at all. `.detail-label` in `App.css` bolds the label in `--plum-deep`.
2. All three pages now show their full list the moment the page loads —
   previously you had to search first (an empty `results` state) before
   anything appeared, same problem on all three. `ActivityLookupPanel`
   (Staff/Patients) and `AdminsPanel` both gained a `fetchResults`
   function called from a `useEffect` on mount/whenever `selected` clears,
   not just on explicit form submit. Both also gained a **list filter**
   dropdown rendered below the search bar (`.list-filter-select`) that
   re-triggers `fetchResults` the moment it changes, no search-submit
   needed — role for Staff (`ROLES`), ward for Patients (`WARDS`, imported
   from `wards.js`), matching the exact "select doctor, only see doctors,
   no searching" behavior the user asked for. Admins gets the
   show-by-default behavior too but no dropdown (confirmed out of scope —
   admin accounts are already all one role, a role filter there would be
   trivial). Both `searchStaff(q, role)` and `searchPatients(q, ward)`
   already supported the second filter param server-side from earlier
   work, so no backend changes were needed. Verified live in-browser
   (Claude-in-Chrome) against the real `282828` doctor and `ADMIN-1` admin
   accounts: both pages list everyone on load, the Staff role dropdown
   narrows the list instantly without pressing Enter, and the labeled
   detail card renders correctly. No console errors.

**Amended a nineteenth time (2026-09-03, "MedGuard AI explanation" on the
live feed):** the Ledger live feed's row drilldown (raw `entry.details`
JSON) gained an AI-generated plain-English translation next to it, per the
user — planned via Plan Mode, approved plan at
`.claude/plans/greedy-humming-graham.md`. The user explicitly chose Google
Gemini over the Claude API for this (they already had a Gemini key; intend
to switch to a paid Claude API key "when I buy it for the competition" —
noted here so a future session doesn't assume Gemini is the permanent
choice). New `ledger/gemini.py`: `explain_entry(entry)` builds a prompt
from the entry's denormalized fields + `details` JSON and calls Gemini's
REST `generateContent` endpoint directly via `requests` (new dependency —
no official SDK installed, a single call didn't justify one), reading
`settings.GEMINI_API_KEY`/`GEMINI_MODEL` (env-configured, `.env.example`
documented, real key lives only in the gitignored `backend/.env`) with a
45s timeout and one automatic retry on a timeout/connection blip — observed
Gemini latency for this prompt size varies widely in practice (14s-30s+ for
the *same* request back to back), and separately, free-tier Gemini keys
are subject to real 429 rate-limiting that surfaces as a normal error-panel
state, not a bug. New `POST /api/ledger/entries/<sequence>/explain/`
(`LedgerEntryExplainView`, `IsSecurityOfficer`-gated) returns
`{explanation}` or a 502 with a message — **never persisted**, generated
fresh every call, since an AI's paraphrase of a decision is not part of
the audited Ledger record. Frontend: `LedgerEntriesFeed`'s drilldown
becomes a `.ledger-drilldown-split` two-column layout the moment a row
expands (raw JSON left, `.ledger-ai-panel` right) — but per the user's
explicit correction, that panel only *fires the request* on an explicit
"Explain with AI" click; an earlier version that auto-fetched the moment a
row expanded was tried and reverted the same day, since the user did not
want an automatic API call just from opening a row. Panel header reads
"✨ MedGuard AI explanation" (also renamed same day, per the user). 17/17
`ledger` app tests passing (4 new, `gemini.explain_entry` mocked so the
suite never makes a real network call). Verified live end-to-end via the
Claude-in-Chrome extension against a real Ledger entry and the real
security officer account, including a real Gemini 429 rendering correctly
through the existing error state.

## Patient SMS Notifications (added 2026-09-14, the user's own idea)

Not originally in this file's spec — the user's own extension once the core
system was built, tying back to the competition's own title ("Safe Access
to Patient Records"): the patient is part of securing their own data too,
not just staff/security officers. When a patient's record is accessed in
any way CLAUDE.md's own scoring bands already treat as noteworthy
(`AUDITED_DEVIATION`, `REDUCED_ACCESS`, `ACCESS_DENIED`,
`EMERGENCY_OVERRIDE`), the patient gets a real SMS via Twilio. A clean,
silent `STANDARD_ACCESS` stays silent for the patient too, matching the
Scoring Engine's own existing "silent unless something's off" convention.

New `notifications` app: `PatientNotification` (real FK to `Patient` — this
app lives on the default database, not a separate one the way `ledger`
does) records every *attempt*, sent or not — kept even when Twilio isn't
configured or the patient has no phone on file, so the feature is honestly
demoable before real credentials exist, and doubles as its own lightweight
audit trail after. `notifications.services.notify_patient()` is the single
writer (same convention as `ledger.services.record_event()`/
`alerts.services.raise_alert()`), looks up the patient's phone from their
own category 1 structured `phone` field (no new patient field needed), and
POSTs directly to Twilio's REST API via `requests` (no SDK, same precedent
`ledger/gemini.py` already set for Gemini) — **deliberately never raises**,
unlike `gemini.explain_entry`: this runs as a background side effect of an
access decision, not a user-initiated action, so a missing config, a
missing phone number, or an unreachable Twilio must never break the
clinician's actual decision response. Every outcome is still recorded.
Called from the exact three places that already call `record_event()` for
these event types: `scoring.views.DecideView`, `scoring.views.
EmergencyOverrideView` (unconditionally — every BTG is a trigger type
already), and `offline_sync.views.OfflineSyncView`'s merge loop (fires when
the device reconnects and syncs, not backdated to the original offline
timestamp). New settings `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/
`TWILIO_FROM_NUMBER` (all optional, unset by default — friendly "not
configured" fallback). A Twilio trial account can only text numbers
verified in the Twilio console, and prefixes every message with "Sent from
your Twilio trial account" — expected trial behavior, not a bug.

10 new backend tests (5 in `notifications` app's own suite, 5 integration
checks added to `scoring`/`offline_sync`), `requests.post` always mocked so
the suite never makes a real network call. Verified live against the real doctor
account and the one real patient: a genuine 70% `AUDITED_DEVIATION`
decision correctly triggered `notify_patient()`, which correctly recorded
"no phone number on file" (Identity category 1 is still empty for this
patient — real missing data, not a bug) without affecting the clinician's
own decision response at all. **Still needed:** the user supplying a real
phone number for the real patient (via the Admin dashboard's existing
Identity category editor) and real Twilio credentials, to verify an actual
SMS arrives.

## Visual + Navigation Redesign (added 2026-09-18)

Not part of this file's original spec — the user asked for the whole
frontend to "look professional," confirmed via `AskUserQuestion` to include
layout/navigation restructuring, not just a CSS polish pass. Planned via
Plan Mode after three parallel research passes read every frontend file in
full (rather than guessing at structure) and the `ui-ux-pro-max` skill's
`--design-system` search grounded the direction in real guidance: a first
query skewed toward marketing/wellness patterns and was discarded per the
skill's own "verify fit" instruction; a retry with "internal admin
dashboard SaaS data-dense B2B tool" returned a genuine match — **Data-Dense
Dashboard** style (grid layouts, KPI cards, tight tables) with **Fira Sans /
Fira Code** typography. Brand colors (`--plum #6528d9`, `--plum-deep
#2a0f5c`, `--lavender #c4b5fd`, `--off-white #faf7ff`) are unchanged —
every hex value is byte-for-byte identical to before.

The research found `App.css` (1574 lines, the single shared stylesheet for
the whole app) had exactly 4 custom properties total, all color — zero
spacing/radius/typography tokens, every other value a hand-picked literal
repeated inconsistently. Fixed across 5 phases, each lint/build-verified:

**Phase 1 — tokens + typography.** Added semantic aliases on top of the 4
existing brand colors (`--color-primary`/`--color-surface`/`--color-text`/
`--color-border`/etc.), named the 3 alert-color families that already
existed as scattered literals (`--color-danger`/`--color-warning`/
`--color-notice`/`--color-override`), and named the Security Ledger's 5
exact severity hexes as `--severity-*` (values unchanged — CLAUDE.md pins
these to an exact user-specified palette; `LedgerCharts3D.jsx`'s three.js
color map can't consume a CSS var, so it stays its own literal JS constant,
now documented as the one place these 5 values must be kept in sync by
hand if they ever changed). Added a 4/8-based spacing scale and a radius
scale naming values the literals already clustered around. Added
`--font-sans` (Fira Sans, loaded via `index.html`'s Google Fonts `<link>` —
the app previously had no font-family declared anywhere, pure browser
default) as the base body font, and `--font-mono` (Fira Code) applied to
code-like UI: the step-up `.assist-code-display`/`.assist-code-input` and
the Ledger drilldown's raw-JSON `<pre>`. Converted all 37 `font-size`
declarations from px to rem (base 16px) — the file previously mixed px and
rem with no rule.

**Phase 2 — unified card/heading/status-banner patterns.** Aligned
`.panel-card`/`.card-row`/`.detail-block`/`.ledger-chart-card`'s
radius/padding to the new scale (previously each had drifted to its own
nearby-but-different pixel values); `.ledger-chart-card` deliberately keeps
its own bolder plum border as an intentional second tier for
data-visualization cards, not flattened into the others. Fixed
`SecurityDashboard.jsx`'s `AdminsPanel` card-2 header (was a bare `<h3>`
with no `.ledger-chart-card-header` wrapper, unlike every other
chart-card header in the app). Gave the 4 decision-outcome classes
(`.access-denied/.access-reduced/.access-audited/.access-override` —
previously bare colored text with no box at all) a shared banner treatment
(tint background + left accent bar via `currentColor`) — deliberately NOT
applied to `.dev-error`/`.notice`, which are also used for small inline
field-level errors where a full banner box would be too heavy.
`.btn-danger` now composes off the same shared base selector
`.btn-primary`/`.btn-secondary` already used instead of re-declaring it
(this also fixed a real small gap: `.btn-danger:disabled` had no style at
all before). `RoleAvatar.jsx`'s `AdminIcon` — the only mascot using brand
colors for its outfit — now reads `var(--plum-deep)`/`var(--lavender)`/
`var(--plum)` for its 3 fills instead of repeating the hex directly in SVG
markup (same rendered color, one source instead of two).

**Phase 3 — navigation restructure.** The one dashboard with a real gap:
`ClinicalDashboard.jsx` previously passed `DashboardShell` a single static
nav item with a no-op `onNavChange`, making the sidebar decorative for 5 of
6 roles, while the old `AssistRequestsBanner` (colleague step-up requests)
rendered inline at the top of every page load whether or not there was
anything to see. Now a real 2-page nav — **Patients** (default, today's
find-a-patient/ward-browse/record flow, unchanged) and **Colleague
Requests** (the same banner's content, now its own page) — mirroring the
`navItems`/`badgeCount` pattern `SecurityDashboard.jsx` already established
for its own Alerts page. The polling/fetch state that used to live inside
the banner component now lives in `ClinicalDashboard` itself (renamed
`ColleagueRequestsPanel`, now a pure presentational component) so the
pending-request count can drive the nav badge regardless of which page is
active — same reasoning `SecurityDashboard.jsx`'s `openAlertCount` already
uses. Unlike the old banner, the new page doesn't self-hide when
empty — it shows "No pending requests right now" instead, since it's a
real page now, not a conditional banner.

**Phase 4 — responsive pass.** CLAUDE.md scopes this app to hospital
desktop workstations ("no GPS; hospital desktops"), not a mobile target, so
this was a modest tablet/small-desktop pass, not full mobile-first
coverage. `.category-grid`/`.overview-grid` were already gracefully
responsive via `repeat(auto-fit, minmax(...))` and needed no change,
confirmed by inspection rather than assumed. Added a 720px breakpoint
(reusing the exact value already established twice elsewhere in the file,
for `.ledger-drilldown-split` and `.shell-header`, rather than introducing
a new one-off number) that stacks `.entity-detail-row` (Staff/Patients/
Admins' avatar-beside-details layout) and `.profile-detail-row` (the
Profile page's photo-beside-fields layout) to a single column — both
previously fixed-width layouts with zero breakpoint at all.

**Phase 5 — verification pass.** Found and fixed one real accessibility
gap while auditing focus-visible coverage: `.search-bar input` removed the
browser's default focus outline (`outline: none`) with nothing replacing
it, so a keyboard user tabbing into any search box in the app got zero
visual feedback that it was focused. Fixed with a `.search-bar:focus-within`
border-color change, same visual language `.login-form input:focus`
already used elsewhere for the same "outline removed, replaced with a
visible border" pattern. `LoginScene.jsx`'s existing `prefers-reduced-motion`
handling was confirmed unaffected (untouched by this pass).
**Not fixed, flagged instead:** `LedgerDonutChart3D`'s pop-in/pulse
animations have no `prefers-reduced-motion` check — a pre-existing gap,
not something this pass introduced, left alone since it's animation logic
inside a three.js scene that's already had many rounds of careful prior
tuning (see the Security Dashboard section's amendment history above) —
out of scope for a visual/navigation redesign pass specifically.

`npm run lint`/`npm run build` clean after every phase. **Live-verified**
in-browser (Claude-in-Chrome, real admin/doctor accounts): Login, Admin
(Overview/Staff/Patients), and Clinical (Patients page, the new Colleague
Requests nav page, decision/record views) all confirmed — no console
errors, no visual regressions, `.search-bar:focus-within` and the new
navigation both render and behave correctly.

**Amended the same day (2026-09-18, elevation + motion pass):** the user
pushed back directly after the first pass — "why is the ui looking so
static like ai made" — and they were right. Root cause, found by grepping
rather than guessing: **zero `box-shadow` declarations anywhere in the
1600+ line stylesheet**, and only a handful of `transition`s, all flat
background-color swaps with no shadow/transform motion at all. Added a
`--shadow-sm`/`--shadow-md`/`--shadow-lg` scale (plum-tinted rather than
pure black, matching the brand instead of looking generic) and a shared
`--ease` timing curve, then applied them across every major surface:
`.panel-card`/`.card-row`/`.ledger-chart-card`/`.detail-block`/`.modal` all
got resting shadows; `.card-row` and all 3 button variants
(`.btn-primary`/`.btn-secondary`/`.btn-danger`) got a hover lift
(`translateY` + bigger shadow) plus a proper `transition` (buttons
previously had none at all — hover was instant). The single biggest fix:
`.category-tile` (the plum ward/role browse tiles — the first thing on
most list-heavy pages) went from a **flat single-color fill with a
`filter: brightness(0.97)` hover** (barely perceptible) to a plum-to-
plum-deep gradient (reusing the same gradient language `.login-brand-panel`
already established) with real resting elevation and a visible hover lift
— confirmed live, the hovered tile visibly separates from its flat
neighbors. `.stat-card-top`/`.stat-card-bottom` (Overview page) got the
same gradient + shadow treatment. Added a blanket
`@media (prefers-reduced-motion: reduce)` rule collapsing every transition/
animation added in this pass to near-zero duration, rather than gating each
one individually. `npm run lint`/`npm run build` clean; live-verified
against the real admin account — the Overview stat cards and Staff page's
"Doctor" tile both show the gradient/shadow/lift clearly against their
flat-before screenshots, no console errors.

**Amended a third time (2026-09-18, charts added to Admin's Staff/Patients
panels):** the user asked for the donut+bar chart pattern Security's
dashboard already has, but on the **Admin dashboard's** Staff/Patients
panels instead — confirmed via `AskUserQuestion` that this was a genuinely
new addition (Admin's panels had no charts before this; only Security's
`ActivityLookupPanel`/`AdminsPanel` did). A second `AskUserQuestion`
resolved a real architecture conflict before writing any code: Security's
donut is three.js, but CLAUDE.md scopes three.js to exactly two places
(Security's own visualization, and the login page) and keeps every other
screen plain React — confirmed the new Admin donut should be a real flat
SVG chart, not three.js, keeping that rule intact rather than silently
breaking it to match Security's look.

Data-wise, these charts read from `getStaffSummary()`/`getPatientSummary()`
— already fetched into `roleCounts`/`wardCounts` state for the existing
category tiles, so no backend changes were needed. New
`frontend/src/pages/DonutChart2D.jsx`: a generic plain-SVG donut over the
same `rows: [{key, label, count, color}]` shape `LedgerCharts3D.jsx`'s
`HorizontalBarChart` already uses (per-segment `<circle>` with
`stroke-dasharray`/`stroke-dashoffset`, rotated -90° so segments start at
12 o'clock, a center total label, and a `.ledger-chart-legend`-styled
legend reusing the exact class names Security's donut legend already
established). `HorizontalBarChart`/`heatColor` (previously internal to
`LedgerCharts3D.jsx`) are now also exported for reuse. `StaffPanel` gets
"Staff by Role" (bar, same heat-scale-by-busyness coloring Security's own
role bar uses) + "Duty Status" (donut: on duty vs. off duty, both counts
derived from `on_duty_by_role`/`by_role` summed over `STAFF_BROWSE_ROLES`
only — deliberately excluding admin/security_officer, consistent with
Staff-browsing already being scoped to the 5 clinical roles elsewhere in
this panel; on-call isn't broken out as its own segment since there's no
clinical-role-scoped on-call count available without a backend change, and
this didn't seem worth one). `PatientPanel` gets "Patients by Ward" (bar)
+ "Ward Distribution" (donut) — deliberately the *same* `by_ward` data
shown two ways (bar for magnitude, donut for proportion) since ward is the
only real second dimension `getPatientSummary()` currently exposes; a new
fixed `WARD_CHART_COLORS` palette (plum-family shades + gray for
unassigned) keeps these visually distinct from the 5 pinned Ledger
severity hues, which mean something different.

**Amended a fourth time (2026-09-18, chart-then-tiles-then-search
ordering):** per the user, both panels' default (nothing selected/
searched) view now orders chart → category tiles → search bar, reversing
the original search-bar-on-top layout. The search bar and error/notice
feedback were extracted into local `searchRow`/`feedback` JSX variables
(not duplicated markup) and conditionally placed: below the tiles in the
default view, back above the results list once a role/ward is picked or a
search is active (there's no chart to lead with there). `npm run lint`/
`npm run build` clean. Verified functionally via direct DOM inspection
(`document.body.innerText`, checked for real rendered `<circle>` elements
with non-zero data) rather than a visual screenshot — the browser window
was intermittently unresponsive/minimized (0×0 viewport) during this pass,
unrelated to the app itself; confirmed both panels' default view reads
chart → tiles → "+ Add Staff"/"+ Add Patient" in that order, and the
drill-down view correctly reverts to search-bar-first with no console
errors.

**Amended a fifth time (2026-09-19, on-call segment + role/duty slicers +
full roster list on the Staff panel):** three related asks from the user
in one message. (1) The "Duty Status" donut gained a third "On call"
segment (was on duty/off duty only) — uses the top-level `roleCounts.
on_duty`/`on_call` fields directly rather than a role-scoped breakdown:
admin/security_officer are `Staff.NO_WARD_DUTY_ROLES` and always `False`
for both, so these two top-level counts are already effectively
clinical-only in practice, and this is the exact same `on_duty`/`on_call`
pair the Overview page's own "Total Staff" card has always shown — no
backend change needed, and consistent with a real pre-existing data
quirk already visible there (`on_duty` sometimes reads higher than the
`on_duty_by_role` sum for the 5 browsable roles; confirmed this predates
this change, not introduced by it, so left alone as out of scope). (2) The
"Staff by Role" chart card gained two slicers — role then duty status —
mirroring `SecurityDashboard.jsx`'s own `.ledger-slicers` pattern
(`STAFF_DUTY_OPTIONS`, a local copy of that file's `DUTY_OPTIONS`, since
the two slicers filter different things: the staff roster directly here,
Ledger entries cross-referenced against staff there). (3) A new full
roster list now renders below the search/Add-Staff row in the default
view — independent of the tile-drill-down `results` list above it, so
browsing it never disturbs that flow — fetched via `searchStaff('',
roleFilter)` (the same call the tile-drill-down already uses) and
filtered client-side by the two new slicers, scoped to
`STAFF_BROWSE_ROLES` throughout (same 5-clinical-roles scoping already
used everywhere else in this panel). A real bug surfaced and fixed before
this shipped: the new state/effect block was first placed *before*
`error`/`setError`'s own declaration in the component, so referencing
`setError` inside the effect's `.catch()` hit a genuine temporal-dead-zone
error (`oxlint` caught it: "Cannot access variable while it is being
initialized") — fixed by moving the whole block after the existing state
declarations, not by reordering `error` itself. `npm run lint`/`npm run
build` clean. Verified live (Claude-in-Chrome, real admin account) via
direct DOM inspection again (screenshots stayed unreliable this session):
confirmed the slicers render, the donut shows a real "On call (0)"
segment, the real doctor account appears in the new roster list with an
"On duty" suffix, and changing the duty slicer to "Off duty" correctly
filters the list to empty (the one real doctor is on duty) — no console
errors.

**Amended a sixth time (2026-09-19, both charts now driven by the
slicers):** per the user, the two slicers added above were only wired to
filter the new roster list — the "Staff by Role" bar and the "Duty
Status" donut still always read the static, unfiltered `getStaffSummary()`
counts, so changing a slicer visibly moved the list underneath but left
both charts above it static. Both charts now derive their rows from
`browseResults` (the same role/duty-filtered array the roster list already
uses) instead of `roleCounts` — the bar counts each role's occurrences
within `browseResults`, and the donut counts `on_duty`/`on_call` within
`browseResults` the same way. A side effect, expected and not a bug: with
the duty slicer set to a specific status, the donut correctly collapses
toward that one segment (e.g. "Off duty" filters the whole card down to
0/0/0 when the one real staff member is on duty) — that's the filter
doing its job, not double-counting or losing data. `npm run lint`/`npm run
build` clean. Verified live (Claude-in-Chrome, real admin account,
DOM-inspection again): with no filters, the bar/donut/roster all agreed
(Doctor: 1, On duty: 1); switching the duty slicer to "Off duty" correctly
zeroed the bar and donut together with the roster ("No staff match the
current filters"); switching back to "On duty" restored all three. No
console errors.

**Amended a seventh time (2026-09-19, same pattern applied to the Patients
panel):** per the user, who pointed out the Staff-panel-only changes above
left the Patients panel behind. `PatientPanel` gets the same treatment,
scaled to one slicer instead of two since ward is the only browsable
dimension there (no role/duty equivalent for patients): a ward `<select>`
in the "Patients by Ward" chart card's header (`chartWardFilter`, options
from `WARD_CHART_COLORS` — the same fixed ward-plus-unassigned list the
tiles already use), a `browseResults` state fetched via
`searchPatients('', chartWardFilter || undefined)` (client-side `!p.ward`
filtering for the `'unassigned'` option, same as the existing
`selectWardCategory`/`runSearch` special-casing elsewhere in this panel),
and a full patient roster list rendered below the search/Add-Patient row.
Both "Patients by Ward" (bar) and "Ward Distribution" (donut) now derive
their rows from `browseResults` instead of the static `wardCounts`
summary, so picking a ward in the slicer collapses both charts toward that
ward together with the list — same expected-collapse behavior as the
Staff panel's duty slicer, not a bug. `npm run lint`/`npm run build`
clean (only the same pre-existing `set-state-in-effect` warning class
already present elsewhere in this file). Verified live (Claude-in-Chrome,
real admin account, DOM inspection): with no filter, the bar/donut/roster
all agreed with the real data (Surgical Ward: 1, the one real patient);
switching the slicer to "General Male Ward" correctly zeroed both charts
and emptied the roster ("No patients match the current filter") while the
ward tiles below (unaffected, static) still correctly showed Surgical
Ward: 1; switching back to "All wards" restored all three. No console
errors.

**Amended an eighth time (2026-09-19, patient status field + chart swap):**
per the user, who wanted the Patients panel's bar chart to show patient
status (admitted/discharged/etc.) instead of ward, and the donut to become
the ward chart with its own slicer. Confirmed via two `AskUserQuestion`
rounds first, since "on appointment" in the user's own phrasing brushed
directly against CLAUDE.md's explicit "do not build appointment booking or
scheduling" exclusion: settled on a plain, manually-set current-state label
— **Admitted / Discharged / Outpatient** — not a scheduling feature. New
`patients.PatientStatus` (`TextChoices`, same shape as `staff.Ward`) and
`Patient.status` (blank-by-default `CharField`, migration
`patients/0004_patient_status.py`, applied to the real dev database) —
manually set by an admin on the Patient panel's detail card, never
computed, same convention as ward/on-duty/on-call. New
`PATCH /api/patients/<id>/status/` (`PatientStatusUpdateView`, `IsAdmin`,
mirrors `PatientWardUpdateView` exactly) and a `status` query param on the
existing `GET /api/patients/` search endpoint (mirrors the existing `ward`
param); `PatientSummaryView` gained `by_status` (mirrors `by_ward`,
including an `unassigned` bucket for patients with no status set yet — the
same necessary "not yet set" bucket ward already has, not a new status
value). `PatientSummarySerializer` now includes `status`. 6 new backend
tests (`patients.tests`: status update, invalid-status rejection,
non-admin-forbidden, search-by-status filter, summary breakdown) — 37/37
`patients` app tests passing.

Frontend: `PatientPanel`'s left chart card is now **"Patient Status"**
(`HorizontalBarChart`, new `PATIENT_STATUS_OPTIONS` color palette — green/
lavender/amber/gray, distinct from both `WARD_CHART_COLORS` and the 5
pinned Ledger severity hues) driven by `browseResults` grouped by
`status`; the right card is now **"Patients by Ward"** (the donut,
renamed from "Ward Distribution") and inherited the ward `<select>` slicer
that used to sit on the bar card — so the one shared `chartWardFilter`
still narrows the bar, the donut, and the roster list together, same
collapse-toward-the-filter behavior as the seventh amendment established.
The detail card gained a second "Status" dropdown + "Save status" button
directly under the existing "Save ward" one (`updatePatientStatus`, new
`frontend/src/api/patients.js` export), and the roster list's meta-line
now appends the status label when one's set. `npm run lint`/`npm run
build` clean (same pre-existing warning class as elsewhere). **Real bug
found and fixed during live verification:** the backend dev server's
autoreloader picked up the `views.py` changes but never re-registered the
new `urls.py` route (`PATCH /api/patients/<id>/status/` 404'd against a
live server whose process had been running since before this session's
edits) — not a code bug, a stale-autoreload quirk; a full server restart
picked up the route correctly on the very next request. Verified live
(Claude-in-Chrome, real admin account, real patient `iuyjcghh`): set
status to Admitted through the UI, confirmed the PATCH returned 200, the
bar chart correctly moved from Unassigned:1 to Admitted:1 after a refetch,
and the roster line picked up "· Admitted"; the ward slicer, now on the
donut, still correctly collapsed both charts and the roster together when
narrowed to a ward with no patients. The test status value was reverted
back to blank afterward (not real data to leave behind) — the ward slicer
was reset to "All wards" too. No console errors.

**Amended a ninth time (2026-09-19, status slicer added):** per the user,
the "Patient Status" bar chart gained its own status `<select>` slicer in
its header (`chartStatusFilter`), mirroring the ward slicer already on the
donut. The two slicers now combine: `browseResults`' fetch effect passes
whichever filter is a concrete backend value as a `searchPatients()` query
param and re-applies both dimensions client-side afterward (needed because
`'unassigned'` isn't a real ward/status value server-side — blank is — so
it's always filtered client-side regardless of which slicer set it,
including when both are set at once). `npm run lint`/`npm run build`
clean. Verified live (Claude-in-Chrome, real admin account): the status
slicer renders with all 4 options; filtering to "Admitted" correctly
zeroed both charts and the roster (the one real patient has no status
set); filtering to "Unassigned" correctly matched that same real patient;
reset back to "All statuses" afterward. No console errors.

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

   **Amended (2026-08-30, Staff-browsing scope + Overview breakdowns):** the
   Admin dashboard's Staff page (category tiles and global search alike) is now
   scoped to the 5 clinical roles only (`STAFF_BROWSE_ROLES` in
   `AdminDashboard.jsx`) — an admin manages only its own account (via the
   Profile page above), and shouldn't browse/manage other admin or
   security_officer accounts from here either, even though it can still
   *create* a security_officer account (`ADMIN_CREATABLE_ROLES` unchanged).
   `OverviewPanel`'s four stat cards each gained a second layer of real
   sub-counts instead of just one number: Total Patients breaks down by ward
   (reusing `by_ward` from the summary endpoint), Total Staff shows on-duty/
   on-call, Staff On Duty breaks down by role, Disaster Mode shows its last
   event (who, when — already available from `DisasterModeView`). New
   `on_call` total and `on_duty_by_role` (scoped to `Staff.CLINICAL_ROLES`,
   same reasoning as the Staff-browsing scoping above) added to
   `GET /api/staff/summary/`. `.overview-grid` also switched from
   `auto-fill`/`minmax` to a fixed `repeat(4, 1fr)` (2 cols under 900px, 1
   under 480px) — the old rule reserved an empty 5th column track on wide
   screens, leaving a gap instead of the 4 real cards filling the row.

   **Amended (2026-08-30, one device per clinical account):** each of the 5
   clinical roles (`Staff.CLINICAL_ROLES`) is now bound to a single primary
   device — whichever device first logs into that account. Admin/security
   officer are exempt (documented shared accounts, see `Staff.NO_WARD_DUTY_ROLES`
   above) and log in exactly as before regardless of device. New
   `access.Device` (one row per approved device, `is_primary` on exactly one)
   and `access.PendingDeviceRequest` (`pending`/`approved`/`rejected`) models,
   both scoped to `access` — not routed through the Security Ledger, same
   reasoning as `scoring.DisasterModeEvent` (the Ledger's `event_type` is
   pinned to 5 fixed values, none of which fit "a device was approved").
   `access.services.create_session()` extracted from `LoginView` so both a
   normal login and an approved device grant a session through the same path.
   A login from an unrecognized device no longer gets a token: it returns
   `202 {"status": "pending_approval", "poll_token": ...}` instead, and
   `LoginPage.jsx` shows a live waiting screen that polls
   `GET /api/access/device-requests/<poll_token>/poll/` (unauthenticated —
   the waiting device has no token yet) every 5s until the account's primary
   device owner approves or declines it, capped at ~10 minutes before showing
   "request expired." New self-service endpoints under `/api/access/devices/`
   (list own devices + pending requests, pending count for the header badge,
   approve/reject/remove — all scoped to `request.auth.staff`, the same
   any-logged-in-staff-member-acting-on-themselves pattern as
   `ChangePasswordView`). The primary device can never be removed (backend
   400s it); removing any other device also ends its still-active session.
   Frontend: `DashboardShell.jsx`'s `ProfilePanel` gained a collapsible
   "Devices" `<details>` section (clinical roles only) with Approve/Decline
   rows for pending requests and a Remove button on non-primary approved
   devices; the header's profile icon gets a small red dot
   (`.profile-badge-dot`) whenever a pending request exists, polled every 25s.
   `device_id` itself is unchanged — still the client-generated UUID persisted
   in `localStorage` by `deviceInfo.js`'s `getOrCreateDeviceId()` (added in
   step 1), reused here rather than adding new fingerprinting; it remains a
   self-reported value with no cryptographic binding, consistent with this
   project's existing trust model for manually-entered fields.

   **Amended (2026-08-30, real staff delete):** the Admin dashboard's Staff
   panel gained a genuine, permanent **Delete account**
   (`staff.views.StaffDeleteView`, `POST /api/staff/<id>/delete/`,
   `IsAdmin`-gated) next to the existing Deactivate/Reactivate toggle — a
   deliberate, explicit exception to this file's usual "deactivate, never a
   hard delete" rule (see step 4's original entry above, which still describes
   Deactivate/Reactivate accurately; that path stays available for the
   reversible case). Rejects admin/security_officer targets with 400
   (`Staff.NO_WARD_DUTY_ROLES`) as defense in depth, even though the Staff
   panel this button lives on already can't reach those rows. Deletes
   `staff.user` (the linked `auth.User`) rather than the `Staff` row directly
   — `Staff.user` is `on_delete=CASCADE`, so removing the `User` cascades to
   the `Staff` row and everything FK'd to it (`AccessSession`, `Device`,
   `PendingDeviceRequest`, patient assignments, behavioral baselines) through
   existing relationships, no new FK behavior needed. `ledger.LedgerEntry`
   rows are untouched — that app denormalizes staff identity (a plain
   `staff_id` `CharField`, not a foreign key) rather than referencing `Staff`,
   so a deleted staff member's historical audit trail survives intact.
   Frontend reveals an inline warning + a second "Yes, permanently delete"
   button before acting (same pattern as BTG's reason textarea — no native
   `confirm()` dialog).

   **Amended (2026-09-03, assign a patient from the Staff panel):** patient
   assignment previously only worked from one direction — select a patient
   in `PatientPanel`, type a staff ID into a raw text field. Per the user,
   the Admin dashboard's `StaffPanel` now supports the reverse too: select
   a doctor/nurse, see their current patient assignments, search for a
   patient inline, and assign/unassign directly from the staff side.
   `PatientAssignmentListCreateView`'s existing POST/`PatientAssignmentDeactivateView`
   are reused unchanged (patient-first or staff-first, same underlying
   `PatientAssignment` row) — only a new read endpoint was needed, the
   reverse of the existing per-patient GET: `GET /api/patients/staff/<staff_pk>/assignments/`
   (`patients.views.StaffAssignmentsView`, `IsAdmin`-gated). Reuses
   `AssignedPatientSerializer` (already used by `MyAssignedPatientsView`),
   which gained an `id` field so the Staff panel can build the deactivate
   URL. Not shown for pharmacist/lab_technician/clerk — assignment isn't a
   concept for those roles per the Contextual module. 22/22 `patients` app
   tests passing (3 new). Verified live in-browser against the real admin
   and doctor accounts: the Staff panel's Patient Assignments section shows
   the existing assignment, and the inline patient search returns and
   renders a matching result correctly.

   **Amended (2026-09-03, structured fields per category):** reverses this
   step's original `PatientCategoryRecord` design — "generic `{"notes":
   ...}` content, deliberately not a structured EMR" (see the original
   sentence above) — per the user, who wants each of the 13 categories to
   have its own named fields (e.g. category 1 Identity: date of birth, sex,
   address, phone, next of kin, marital status, occupation) rather than one
   free-text box. Confirmed via `AskUserQuestion`: real validated
   structure, all 13 categories, not just a cosmetic form over unstructured
   JSON. New `patients/category_fields.py`'s `CATEGORY_FIELDS` dict (keyed
   by category number, each a list of `{name, label, type}`) is the single
   source of truth — `PatientCategoryRecordSerializer` exposes it per
   record as `field_defs` (named that, not `fields` — collides with DRF's
   own `Serializer.fields` property) so the frontend renders each
   category's form purely from what the backend sends, no schema
   duplicated in JS; `PatientCategoryContentUpdateSerializer` validates
   saved content against it (unknown keys or non-string values 400).
   `content` stays a plain `JSONField` — no migration, only what's *allowed
   inside it* changed. Frontend: `AdminDashboard.jsx`'s category editor
   (was `CategoryNotesEditor`, one hardcoded textarea) is now
   `CategoryFieldsEditor`, rendering one labeled input per `field_defs`
   entry (`text`/`number`/`date` → `<input>`, `textarea` → `<textarea>`,
   `select` → `<select>` with `options`). Checked the real dev database
   first: exactly 1 patient existed, every category still `{}` — nothing
   real to migrate. 25/25 `patients` app tests passing (3 new, plus the
   pre-existing category-content test's payload updated since `{"notes":
   ...}` is no longer a valid shape for category 6). Verified live
   in-browser against the one real patient: Identity's seven fields render
   correctly, a value round-trips through a full page reload, Allergies
   renders its own distinct two fields — test values cleared back to empty
   afterward.

   **Amended (2026-09-05, advanced Profile page + staff photo upload):** the
   shared Profile page (`DashboardShell.jsx`'s `ProfilePanel`, opened via the
   header's profile icon, same component for every role) gained real
   labeled fields and a profile photo, per the user, who wanted it "more
   advanced... more professional" than the old two bare lines. New
   `Staff.photo` (`ImageField`, `upload_to="staff_photos/"`, migration
   `staff/0006_staff_photo.py`, applied to the real dev database) — local
   disk storage, confirmed via `AskUserQuestion` ("Local disk for now
   (recommended for the hackathon)"): fine for local dev/a single demo
   session, but Render's free-tier disk is ephemeral, so an uploaded photo
   won't survive a backend redeploy there without swapping in real object
   storage later (documented on the field's own `help_text` too). New
   `MEDIA_URL`/`MEDIA_ROOT` in `config/settings.py`, served via
   `config/urls.py`'s `static()` helper in `DEBUG` only. Self-service
   `ProfilePhotoView` (`POST` multipart to upload/replace, `DELETE` to
   remove, `/api/access/profile/photo/`) follows the same
   any-authenticated-staff-acts-on-themselves pattern as
   `ChangePasswordView`/`CurrentSessionView`; a shared `_photo_url(request,
   staff)` helper returns an absolute URL via `request.build_absolute_uri()`
   so the frontend never needs to know the backend host separately from the
   API base. `CurrentSessionView` gained `on_call` (previously missing
   despite `on_duty`/`ward` already being live-read there) and `photo_url`;
   `StaffSummarySerializer` gained a `photo_url` `SerializerMethodField`
   (needs `request` in context — added to all 5 call sites in
   `staff/views.py`: search, create, duty-update, deactivate, reactivate).
   Frontend: `client.js`'s `request()` now detects a `FormData` body and
   skips both the JSON `Content-Type` header and `JSON.stringify` so the
   browser can set its own multipart boundary; `RoleAvatar.jsx` accepts an
   optional `photoUrl` prop and renders the real photo instead of the
   cartoon mascot when one exists (patients are unaffected — no `photoUrl`
   is ever passed for them); `SecurityDashboard.jsx` threads
   `photoUrl={selected.photo_url}` into both existing `<RoleAvatar>` call
   sites (Staff/Patients' `ActivityLookupPanel` and `AdminsPanel`) so a
   Security Officer sees a staff member's or admin's real photo the moment
   one's uploaded. `ProfilePanel`'s "My profile" card now renders Name,
   Staff ID, Role, and — clinical roles only (`CLINICAL_ROLES`, matching
   `NO_WARD_DUTY_ROLES` everywhere else in this app) — a live Duty status
   line (`On duty (ward)`/`Off duty (ward)`, or just `On duty`/`Off duty`
   with no ward) and an On call (Yes/No) line, all sourced from
   `getCurrentSession()` rather than the `staff` prop's login-time snapshot,
   so the card reflects a change an admin makes elsewhere without needing a
   fresh login. A new `ProfilePhotoSection` sits at the top of the card —
   Devices-then-Change-password ordering underneath is unchanged. Along the
   way, found and fixed a real pre-existing gap unrelated to this feature's
   own code but which this feature's tests surfaced: `config/settings.py`'s
   `STORAGES` setting had no `'default'` entry (only `'staticfiles'`), so
   *any* `ImageField`/`FileField` save raised `InvalidStorageError` — added
   a `FileSystemStorage` default. 187/187 backend tests passing (4 new,
   `access.ProfilePhotoViewTests`).

   **Amended again (2026-09-05, same day — horizontal split + click-the-
   avatar-to-upload):** two follow-up corrections, per the user, to the
   layout/interaction just shipped above. First, the "My profile" card is
   now a horizontal split (`.profile-detail-row` in `App.css`): the photo on
   the left (`.profile-detail-photo`, fixed ~110px), the labeled Name/Staff
   ID/Role/Duty status/On call fields on the right (`.profile-detail-fields`,
   flexes to fill the rest) — previously the photo sat in its own row above
   all the fields, full-width. Second, `ProfilePhotoSection`'s separate
   "Upload photo"/"Replace photo" button is gone — the avatar image itself
   is now the trigger: it's wrapped in a `<label className="profile-avatar-
   upload">` holding the hidden `<input type="file">`, so clicking directly
   on the avatar opens the file picker (`title` attribute reads "Click to
   upload a photo" / "Click to change photo" depending on whether one
   already exists). A small "Remove photo" text link (new `.link-button`
   style) sits underneath the avatar in the left column, shown only once a
   photo exists — unchanged in behavior, just restyled to fit the narrower
   left column. Verified live in-browser against the real doctor account
   (282828): clicking the avatar directly opens the picker and uploads
   correctly (no separate button in the way), removal reverts to the
   cartoon mascot (the fields stay stacked vertically, one per line -- a
   same-day attempt to lay them out horizontally in a row was tried and
   immediately reverted, per the user; text within that column is
   left-aligned, `text-align: left` -- an in-session right-aligned attempt
   was corrected back to left the same day, per the user). `.profile-detail-
   row` is an explicit two-column CSS grid (`grid-template-columns: 1fr
   1fr`), not flex, so the fields column always starts exactly at the
   card's horizontal midpoint regardless of the photo's own width (per the
   user: "the details start from the middle of the card"), and
   `.profile-detail-fields` got a bumped `font-size: 1.1rem` (per the user:
   "make the text a little bit big"). Verified live in-browser against the
   real doctor account (282828, who by this point had uploaded their own
   real profile photo through the running dev server, confirming the
   feature works end-to-end for a real user, not just my own test
   uploads) -- fields start at the card's midpoint, text reads noticeably
   larger, no console errors.

   **Amended (2026-09-12, browse patients by ward, not just search):** the
   Clinical Dashboard (shared by all 5 clinical roles) previously had exactly
   one way to find a patient -- free-text search, plus "Assigned to you" for
   doctors/nurses. Per the user, acting as their own product owner ("how it
   should suppose to be a doctor dashboard... not only by searching, you can
   also select ward"), planned via Plan Mode. Rather than inventing new UI,
   this mirrors `AdminDashboard.jsx`'s `PatientPanel` ward-tile pattern
   exactly (`.category-grid`/`.category-tile`, already used identically for
   Staff-by-role and Patients-by-ward there) -- same
   `selectedWard`/`wardCounts` state shape, same
   `selectWardCategory`/`backToWards`/`showingWards` logic, same "search
   scopes to whichever ward you're in" behavior, just without the admin-only
   Manage/Add-Patient actions. "Search patients" is renamed "Find a patient"
   since search and ward-browsing are now two entry points into the same
   list, not separate features.

   One backend permission widened: `GET /api/patients/summary/`
   (`PatientSummaryView`) was `IsAdmin`-gated, but it only ever returns
   aggregate ward counts, never patient identities -- same reasoning already
   used once before to widen `StaffSearchView` from `IsAdmin` to
   `IsAdminOrSecurityOfficer`. Its `permission_classes` override was removed
   entirely, falling back to the project default `IsAuthenticated`, so any
   logged-in staff member (not just Admin) can now read it.
   `test_non_admin_cannot_read_patient_summary` became
   `test_any_authenticated_staff_can_read_patient_summary` (now asserting
   200 + correct counts instead of 403), plus a new
   `test_unauthenticated_cannot_read_patient_summary` confirming the
   endpoint still isn't open to the entire internet. Everything else needed
   zero backend changes -- `GET /api/patients/?q=&ward=` was already
   ward-filterable and already open to any authenticated staff;
   `ClinicalDashboard.jsx`'s search just wasn't passing the `ward` argument
   yet. 26/26 `patients` app tests passing.

   **Real bug found during the user's own live testing, fixed the same
   day:** after viewing a patient from within a ward's list, clicking "←
   Back to wards" returned to the ward tiles but left the patient's detail
   panel (decision/records/step-up/BTG, all of it) still rendered
   underneath -- `backToWards()` only ever reset the ward-browsing state
   (`selectedWard`/`query`/`results`), never the separate patient-detail
   state, since nothing had previously needed to close that panel from
   outside `openPatient()` itself. New `closePatientDetail()` resets every
   field `openPatient()` resets when it *opens* a new patient (minus the
   fields only a live fetch needs), called from `backToWards`,
   `selectWardCategory`, and `handleSearch` alike -- any action that changes
   what's shown in the Find-a-patient results area now also closes a stale
   detail view underneath it, not just the one path the user happened to
   hit first. Verified live in-browser against the real doctor account
   (282828) and the one real patient: ward tiles show the correct real
   count (Surgical Ward: 1), drilling in and clicking View opens a genuine
   48% reduced-access decision, and clicking "← Back to wards" now returns
   to a clean tile grid with no leftover panel. No console errors.

   **Amended the same day (2026-09-12, "Assigned to you" moved below the
   ward tiles):** per the user, this section (doctor/nurse only) moved from
   its own place above "Find a patient" to directly underneath the
   `.category-grid` ward tiles, inside that same section's default
   (`showingWards`) view -- shown by default alongside the tiles, per the
   user, not only once a ward's picked. Purely a JSX relocation: the
   `assignedPatients` fetch, its `.map()` row rendering, and the `View`
   button's call into `openPatient()` are all unchanged, just wrapped in a
   new `.assigned-to-you` spacing div and rendered one level deeper.
   Verified live against the real doctor account (282828): since that
   account genuinely has zero active patient assignments right now, a real
   (not fabricated) `PatientAssignment` row was created directly against
   the one real patient specifically to confirm the section's new position
   renders correctly -- it appeared directly below the ward tiles exactly
   as intended, no console errors -- then deleted immediately afterward,
   confirmed back to zero active assignments for that account.

   **Amended a third time the same day (2026-09-12, "Unassigned" tile
   removed):** per the user, a ward-browsing category inviting anyone to
   pull up every patient with no ward on file read as an unnecessary
   temptation toward misuse, not a useful feature -- removed from
   `ClinicalDashboard.jsx`'s ward-tile grid entirely (the four real wards
   remain). `handleSearch`/`selectWardCategory`'s `'unassigned'`
   special-casing (a client-side `!p.ward` filter, since that value never
   existed as a real backend `ward`) was dead code once the only button
   that could ever set `selectedWard` to `'unassigned'` was gone, so it was
   removed too, not just hidden. A patient with no ward is still findable
   by name/hospital-number search and still correctly labeled "Unassigned"
   in its own result row -- only the *browse-every-unassigned-patient*
   discovery path is gone, not the label. `AdminDashboard.jsx`'s own
   "Unassigned" tile (a different audience -- admins actively need to find
   patients still awaiting a ward assignment) is untouched, out of scope
   for this change. Verified live in-browser against the real doctor
   account: the tile grid now shows exactly the four real wards, no console
   errors.

   **Amended a fourth time the same day (2026-09-12, real assignment
   created):** the temporary verification assignment from the second
   amendment above had been created then deleted, so the doctor account
   genuinely had zero assignments again -- which read, from the user's own
   screen, like the just-shipped "Assigned to you" feature appearing and
   then disappearing. After clarifying that no code had changed (re-read
   the file to confirm), the user asked for a real, permanent assignment
   this time. Created through the actual `POST /api/patients/<id>/
   assignments/` endpoint (not raw ORM) using a diagnostic admin session
   token for auth, which was deleted immediately after the call; the
   resulting `PatientAssignment` row (Dr. Maaji Shettima Bukar, 282828, as
   doctor for the one real patient, hospital number iuyjcghh) is real
   enrollment data, not test data, and was left in place. Verified live in-
   browser against the real doctor account, including a full page refresh:
   "Assigned to you" now permanently shows this patient, no console errors.

   **Amended a fifth time the same day (2026-09-12, real bug: clinical
   record view never displayed the structured fields):** while checking
   why category 1 (Identity)'s phone number wasn't showing to clinical
   staff, found that `ClinicalDashboard.jsx`'s patient-record view
   (`records.records.map(...)`) had never been updated for the 2026-09-03
   "structured fields per category" change (see that amendment above) --
   it still read `r.content?.notes`, a key that hasn't existed in any
   category's content since that change, so every category always
   rendered "(no notes recorded)" regardless of what was actually stored.
   `PatientRecordView`'s API response already included the real
   `field_defs`/`content` the whole time (via the shared
   `PatientCategoryRecordSerializer`, same as the Admin dashboard's
   `CategoryFieldsEditor` uses) -- only this one read-only view never
   consumed it. Now renders one "Label: value" line per filled field
   (skipping empty ones), matching the "Label: value" pattern already used
   elsewhere in this app (`DetailField` on the Security dashboard) --
   read-only, no editing here (that stays the Admin dashboard's job). This
   was a pure bug fix, not new scope: the phone field itself has existed in
   `patients/category_fields.py`'s category-1 field list since 2026-09-03.
   Verified live in-browser against the real doctor account and the one
   real patient: every one of the 13 categories now correctly shows "(no
   information recorded)" instead of the old "(no notes recorded)" text,
   since no Identity fields (including phone) have actually been entered
   for this patient yet -- that's real, still-missing enrollment data, not
   a rendering bug, so it wasn't fabricated here; it needs to be entered
   through the Admin dashboard's existing Identity category editor. No
   console errors.
5. ✅ **Done (2026-08-28).** Emergency Override ("Break the Glass" / BTG in the UI — see the Emergency Override section above for naming and scope decisions). New `POST /api/scoring/emergency-override/` (`scoring.views.EmergencyOverrideView`, `IsClinicalStaff`-gated): takes `{patient_id, reason}` (reason min 10 chars), grants the caller's full role ceiling (`ROLE_CEILINGS[staff.role]`) regardless of the hard gate/score band/Nurse rule, writes an `AccessDecision` row (`decision_type=EMERGENCY_OVERRIDE`; `gate_passed`/`score`/`score_band` now nullable on that model — an override never ran the scoring pipeline, so "not applicable" is more honest than a sentinel score) and an `EMERGENCY_OVERRIDE` Ledger entry (`reason` in `details`). Does not check `contextual.target_patient_id` the way `DecideView` does (must still work if capture/contextual state is missing or itself the reason normal access failed) and does not reinforce the behavioral baseline (an override is by definition an abnormal session). `scoring.views.PatientRecordView` needed no changes — it already treats any non-`ACCESS_DENIED` decision type the same way. Frontend: `ClinicalDashboard.jsx` gained a "Break the Glass" button in the patient-view section (always visible once a patient is selected, not gated behind a denial) that reveals an inline reason textarea before submitting — no native `confirm()` dialog. `SecurityDashboard.jsx` needed no changes (its event-type filter/severity coloring/drill-down already handled `EMERGENCY_OVERRIDE` rows from step 4). 105/105 backend tests passing (8 new); verified end-to-end via direct API calls against the real dev database using the real Admin and doctor accounts (Chrome browser extension wasn't connected for a live UI click-through) — confirmed the full round trip (override → granted all 13 categories → records endpoint returns content → a correctly hash-chained `EMERGENCY_OVERRIDE` Ledger entry with the reason). The temporary QA patient and sessions were deleted afterward; the Ledger entry itself was left in place since it's append-only by design.

   **Amended 2026-08-29** (after a live demo surfaced a real gap): added the Doctor rule (see Role → category access above) and BTG's own availability gate (see Emergency Override above). `AccessDecision.nurse_path` renamed to `role_rule_path` (now used by both roles' rule paths; migration `scoring/0003_rename_nurse_path_to_role_rule_path.py`). New `captures/services.py` (`compute_patient_assignment_status`) extracted from `captures.views.TargetPatientView` so both the normal capture flow and BTG's fresh gate check share one implementation instead of two.

   **Amended again 2026-08-29** (same-day follow-up, real-world refinement of the above): added `Staff.on_call`/`ContextualCapture.on_call_at_login` (treated as equivalent to on-duty everywhere the Doctor rule/BTG gate check duty status — see Contextual module and Emergency Override above), BTG's `reason_category` field (`clinical_emergency`/`cross_coverage`/`other` — `cross_coverage` self-attests through the off-duty+unconnected block), and Disaster/Mass Casualty Mode (`scoring.DisasterModeEvent`, `scoring.disaster_mode.is_disaster_mode_active()`, `IsAdmin`-gated `POST /api/scoring/disaster-mode/activate|deactivate/`, Admin-dashboard-only `DisasterModePanel` — see Emergency Override above for full scope/reasoning, including why it's audited outside the Security Ledger). Frontend: `ClinicalDashboard.jsx`'s BTG form gained a required category `<select>` above the existing reason textarea; `AdminDashboard.jsx`'s `StaffPanel` gained an "On call" checkbox alongside "On duty".

   **Amended a third time (2026-09-08, hide the button once there's nothing
   left for it to do):** per the user, the BTG button was showing even when
   it made no sense to — once a session already had full role-permitted
   access (`STANDARD_ACCESS`/`AUDITED_DEVIATION`, both grant the complete
   role ceiling per the Scoring Engine's band table) or had already used
   BTG for this patient (`EMERGENCY_OVERRIDE`). `ClinicalDashboard.jsx` now
   derives `hideBreakGlass` (`decision` exists and its `decision_type` is
   one of those three) and hides the whole `override-control` block when
   true — `REDUCED_ACCESS`, `ACCESS_DENIED`, and no-decision-yet all still
   show it, since those are exactly the cases BTG exists to rescue. This is
   a frontend-only simplification, not a backend security change — CLAUDE.md
   still requires the override endpoint itself to remain "always available
   regardless of score or role match"; `EmergencyOverrideView` is untouched
   and would still grant access if called directly. Verified live in-browser
   against the real doctor account (`282828`) and the one real patient: a
   genuine 60% score landed in `REDUCED_ACCESS` and correctly still showed
   the button; triggering a real Break the Glass (`clinical_emergency`, a
   real reason) granted all 13 categories and correctly made the button
   disappear afterward, with no console errors. That real
   `EMERGENCY_OVERRIDE` decision and its Ledger entry were left in place
   (same reasoning as step 5's original entry above — the Ledger is
   append-only by design and this was a genuine audited event, not
   fabricated test data).
5b. ✅ **Done (2026-09-06).** Five hackathon-hardening features, chosen by the
   user from a full-system review that surfaced six gaps (they picked all but
   the sixth — demo enrollment data, which is theirs to supply per the
   Enrollment data rule). Planned via Plan Mode; the three design forks were
   settled with `AskUserQuestion`. Numbered here as 5b because these harden
   steps 1–5 rather than extending the build order.

   **(a) Step-up verification — closes a spec/code gap.** CLAUDE.md's band
   table has said "40–69% → Reduced access **+ step-up verification
   required**" since step 2, and `ClinicalDashboard.jsx` even printed that
   sentence to the user, but nothing enforced it: `openPatient()` fetched and
   rendered records immediately for any non-denied decision. Now real. The
   second factor is a **separate step-up PIN** (`Staff.step_up_pin_hash`,
   4–8 digits, hashed with `django.contrib.auth.hashers`, never stored or
   returned in clear) rather than password re-entry — confirmed via
   `AskUserQuestion`, on the grounds that re-typing the login password isn't
   genuinely a second factor. New `AccessDecision.step_up_verified` /
   `step_up_verified_at` / `step_up_failed_attempts` **are** the audit record
   for step-up (deliberately not a sixth Ledger event type — the Ledger stays
   pinned to five). Enforced in `scoring.views.PatientRecordView`, **not just
   the UI**: that view is what actually hands over record content, so gating
   only the React screen would leave the API open to a direct call; it now
   403s with `step_up_required: true` until verified. New
   `POST /api/scoring/decisions/<id>/step-up/` (`StepUpVerifyView`,
   `IsClinicalStaff`, scoped to the caller's own session — someone else's
   decision is a 404, not a 403, so decision IDs can't be probed); three wrong
   PINs spend the decision and force a re-`/decide/`, and every failure raises
   a `STEP_UP_FAILED` alert. Admin sets the initial PIN
   (`POST /api/staff/<id>/step-up-pin/`, rejected for admin/security officer,
   who never score at all); the staff member changes it themselves from
   Profile (`POST /api/access/step-up-pin/`), so an admin isn't left knowing
   someone else's second factor. **Fails closed:** no PIN set means step-up
   can never succeed and reduced-band records stay hidden — deliberate, but it
   means PINs must be set before demoing. `StaffSummarySerializer` exposes
   `has_step_up_pin` (never the hash) so the Admin UI shows who still needs one.

   **(b) Ledger integrity verification — exposing what already existed.**
   `ledger.verification.verify_chain()` had been implemented and tested since
   step 3 but was unreachable outside the test suite, which meant the Ledger's
   entire tamper-evidence property couldn't be shown to anyone. New
   `GET /api/ledger/verify/` (`LedgerVerifyView`, `IsSecurityOfficer`) returns
   `{valid, bad_sequence, entries_checked, verified_at}`; computes fresh and
   persists nothing (same posture as `LedgerEntryExplainView` — a verification
   result is an observation *about* the Ledger, not part of it).
   `entries_checked` is counted separately so `verify_chain()`'s already-tested
   signature stays untouched. Frontend: a "Verify ledger integrity" button
   beside the Live feed heading (`LedgerVerifyControl` in
   `SecurityDashboard.jsx`) showing "Chain intact — N entries verified" or
   "Tampering detected at entry #N".

   **(c) Login brute-force lockout.** There was none at all. New
   `access.LoginAttempt` (one row per attempt, success or failure, with
   `ip_address` — not captured anywhere before this). **Lockout state is
   derived, not stored**: an account is locked while it has
   `settings.LOGIN_MAX_FAILED_ATTEMPTS` (5) failures inside
   `LOGIN_LOCKOUT_MINUTES` (15), both env-overridable — so auto-unlock is free
   (failures age out of the window, no scheduled job), and an admin clearing it
   early is just deleting those rows. Confirmed via `AskUserQuestion`:
   auto-expiry *and* admin unlock, specifically so a demo can never be
   permanently bricked. Checked in `LoginView.post()` **before**
   `authenticate()`, returning 429 — so a correct password during a lockout is
   still refused and an attacker who finally guesses right gets no signal.
   A successful login resets the count. Unknown usernames can lock out too
   (worth recording in its own right). Crossing the threshold raises a
   `LOGIN_LOCKOUT` alert. Admin unlock:
   `POST /api/staff/<id>/unlock/` (`IsAdmin`), logged via the existing
   `record_admin_action()` with a new `AdminActionLog.Action.STAFF_UNLOCKED`
   (a new `STEP_UP_PIN_SET` action was added the same day for (a)).
   `StaffSummarySerializer` exposes `is_locked_out`.

   **(d) Security alerts with an acknowledge workflow — closes the other
   spec/code gap.** CLAUDE.md's band table has always said sub-40% means
   "`ACCESS_DENIED`, **security alert triggered**", but a denial only ever
   wrote a Ledger row that scrolled past in a feed with nothing recording that
   anyone had reviewed it. New **`alerts` app** (`SecurityAlert`): three types
   — `ACCESS_DENIED`, `LOGIN_LOCKOUT`, `STEP_UP_FAILED` — each starting
   unacknowledged, with `acknowledged_at`/`acknowledged_by_staff_id`/
   `acknowledgement_note`. Confirmed via `AskUserQuestion` (full workflow, not
   just a visual counter), because logging something nobody reads isn't
   accountability. Denormalized actor fields, no FK — same reasoning as
   `ledger.LedgerEntry`/`staff.AdminActionLog`: deleting a staff member must
   not delete the evidence of what they did; `staff_id` is blank for a lockout
   against a username matching no account. `ledger_sequence` links a denial
   alert back to its Ledger entry (a plain int, since that row lives on a
   different database). Deliberately **not** a sixth Ledger event type and not
   hash-chained — it's a workflow record, not the access trail; same precedent
   as `scoring.DisasterModeEvent`. Single writer,
   `alerts.services.raise_alert()`. Endpoints (`IsSecurityOfficer`):
   `GET /api/alerts/`, `GET /api/alerts/unacknowledged-count/` (cheap badge
   poll, mirroring `DevicePendingCountView`), `POST /api/alerts/<id>/acknowledge/`
   (first acknowledgement wins — re-acknowledging won't overwrite who
   reviewed it). Frontend: a 5th Security-dashboard destination, **Alerts**,
   with a red count pill on the nav item (new optional `navItems[].badgeCount`
   on `DashboardShell`, polled every 25s like the pending-device dot).

   **(e) README + deploy config.** There was no root README at all (judges'
   first document) and no deploy config despite Render+Vercel being the chosen
   hosting since step 1 — `gunicorn`/`whitenoise` sat in `requirements.txt`
   with nothing invoking them. Added `README.md` (the problem, the Nigerian
   legal mapping, how decisions are made, architecture, local setup, tests,
   deployment, and a scripted demo path), `render.yaml` (both databases, and a
   build step that migrates **both** connections — `migrate` alone would leave
   the ledger tables missing), `frontend/vercel.json` (SPA rewrite; this app
   routes via `useState`, not a router), and replaced `frontend/README.md`'s
   untouched Vite boilerplate.

   228/228 backend tests passing (41 new across `ledger`/`access`/`scoring`/
   `staff`/`alerts`); migrations applied to the real dev database (default
   connection — only the `ledger` app needs `--database=ledger`).

   **Verified live** (Claude-in-Chrome, real security-officer account
   `SS0001`): the Verify-integrity button reported "Chain intact — 16 entries
   verified" against the real ledger database; a deliberate lockout (5 failed
   logins against a deliberately non-existent username, so no real account was
   locked) returned 429 with the remaining-minutes message, raised a
   `LOGIN_LOCKOUT` alert that appeared on the new Alerts page with the red
   nav-badge count, rendered correctly as "Unknown account" (no matching
   `Staff` row), and acknowledged cleanly — moving out of "Needs review" and
   into "Reviewed by: SS0001" with the note attached. The QA login attempts
   and that alert were deleted from the dev database afterwards. No console
   errors. **Not yet verified in-browser** (needs the admin and clinical
   logins, which weren't the account signed in at the time): the Admin Staff
   panel's Unlock/Set-step-up-PIN controls, the Profile page's Step-up PIN
   section, and the clinical dashboard's PIN challenge — all covered by
   backend tests, but the UI itself is unconfirmed.

   **Amended the same day (2026-09-06, step-up PIN replaced with device
   biometrics + peer-assist):** a few hours after 5b(a) shipped, the user
   asked to replace the typed PIN with the device's own Face ID/fingerprint/
   Windows Hello, "depending on the verification method of the device of the
   user." Confirmed via two `AskUserQuestion` rounds: the PIN is **retired
   entirely**, not kept as a fallback (Break the Glass already covers the
   "nobody's available at all" edge case); the fallback for a device with no
   biometric (or before one's enrolled) is **any other logged-in clinical
   colleague vouching from their own device**, unrestricted by role or duty
   status.

   The mechanism is **WebAuthn** — a website never sees the fingerprint or
   face, only a cryptographic proof the device's own biometric unlock
   approved it. Explicitly a different thing from the planned MedGuard
   Identity bonus layer (patient identification via a scanned fingerprint,
   SourceAFIS) — no overlap. Libraries: backend `webauthn` (py_webauthn,
   Duo Labs, pinned `3.0.0`), frontend `@simplewebauthn/browser` (`13.3.0`)
   — sibling projects speaking the same JSON shapes, confirmed by reading
   the installed packages' own source directly rather than trusting
   recalled API shapes (the docs site didn't resolve to version-pinned
   pages during research).

   **What was retired:** `Staff.step_up_pin_hash` (migration
   `staff/0008_remove_staff_step_up_pin_hash_and_more.py`),
   `StaffStepUpPinView`/`ChangeStepUpPinView` and their serializers/URLs,
   the PIN-checking body of the old `StepUpVerifyView`, `has_step_up_pin` on
   `StaffSummarySerializer`, and the Admin dashboard's "Set/Reset step-up
   PIN" button. `AdminActionLog.Action.STEP_UP_PIN_SET` stays defined but
   unused (no migration needed to drop a choice; no real PIN was ever set,
   so nothing historical is lost). **What survived unchanged:**
   `AccessDecision.step_up_verified`/`step_up_verified_at`/
   `step_up_failed_attempts` and `PatientRecordView`'s gate — that
   bookkeeping never cared *how* verification happened, only *whether*.

   **New in `access`:** `AccessSession.webauthn_challenge`/
   `webauthn_challenge_created_at` (the pending challenge between a
   ceremony's two calls, stored on the session row rather than Django's
   cache framework — `LocMemCache` is per-process and wouldn't survive
   Render's multi-worker gunicorn); `WebAuthnCredential` (one per device,
   `OneToOneField(Device)` — being an *approved* device and being
   *biometric-enrolled* are related but distinct facts); shared
   `access.services.webauthn_challenge_is_fresh()`/`clear_webauthn_challenge()`
   (both `access.views` and `scoring.views` need the identical freshness
   check, since both ceremonies use the same session field);
   `POST /api/access/webauthn/registration-options/` +
   `.../register/` (self-service enrollment, `IsClinicalStaff`,
   `AuthenticatorSelectionCriteria(authenticator_attachment=PLATFORM)` is
   what restricts to the device's own built-in authenticator rather than
   also offering a USB security key).

   **New in `scoring`:** `StepUpAssistRequest` (`decision`/`requesting_staff`/
   `resolved_by` FKs, `pending`/`approved`/`declined`) — lives here rather
   than mirroring `PendingDeviceRequest`'s home in `access`, because it must
   FK to `AccessDecision` and `access` sits *before* `scoring` in this
   project's one-way app dependency order. `POST /decisions/<id>/step-up/
   webauthn/options/` + `.../verify/` (mirrors the access-app registration
   pair; a genuine cryptographic failure — bad signature, sign-count
   regression — raises a `STEP_UP_FAILED` alert same as 3 wrong PINs used
   to, but a plain browser-side cancel never reaches the server at all, so
   it never alerts). `POST /decisions/<id>/step-up/assist/request/` +
   `GET /step-up/assist-requests/` (every *other* clinical colleague's
   pending requests — deliberately not scoped to "your own account" the way
   `DeviceListView` is) + `.../approve/` + `.../decline/` (decline also
   raises `STEP_UP_FAILED` — unlike a timeout, a colleague explicitly
   refusing to vouch is worth a security officer's attention). The
   requester's own "waiting for a colleague" screen polls the **existing**
   `PatientRecordView` rather than a new endpoint, since it already starts
   returning 200 the instant `step_up_verified` flips.

   New settings `WEBAUTHN_RP_ID`/`WEBAUTHN_RP_NAME`/`WEBAUTHN_ORIGIN`
   (default to `localhost` locally). **The one deployment detail that's easy
   to get wrong:** these must match the **frontend's** real domain (Vercel)
   in production, not this backend's Render domain — WebAuthn ties a
   credential to the origin the *browser* believes it's on, even though
   verification happens server-side. `render.yaml` ships obvious
   placeholder values on purpose so a first deploy can't silently ship a
   broken value unnoticed.

   Frontend: `DashboardShell.jsx`'s Profile-page `StepUpPinPanel` became
   `StepUpEnrollmentPanel` (checks
   `platformAuthenticatorIsAvailable()` before even offering the button, so
   a device with no biometric hardware sees an explanation instead of a
   button that would just fail). `ClinicalDashboard.jsx`'s PIN form became
   two paths shown together — "Verify with your device" (only shown when
   `session.has_webauthn_credential` for *this* device, itself a new field
   on `CurrentSessionView`) and "Ask a colleague to verify" (always
   available) — plus a new `AssistRequestsBanner` at the top of the
   dashboard, independent of whatever patient is open, polling every 10s for
   *other* colleagues' pending requests (matching the pending-device-badge
   cadence already used elsewhere). The Admin dashboard's Staff panel lost
   its PIN button entirely — nothing left for an admin to do here, since
   enrollment is unavoidably self-service.

   234/234 backend tests passing (rewrote the PIN-specific tests into
   `access.WebAuthnRegistrationTests`, `scoring.StepUpVerificationTests`, and
   a new `scoring.StepUpAssistTests` — real biometric ceremonies can't be
   produced in a test, so `verify_registration_response`/
   `verify_authentication_response` are mocked, same convention already
   used for `ledger.gemini.explain_entry`; the colleague-assist flow is
   fully real, no mocking needed). `npm run lint` clean. Confirmed the app
   loads with no console errors, but **could not verify the authenticated
   screens live** this round — the session active earlier in this work
   session had logged out by the time the code was ready, and only one real
   clinical account (`282828`) exists in the dev database, which isn't
   enough to exercise the colleague-assist flow (needs two). Also
   **structurally unable to verify the real biometric prompt itself** via
   browser automation regardless of login state — same category of
   limitation as a native file-picker dialog — that part needs the user's
   own physical device.

   **Follow-up live verification (2026-09-07):** once the user logged back
   in as the real doctor account (`282828`), picked the session up and
   confirmed the parts that were previously unverified. Profile page: the
   new "Step-up verification" section sits correctly between Devices and
   Change password, and — since this particular machine has no platform
   authenticator configured — correctly showed the no-hardware explanation
   rather than a button that would just fail (`platformAuthenticatorIsAvailable()`
   returning `false` renders as intended). Clinical dashboard: opening the
   one real patient produced a genuine, unprompted 50% score landing in the
   REDUCED_ACCESS band — not a constructed test case — and correctly showed
   only "Ask a colleague to verify" (no biometric on this device), with the
   exact explanatory copy and Break the Glass still available underneath,
   untouched. Clicking it created a real `StepUpAssistRequest` row
   (confirmed directly against the dev database), flipped the UI to the
   "Waiting for a colleague…" state, and Cancel correctly reverted it. No
   console errors throughout. The test assist request was deleted
   afterward; the real `AccessDecision` it hung off is genuine scoring
   output, not test data, so it was left alone. Still outstanding, and
   still needs a second real clinical account or the user's own device:
   the colleague-approve/decline side of the assist flow, and the real
   biometric ceremony itself.

   **Follow-up live verification (2026-09-17):** the colleague-approve/
   decline side above is now confirmed too. A temporary second clinical
   account (`STF-TEMP-VERIFY`, nurse) was created through the real
   `POST /api/staff/create/` API specifically for this, and a genuine
   `REDUCED_ACCESS` decision was produced for the real doctor account by
   creating a fresh session with an unrecognized device/network plus
   keystroke values tuned (via a dry-run of `scoring.engine._feature_similarity`
   before writing anything) to land inside the 40-69% band without tripping
   the hard behavioral gate — real factor inputs through the real scoring
   pipeline, not a fabricated decision object. Clicking "Ask a colleague to
   verify" in the doctor's browser tab created a real `StepUpAssistRequest`;
   logging into a second tab as the temp nurse showed it in "Colleagues
   asking for step-up verification"; Approve flipped the doctor's session to
   full record access instantly. The temp nurse account, the verification
   sessions/decisions, and the stale test `StepUpAssistRequest` rows were
   all deleted afterward — the real `EMERGENCY_OVERRIDE`/etc. Ledger entries
   this produced were left in place (append-only by design). **Still
   outstanding:** the real biometric ceremony itself needs the user's own
   physical device — structurally unreachable by browser automation, same
   category of limitation as a native file-picker dialog.

   **Amended the same day (2026-09-17, verification code added to the
   assist flow):** per the user, approving a colleague's request is no
   longer just a click — the requester's own "waiting for a colleague"
   screen now displays a system-generated 6-digit code
   (`scoring.views._generate_assist_code()`, `secrets.randbelow`, not
   `random` — this gates a real access grant), and the colleague must read
   it from the requester directly (in person or by phone) and type it into
   the shared queue's new code field before Approve goes through. This
   turns "vouching" into proof of actual contact between the two people,
   not just a remote click on a notification. New
   `StepUpAssistRequest.verification_code` (migration
   `scoring/0007_stepupassistrequest_verification_code.py`), generated once
   at request creation and never regenerated for the same pending row (a
   duplicate `/assist/request/` call, already deduplicated via
   `get_or_create`, returns the same code). **Deliberately asymmetric
   serialization:** the existing `StepUpAssistRequestSerializer` (used by
   the shared queue every *other* colleague sees, `StepUpAssistListView`)
   still never exposes the code; a new `StepUpAssistRequestOwnSerializer`
   (adds `verification_code`) is used only in `StepUpAssistRequestView`'s
   own response to the requester who just created it — exposing the code on
   the shared list would let anyone approve without ever actually
   contacting the requester, defeating the point. Wrong-code attempts don't
   get their own counter — `StepUpAssistApproveView` now checks and
   increments the *decision's* existing `step_up_failed_attempts` (via
   `hmac.compare_digest`, not `==`), the same counter/cap
   (`STEP_UP_MAX_ATTEMPTS = 3`) a failed WebAuthn attempt already uses,
   since both are just different methods through the same step-up gate; a
   wrong code raises `STEP_UP_FAILED` same as a WebAuthn failure or an
   explicit decline. Frontend: `ClinicalDashboard.jsx`'s "waiting for a
   colleague" screen shows the large code (`.assist-code-display`);
   `AssistRequestsBanner`'s shared queue gained a per-row 6-digit text input
   (`.assist-code-input`, keyed by request id since several requests can be
   pending at once) beside Approve, with its own inline error on a wrong
   code. 8/8 `scoring.StepUpAssistTests` passing (2 new: wrong code
   rejected and counts against the decision, three wrong codes locks out
   further attempts even with the eventual correct one); full backend suite
   green (282/282, see step 7's entry below for what else that run
   covered). `npm run lint`/`npm run build` clean. **Live-verified**
   end-to-end (Claude-in-Chrome, a diagnostic second clinical account
   created and deleted afterward): a genuine 51% `REDUCED_ACCESS` decision
   showed the code on the requester's screen; a wrong code on the
   colleague's side correctly showed "Incorrect code." and left the request
   pending; the real code then approved it, flipping the requester's
   session to full access, confirmed both in the UI and directly against
   the database (`step_up_verified=True`).

   **Amended the next day (2026-09-18, narrowed to on-duty/on-call
   colleagues in the requester's own ward):** per the user, confirmed via
   two `AskUserQuestion` rounds. The assist pool used to be "any other
   logged-in clinical colleague, hospital-wide" — now it's staff currently
   on duty *or* on call (equivalent everywhere else in this app — the
   Doctor rule, BTG's own gate) in the **same ward** as the requester.
   Deliberately **no hospital-wide fallback** if nobody in-ward qualifies —
   same reasoning the Nurse/Doctor rules already use for "nobody
   legitimately connected": Break the Glass exists specifically to rescue
   that case, so this doesn't need its own escape hatch. New
   `scoring.views._is_eligible_assistant(colleague, requesting_staff)`
   (`colleague.id != requesting_staff.id`, `colleague.on_duty or
   colleague.on_call`, `colleague.ward == requesting_staff.ward`) — checked
   in `StepUpAssistListView` (an ineligible caller, or one who isn't
   themselves on duty/on call, sees an empty list) **and** enforced again in
   `StepUpAssistApproveView`/`StepUpAssistDeclineView` (403, not just
   hidden from the list) so a colleague who already knows a `request_id`
   can't act on it via a direct API call either — same "not just the UI"
   posture this app already applies to step-up gating elsewhere
   (`PatientRecordView`). 11/11 `scoring.StepUpAssistTests` passing (3 new:
   different-ward colleague sees nothing and is rejected server-side,
   off-duty-and-not-on-call colleague likewise, on-call-but-not-on-duty
   colleague in the same ward is correctly still eligible) — the 8
   pre-existing tests needed no changes since their fixtures already used a
   shared ward and `on_duty=True` for both parties.
6. ✅ **Done (2026-09-12, closed out 2026-09-14).** Offline Mode. Planned via Plan Mode
   (`.claude/plans/greedy-humming-graham.md`) — full design decisions there,
   summarized here. Confirmed a hard constraint first: the real Ledger
   mints sequence/hash under a `select_for_update()` lock server-side, so a
   device can't safely pre-allocate real ledger entries while disconnected;
   and there's no JWT/offline-verifiable auth in this codebase, only opaque
   DB-backed bearer tokens, so a *fresh* offline login was ruled out --
   "devices still require local staff login" is implemented as *continuing*
   an already-authenticated session through a disconnection, not
   bootstrapping one from a cold, never-connected device.

   **Backend (implemented, tested):** `access.Device.sync_public_key`
   (migration `access/0005_device_sync_public_key.py`) plus
   `POST /api/access/devices/register-signing-key/`
   (`RegisterSyncKeyView`, self-service, 404 for an unknown device). New
   `offline_sync` app (sits after `alerts` in `INSTALLED_APPS`):
   `SyncedBatch` (idempotency guard keyed by a client-generated
   `batch_id`) and `POST /api/offline/sync/` (`OfflineSyncView`,
   `IsClinicalStaff`) -- verifies an ECDSA/SHA-256 signature (via
   `cryptography`, now a direct `requirements.txt` pin rather than only a
   transitive `webauthn` dependency) over the batch, recomputes each
   queued event's local hash chain and rejects on the first mismatch (naming
   the bad `client_seq`), then replays verified entries through the
   **existing, unchanged** `ledger.services.record_event()` one at a time
   (preserving the original offline `occurred_at`), raising a
   `SecurityAlert` for any `ACCESS_DENIED` entries -- same as
   `DecideView` already does online. Deliberately does **not** reconstruct
   `AccessDecision` rows for offline-produced events -- that model stays a
   live, request-time construct (step-up gating on an active session); the
   durable record of an offline access is the Ledger entry alone, which
   still satisfies "every decision... writes here." New
   `GET /api/scoring/my-baseline/` (`MyBaselineView`, self-service) exposes
   the caller's own frozen `BehavioralBaseline` snapshot + the Disaster Mode
   flag, for the frontend to cache. 249/249 backend tests passing (15 new:
   `access.RegisterSyncKeyViewTests`, `offline_sync.OfflineSyncViewTests`,
   `scoring.MyBaselineViewTests`) -- covering valid-batch merge, bad
   signature, tampered local chain (specific position reported), unregistered
   device, duplicate `batch_id` idempotency, and denial-raises-alert.

   **Frontend (implemented, not yet live-verified end-to-end -- see below):**
   new `frontend/src/offline/` module (`db.js` -- IndexedDB via the new
   `idb` dependency, four stores: `cache`/`session`/`queue`/`keys`;
   `crypto.js` -- per-device non-extractable ECDSA signing keypair + AES-GCM
   encryption key, so cached patient data is genuinely encrypted at rest
   without a password-derived key; `localLedger.js` -- the device-local hash
   chain, a *separate, simpler* scheme from the real Ledger's
   (`_compute_entry_hash`'s exact field set), whose only job is proving the
   local queue wasn't tampered with before reaching the server, not
   reproducing the production chain; `scoringEngine.js` -- a JS port of
   `scoring/engine.py`'s role-ceiling/band/Nurse-Doctor-rule logic, with one
   documented simplification: of the 7 weighted factors, only
   `on_duty`/`ward_assignment` actually vary per patient within a session,
   so the other five are reused from the most recent successful *online*
   decision's `factor_breakdown` rather than re-deriving keystroke/mouse
   dynamics offline; `syncManager.js` -- ties it together:
   `refreshOfflineCache()` (called after every successful online
   decide()+records fetch -- this is how "last-synced cache" builds up from
   normal use, no separate download step), `queueOfflineEvent()`,
   `trySync()`, `ensureSigningKeyRegistered()`). `ClinicalDashboard.jsx`'s
   `openPatient`/`handleEmergencyOverride` both gained an offline branch
   (triggered when a real request fails with no HTTP status, i.e. a genuine
   network failure, not a server rejection) that computes a decision from
   the cache instead of failing; a header badge
   (`DashboardShell.jsx`'s new `offlineStatus` prop) shows
   "Offline"/"N pending sync". An offline `REDUCED_ACCESS` decision still
   excludes categories 8–11/13 but can't perform WebAuthn/colleague-assist
   step-up (both need the server), so it's logged with
   `step_up_deferred_offline: true` instead of blocking forever --
   reviewable via the existing Ledger drilldown once synced, no new UI
   needed. `App.jsx` registers the device's signing key once per login
   (clinical roles only) and resyncs on the browser's `online` event, backed
   by a plain 10s poll too (`ClinicalDashboard.jsx`'s
   `OFFLINE_SYNC_POLL_MS`) so a demo that simulates disconnection by
   stopping the local Django server -- rather than toggling real network
   conditions -- still recovers, since `navigator.onLine` never flips in
   that scenario. `npm run lint`/`npm run build` both clean.

   **Found and fixed one real bug during live testing:** the `staff` prop
   `ClinicalDashboard` receives is deliberately minimal (staff_id/full_name/
   role only, see `App.jsx`) and doesn't carry `on_duty`/`on_call`/`ward` --
   the first offline-cached "staff" snapshot used it directly, so an offline
   decision's on-duty factor silently scored as if always off-duty,
   producing a real, wrong score (65% offline vs. the correct 85% online for
   the same session). Fixed with a new `offlineStaffSnapshot(staff,
   session)` helper that merges the two, used everywhere "staff" gets
   cached for offline use. Also hardened the online success path while
   investigating: caching for offline use is now genuinely fire-and-forget
   (previously it `await`ed an extra `getCachedSession()` call inline,
   meaning any IndexedDB slowness would have blocked the already-successful
   online view from rendering -- `refreshOfflineCache()` now defaults
   `disasterModeActive` to whatever's already cached instead of requiring
   the caller to re-fetch it just to preserve that one field).

   **Live end-to-end verification, completed 2026-09-14** (Claude-in-Chrome,
   real doctor account `282828`, real patient `iuyjcghh`), after two real
   bugs surfaced and got fixed along the way:

   - The Chrome tab used for the first verification pass hit a genuine
     browser storage-service lockup specific to the `medguard-offline`
     IndexedDB database (`indexedDB.open()` hung indefinitely, reproduced
     in a brand-new tab, while a differently-named database on the same
     origin opened instantly) -- not application code, confirmed by that
     clean control test. Resolved once the user cleared that site's
     browser storage; not expected to recur, but if it ever does, clearing
     site data for the frontend's origin is the fix.
   - **A real, more serious bug found using "Verify ledger integrity"
     itself**, which came back invalid after the first successful offline
     sync: `ledger.services.record_event()` hashed `occurred_at` using
     whatever timezone a caller's datetime happened to carry, but
     `offline_sync.OfflineSyncView` passes an *explicit* `occurred_at`
     (the original offline timestamp) that arrives through DRF's
     `DateTimeField`, which converts it to Django's configured local
     timezone (`settings.TIME_ZONE = 'Africa/Lagos'`, +01:00) --
     while the same field read back from the database later always comes
     back in UTC. Same instant, two valid ISO-string representations,
     different hash. Every *normal* online decision was unaffected (they
     never pass an explicit `occurred_at`, always defaulting to
     `timezone.now()`, already UTC) -- this only ever hit offline-synced
     entries. Fixed at the source: `record_event()` now normalizes
     `occurred_at` to UTC once, before it's used for both the hash and the
     saved row, regardless of what timezone the caller's datetime carries.
     New regression tests added:
     `ledger.tests.RecordEventChainTests.test_explicit_non_utc_occurred_at_still_verifies`,
     and `offline_sync.tests.OfflineSyncViewTests.test_valid_batch_merges_into_ledger`
     now also asserts `verify_chain()` passes (previously only checked
     field values, which is why this shipped without a failing test in
     the first place). 251/251 backend tests passing.
   - The bug had already written two bad-hash entries to the real local
     dev Ledger before the fix (`ledger.sqlite3`) -- unlike a code bug,
     an already-computed Ledger hash can't be repaired in place by
     design (append-only, by CLAUDE.md's own Security Ledger spec).
     Confirmed via `AskUserQuestion` with the user: since nothing is
     deployed yet and this only affected the local dev Ledger (not
     `db.sqlite3`, where all real staff/patient/session data lives,
     untouched), the local `ledger.sqlite3` file was deleted and
     recreated empty via `manage.py migrate --database=ledger` --
     the real doctor/patient/admin accounts and their sessions all
     survived intact, confirmed live (the same browser session kept
     working through the reset with no re-login needed).
   - Final full round trip against the fresh, empty Ledger: online decide
     (real 88% `AUDITED_DEVIATION`) → backend stopped → offline `View`
     click computed the identical decision from cache and queued it (header
     showed "1 pending sync") → backend restarted → the 10s poll
     auto-synced it with no user action → header badge cleared → both
     resulting Ledger entries (#1 online, #2 offline-synced) verify
     correctly end to end. No console errors throughout.
7. ✅ **Done (2026-09-14), with one scope gap flagged below.** Bonus:
   MedGuard Identity — fingerprint matching, emergency/offline lookup only.
   Planned via Plan Mode after two real hardware constraints got worked
   through with the user (confirmed via `AskUserQuestion`, multiple rounds):

   - The user's phone, then laptop (Windows Hello), were both proposed as
     the capture method — both ruled out on hard technical grounds, not
     preference. Every consumer platform fingerprint sensor (phone or
     laptop) locks the scan in a hardware secure enclave and will only ever
     answer "same owner, yes/no" for unlocking that one device — the same
     mechanism the step-up WebAuthn feature (5b) already relies on. This
     feature needs the opposite: *identification* mode (whose record is
     this, out of everyone enrolled), which requires actually seeing the
     fingerprint pattern to compare against a database. No web app, this
     one included, can ever get that out of a phone/laptop sensor — it's a
     deliberate security boundary, not a gap to code around. Settled on
     real fingerprint *images* (a photo/scan of an actual finger) instead.
   - **SourceAFIS, the library CLAUDE.md names, has no official Python
     port** (verified via `WebSearch` — only Java and .NET, under
     robertvazan's GitHub org). Rather than shelling out to a Java
     subprocess, substituted a real, comparable pure-Python pipeline,
     confirmed with the user: `fingerprint-feature-extractor` (PyPI, MIT)
     for minutiae extraction — read its actual source before committing to
     it; it's the standard textbook algorithm (ridge skeletonization via
     `skimage.morphology.skeletonize`, then real crossing-number minutiae
     detection), not a toy. It has no matching component, and a second
     candidate package found during research (`fingerprints-matching`) was
     downloaded and rejected after reading its source — its "matching"
     never aligns the two minutiae sets before comparing raw coordinates,
     which only works if both images happen to already be identically
     framed, not legitimate for two independent scans. Matching
     (`identity/matching.py`) is hand-written instead: the standard
     simplified minutiae-pair rigid-alignment technique (try every
     same-type probe/template minutia pair as a candidate rotation+
     translation, count how many other minutiae land in tolerance under
     that transform, keep the best) — real point-pattern matching, just
     simpler than SourceAFIS's own approach, in the same "deliberately
     simple, explainable... appropriate for a hackathon demo" spirit
     CLAUDE.md's Scoring Engine section already uses for its own matching.

   New `identity` Django app: `FingerprintTemplate` (`OneToOneField` to
   `Patient` — re-enrolling replaces the template, same pattern
   `access.WebAuthnCredential` already uses), `encrypted_template` (Fernet/
   AES, `identity/crypto.py`, keyed by a new `settings.FINGERPRINT_
   TEMPLATE_KEY`) — never the raw image, which is decoded and processed
   entirely in memory (`identity/extraction.py`, OpenCV) and discarded, not
   even written to a temp file. `POST /api/identity/enroll/` (`IsAdmin`,
   multipart `{patient_id, image}`, rejects images yielding fewer than 5
   minutiae as unusable) and `POST /api/identity/identify/`
   (`IsClinicalStaff`, multipart `{image}`, deliberately no `patient_id`)
   — the latter scores the probe against every enrolled template and
   returns the best match above `settings.FINGERPRINT_MATCH_THRESHOLD`
   (default 40) or a plain "no match" (an expected outcome, not an error).
   A match returns a MINIMAL emergency summary assembled from existing
   category data (blood type, allergies, current meds, current diagnoses,
   next of kin) — not the full 13-category record, matching CLAUDE.md's own
   example wording exactly. One small schema addition:
   `patients/category_fields.py` category 3 gained `blood_type` (CLAUDE.md's
   own example names it; nothing existing carried it). Not routed through
   the Security Ledger and no new audit table — same precedent as
   `DisasterModeEvent`/`PendingDeviceRequest`, kept bounded as the bonus
   feature. `opencv-python-headless` used instead of the extractor
   package's declared desktop `opencv-python` (same `cv2` API, no GUI
   bindings a server needs); the extractor itself is installed with
   `--no-deps` (`render.yaml`'s `buildCommand` extended accordingly) so a
   plain `pip install -r requirements.txt` never pulls the heavier desktop
   build in alongside it.

   Frontend: Admin dashboard's Patient panel gained an "Enroll / replace
   fingerprint" file upload (same click-a-label-to-open-the-picker pattern
   `ProfilePhotoSection` already uses). Clinical dashboard gained a new
   "Emergency fingerprint lookup" collapsible section at the top of the
   page (same visual weight as the existing assist-requests banner) —
   deliberately not gated behind selecting a patient first, since this *is*
   the patient-selection step for this flow; a match's "View full record"
   button feeds the found patient straight into the normal `openPatient`
   access-decision flow.

   16 new backend tests (`identity/tests.py`): matching tested directly
   against synthetic minutiae (identical sets score 100; a known rotation+
   translation still scores ~100, proving the alignment step actually
   works, not just trivial self-comparison; unrelated sets score low; empty
   sets score 0) — no real images needed for this part. Extraction tested
   against a synthetic ridge-like test image (deterministic — same bytes
   always extract the same minutiae, which the enroll-then-identify-the-
   same-photo view test relies on rather than hardcoding expected minutiae
   counts). View tests cover the full enroll→identify round trip, no-match
   cases, admin/clinical-only role gates, re-enrollment replacing rather
   than accumulating, and that raw image bytes never persist anywhere.

   **Scope gap, flagged deliberately rather than half-built: online only.**
   CLAUDE.md's own wording says "emergency or offline lookup." Real
   extraction+matching client-side (mirroring Offline Mode's JS scoring-
   engine port) would need ridge skeletonization and image processing
   ported to JS with no ready library for it — a genuinely large separate
   lift, not attempted here. This covers the "emergency, unconscious
   patient" half of the use case as long as there's connectivity; true
   network-down fingerprint lookup remains a known, documented gap, not a
   silently-missed one.

   **Not yet live-verified against a real fingerprint** — CLAUDE.md's
   Enrollment data rule means that needs the user's own real finger, not
   synthetic test data; pending once supplied.

   **Amended (2026-09-17, offline gap closed):** the "online only" gap
   above is closed. Planned via Plan Mode (`.claude/plans/
   greedy-humming-graham.md`); confirmed via `AskUserQuestion` that the
   device caches the **full enrolled-patient roster** (every patient's
   template + emergency summary), not just previously-viewed patients — a
   partial cache would defeat identifying a patient this specific device
   has never opened before, the exact "unconscious stranger" case this
   feature exists for.

   New `GET /api/identity/offline-bundle/` (`OfflineFingerprintBundleView`,
   `IsClinicalStaff`) decrypts every `FingerprintTemplate` server-side and
   returns the plaintext minutiae + the same minimal emergency summary
   `identify()` already exposes, for the device to re-encrypt at rest
   immediately on receipt — same protection level `refreshOfflineCache`
   already gives full patient records. Frontend: `db.js` gained a
   `fingerprints` IndexedDB store (bumped `DB_VERSION` to 2); new
   `offline/fingerprintCache.js` caches the whole roster as one AES-GCM-
   encrypted blob (matching always scans the whole roster anyway, mirroring
   `IdentifyFingerprintView`'s own loop); refreshed best-effort on mount/
   reconnect from `ClinicalDashboard.jsx`'s existing online/offline effect,
   same silent-failure posture as `ensureSigningKeyRegistered()`.

   The real new work: `offline/fingerprintExtraction.js`, a from-scratch
   Canvas-2D-only port of `identity/extraction.py`'s pipeline (resize to
   the same `CANONICAL_SIZE=400` → real tiled CLAHE with clip+redistribute+
   bilinear blend, kept in scope rather than simplified away since it was
   the actual fix for a real backend lighting bug already → Otsu threshold
   → Zhang-Suen thinning → crossing-number minutiae detection), and
   `offline/fingerprintMatching.js`, a direct port of `matching.py`'s
   spatial-grid rigid-alignment `similarity_score` (own tolerance
   constants, separate from the backend's). `FingerprintLookup`
   (`ClinicalDashboard.jsx`) now takes an `online` prop: online behavior is
   unchanged (server stays authoritative when reachable); offline, it runs
   this pipeline against the cached roster instead.

   **Known, stated-up-front risk:** enrollment stays online-only (Admin-
   only, deliberate — nothing in CLAUDE.md's spec asks for offline
   enrollment), so an offline probe (JS-extracted) is always matched
   against a template extracted by the *Python* pipeline — cross-pipeline
   matching, not the same-pipeline matching the online path has. The two
   pipelines won't compute minutiae angle identically (Python's comes from
   `fingerprint_feature_extractor`'s own orientation estimation, not
   something a from-scratch client-side port can replicate exactly), so
   offline match accuracy is honestly expected to be lower than online
   until a live-tuning pass — mirroring what already happened to the
   *online* path itself (a real performance bug, then a real accuracy bug,
   both only found by testing against real photos). This is why the
   tolerance constants live in their own file, separate from the backend's.

   A new `emergencySummaryOnly` fallback was added to `openPatientOffline`
   (`ClinicalDashboard.jsx`): previously, a cache-miss there always meant
   "this patient hasn't been viewed offline yet, dead end" — but a
   fingerprint match against the on-device roster can legitimately find a
   patient this device has *never* opened before (the exact case this
   whole feature exists for). When that happens, the roster's own bundled
   emergency summary renders directly (blood type, allergies, meds,
   diagnoses, next of kin) instead of the generic error — no decision is
   computed and nothing is queued to the local ledger, since identification
   isn't access-decisioning (matches the online `IdentifyFingerprintView`
   itself, which never calls `record_event` either). If the device *does*
   already have this patient's full record cached, behavior is unchanged.

   3 new backend tests (`identity/tests.py`,
   `OfflineFingerprintBundleViewTests`) — full suite green. No JS test
   runner exists in this frontend (same limitation `scoringEngine.js`'s own
   header comment already documents) — verified live instead
   (Claude-in-Chrome): logged in as the real doctor account, confirmed the
   roster downloads and caches encrypted in IndexedDB on a normal login;
   simulated a real network outage (not just the `online`/`offline` DOM
   events — `window.fetch` itself rejects any request to the backend, so a
   latent bug couldn't silently fall through to the real server); fed a
   synthetic (non-enrolled) test image through the offline "Search by
   fingerprint" flow and confirmed it ran the full extraction+matching
   pipeline against the cached roster with zero network calls and correctly
   reported "No match found" — no crash, no console errors. **Not yet
   verified with a real matching fingerprint photo** (same Enrollment data
   constraint as the original online build — needs the user's own finger)
   or the `emergencySummaryOnly` fallback specifically (the one real
   enrolled patient was already cached on the test device from earlier in
   the same session, so a genuine never-before-seen-patient match couldn't
   be produced without fabricating data) — both pending live confirmation
   from the user, and per the plan's own "Known risk" section, the first
   of those may surface a real need to loosen `fingerprintMatching.js`'s
   tolerances, a one-line follow-up if so.

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
