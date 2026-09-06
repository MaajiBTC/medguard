# MedGuard

**A security and access-control layer for patient records.**

Built for **Track C — "Safe Access to Patient Records"** of the ICSC 2026
Universities Hackathon, scoped to Nigerian hospitals and Nigerian law.

---

## The problem

In most hospital systems, "who can see this patient's file?" is answered once,
at login. If your account says *doctor*, you see everything — every patient,
every category, every time, with no distinction between the consultant treating
the patient and a logged-in workstation someone walked away from.

That is how real breaches happen: not by breaking encryption, but through a
legitimate account being used illegitimately. A curious staff member looking up
a celebrity admission. A shared terminal left unlocked. A leaked password used
at 3am from a ward the account holder has never worked on.

MedGuard sits **in front of** the records system and answers a harder question
on every single access: *is this really you, are you meant to be here right
now, and how much of this record does this particular moment justify?*

**MedGuard is a security layer, not a hospital management system.** It does not
do booking, billing, or scheduling. Every feature here serves authentication,
access control, or audit.

---

## Legal grounding (Nigeria)

| Requirement | Where MedGuard addresses it |
|---|---|
| **National Health Act 2014** — confidentiality of patient information; disclosure only where authorised | Role→category ceilings, the Nurse and Doctor rules, and the reduced-access band all constrain disclosure per access, not per account |
| **Nigeria Data Protection Act 2023** — health data is sensitive personal data; requires proportionate technical measures and accountability | Behavioural + contextual signals, step-up verification for lower-trust sessions, one-device-per-account, brute-force lockout, and a tamper-evident audit trail |
| **NDPA 2023** — demonstrable accountability | The hash-chained Security Ledger records every decision, grant *and* denial, and can be re-verified on demand |
| **Patients' Bill of Rights** — right to confidentiality and to know how records are handled | Per-patient access history, viewable by a security officer, showing exactly which staff opened which record and when |

---

## How access is decided

Access is **two-dimensional**. Role sets the ceiling; the session's trust score
decides how much of that ceiling is actually granted this time.

### 1. Role sets the ceiling

The 13 record categories are: Identity · Administrative/Billing · Vital Signs ·
Diagnosis & History · Medication · Allergies · General Lab Results · **Highly
Sensitive Results** · **Mental Health** · **Reproductive Health** ·
Surgical History · Nursing Notes · Imaging.

| Role | Categories |
|---|---|
| Doctor | 1–13 |
| Nurse | 1–13 (via one of three paths — see below) |
| Pharmacist | 1, 4, 5, 6, 7 |
| Lab technician | 1 |
| Clerk | 1, 2 |

*Admin* and *security officer* are system roles — they never request patient
categories at all.

### 2. Signals are captured, then scored

Two capture modules record raw signals and make no decisions:

- **Behavioural** — keystroke rhythm (derived timing features only, never key
  identity), mouse dynamics, touch dynamics.
- **Contextual** — login time, device, network segment/ward, on-duty and
  on-call status, ward assignment, and whether this staff member is
  *specifically assigned* to this patient.

The **Scoring Engine** then decides:

**A hard gate runs first.** A severe behavioural mismatch — typing rhythm
wildly unlike the stored baseline — denies access outright. Nothing
compensates for it.

**Then seven weighted factors:**

| Factor | Weight |
|---|---|
| Keystroke/touch dynamics | 30% |
| On-duty status | 20% |
| Ward assignment | 15% |
| Mouse dynamics | 15% |
| Device recognition | 10% |
| Login-time normalcy | 7% |
| Location/network | 3% |

### 3. The score decides how much opens

| Score | Result |
|---|---|
| 90–100% | Full role access, silent |
| 70–89% | Full role access, **logged as an audited deviation** |
| 40–69% | **Reduced access** — sensitive categories (8–11, 13) withheld, **and a step-up PIN is required before anything opens** |
| Below 40% | **Denied**, and a security alert is raised for review |

**Worked example:** a doctor on duty, everything matching except ward
assignment → 85% → full access, but permanently flagged as a deviation.

### Role-specific rules

- **Nurse** — assigned to the patient → normal scoring. Not assigned but on the
  same ward → access granted but *always* logged as a deviation. Neither →
  hard denied, regardless of score.
- **Doctor** — off duty, not on call, and no connection to the patient at all →
  hard denied, regardless of score.

Both are suspended hospital-wide while **Disaster/Mass Casualty Mode** is
active.

---

## Key features

**Break the Glass** — emergency override, always available, one action, capped
at the caller's role ceiling. Requires a reason category and written
justification, and is permanently logged and un-deletable.

**Security Ledger** — append-only and hash-chained (each entry contains the
hash of the previous one), stored in a **separate database** from the main
application so a compromised app cannot rewrite its own trail. Enforced at
three levels — instance saves, bulk queryset operations, and the separate
database — with `verify_chain()` as the backstop against direct database
tampering. A security officer can **re-verify the entire chain on demand** from
the dashboard.

**Security alerts** — every denial, lockout, and failed step-up raises an alert
that a security officer must acknowledge. Logging something nobody reads isn't
accountability.

**One device per clinical account** — the first device to log in becomes the
primary; any other device must be approved by the account holder on their
existing device before it gets a session.

**Brute-force lockout** — repeated failed logins lock an account temporarily.
A correct password during a lockout is still refused, so an attacker who
finally guesses right gets no signal that they did.

**MedGuard AI explanation** — a security officer can turn any ledger entry's
raw factor breakdown into plain English, so investigating a deviation doesn't
require reading JSON.

---

## Architecture

```
React + Vite frontend
   |  behavioural + contextual capture (browser)
   v
Django REST Framework API
   |
   +-- staff      roles, wards, duty status, step-up PINs, admin audit
   +-- patients   patients, assignments, 13 category records
   +-- access     sessions, devices, login attempts/lockout
   +-- captures   behavioural + contextual signals (capture only)
   +-- scoring    the engine: gate, weights, bands, role rules, BTG
   +-- alerts     security alerts + acknowledgement workflow
   +-- ledger     hash-chained audit trail  --> SEPARATE DATABASE
```

Three role-routed dashboards share one login page: **Clinical** (search →
decision → records), **Admin** (staff, patients, assignments, disaster mode),
and **Security** (ledger feed, alerts, staff/patient activity).

---

## Running it locally

**Requires:** Python 3.12+, Node.js LTS. On Windows use the `py` launcher.

### Backend

```bash
cd backend
py -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then edit it — see below
python manage.py migrate
python manage.py migrate --database=ledger
python manage.py runserver 0.0.0.0:8000
```

Note the **two** migrate commands — the Security Ledger lives on its own
database connection by design.

Create the first admin account (there is no dashboard to create it from yet):

```bash
python manage.py create_staff_account --username <name> --staff-id <id> \
  --full-name "<full name>" --role admin
```

It reads the password from `STAFF_LOGIN_PASSWORD` in your environment, so no
password is ever typed into a command line or committed.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open the printed URL (usually `http://localhost:5173`).

### Environment variables

See `backend/.env.example` for the full list. The essentials:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret — generate a fresh one, never reuse |
| `DEBUG` | `True` locally, unset/`False` in production |
| `DATABASE_URL` | Main database (Render sets this automatically) |
| `LEDGER_DATABASE_URL` | Ledger database — ideally a *different* provider |
| `STAFF_LOGIN_PASSWORD` | Used by `create_staff_account` |
| `GEMINI_API_KEY` | Optional — enables AI ledger explanations |
| `LOGIN_MAX_FAILED_ATTEMPTS` | Lockout threshold (default 5) |
| `LOGIN_LOCKOUT_MINUTES` | Lockout duration (default 15) |

**Never commit `.env`.** It is gitignored.

---

## Tests

```bash
cd backend
python manage.py test          # whole suite
python manage.py test scoring  # one app
```

```bash
cd frontend
npm run lint
```

The suite runs against Django's throwaway test databases and never touches the
real one. **No synthetic staff, patient, or fingerprint data is ever generated**
— test fixtures exist only inside the isolated test database.

---

## Deployment

`render.yaml` (backend) and `frontend/vercel.json` (frontend) are included.

On Render, the blueprint provisions the web service and both databases, runs
migrations for each, and collects static files. Set `SECRET_KEY`,
`STAFF_LOGIN_PASSWORD`, and optionally `GEMINI_API_KEY` in the dashboard.

On Vercel, set `VITE_API_BASE_URL` to your Render backend's `/api` URL.

**Known limitation:** uploaded staff photos are stored on local disk, and
Render's free tier has an ephemeral filesystem — photos won't survive a
redeploy there. Swap in object storage if that matters for your deployment.

---

## Suggested demo path

1. **Normal access** — a doctor on duty opens an assigned patient. Full access,
   silently logged.
2. **Audited deviation** — same doctor, a patient on another ward. Access still
   granted, but permanently flagged.
3. **Reduced access** — a session scoring 40–69%. Sensitive categories are
   withheld *and nothing opens at all* until the step-up PIN is entered.
4. **Hard denial** — a nurse neither assigned to nor sharing a ward with the
   patient. Denied regardless of score, and a security alert is raised.
5. **Break the Glass** — the same nurse overrides with a logged justification,
   and gets exactly her role ceiling, nothing more.
6. **The Security Dashboard** — every one of the above appears in the live
   feed. Open a deviation, read the factor breakdown, translate it with AI, and
   acknowledge the alert.
7. **Prove the trail** — click **Verify ledger integrity**. Then edit a ledger
   row directly in the database and click it again: it names the exact entry
   that was altered.

---

## Status

Built: capture modules, scoring engine, security ledger, all three dashboards,
Break the Glass, disaster mode, device binding, step-up verification, security
alerts, and login lockout.

Planned: offline mode, and MedGuard Identity (fingerprint-based patient
identification for emergency and offline lookup, using SourceAFIS).
