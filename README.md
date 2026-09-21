# 🛡️ MedGuard — Safe Access to Patient Records

> **Behavioural and contextual access control for hospital record systems — it assumes the password is already stolen**

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![Django](https://img.shields.io/badge/Django-6.1-092E20.svg)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/DRF-3.18-a30000.svg)](https://django-rest-framework.org)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev)
[![Tests](https://img.shields.io/badge/backend%20tests-312-brightgreen.svg)](#-development)
[![Track](https://img.shields.io/badge/ICSC%202026-Track%20C-6528D9.svg)](#)

## 🌟 Overview

Hospital record systems protect patient data the way most software does: with a
username and a password. That guards the front door and nothing behind it. Once
someone is inside holding valid credentials, they are rarely asked another
question — and in a hospital the most common breach is not a break-in. It is a
**legitimate account used for an illegitimate reason**: a curious colleague
looking up a well-known admission, a shared password, a staff member checking on
a neighbour they have no clinical involvement with.

MedGuard is a **security and access-control layer** that sits in front of a
hospital's existing record system, built to complement it rather than replace
it. Instead of asking only *"is this a valid login?"*, it asks a harder question
every time a record is opened:

> **Is this the right person, with a legitimate reason, right now?**

It is deliberately **not** a hospital management system — no booking, billing or
scheduling appears anywhere in it. Every component earns its place by serving
**authentication, access control, or audit**.

Built for **Track C (Safe Access to Patient Records)** of the ICSC 2026
Universities Hackathon, scoped to Nigerian hospitals and Nigerian law.

## ⚖️ Legal grounding (Nigeria)

| Instrument | What it requires | How MedGuard answers it |
|---|---|---|
| **National Health Act 2014** | Patient information is confidential; the duty to protect it sits on the health establishment | Access is decided per request, not per login, and every decision is permanently recorded |
| **Nigeria Data Protection Act 2023** | Personal data processed lawfully, for a specified legitimate purpose, and no further | Role ceilings cap what each role may ever see; the reduced band withholds the most sensitive categories outright |
| **Patients' Bill of Rights** | Confidentiality of records | The patient is notified by SMS whenever their own record is touched in a way the system considers noteworthy |

## ✨ Key Features

### 🧠 **Two-dimensional access decisions**
- **Role ceiling**: what this role could *ever* see, across 13 record categories
- **Session score**: how much of that ceiling is actually released this time
- **Hard behavioural gate**: a typing rhythm wildly unlike the stored baseline denies access outright, before any score is computed — nothing compensates for it
- **Role rules that outrank the score**: explicit Nurse and Doctor carve-outs for situations a number should not decide

### 👤 **Behavioural + contextual capture**
- **Keystroke dynamics**: flight time, digraph/trigraph latency, correction rate, rhythm consistency, automation flags
- **Mouse + touch dynamics**: trajectory, speed, acceleration, click and tap timing
- **Contextual signals**: login time, device, network segment, on-duty, on-call, ward, patient assignment
- **Privacy by construction**: keystroke capture stores **timing only — never which key was pressed**, so the password is unrecoverable from what is stored

### 🔐 **Identity and session security**
- **One device per clinical account** — an unrecognised device gets an approval request the account owner resolves from their own device, *not* a session token
- **Brute-force lockout** — 5 failures in 15 minutes, derived from the attempt log so it expires by itself; a correct password during lockout is still refused
- **Step-up verification** — the device's own biometric via WebAuthn (the server never sees the fingerprint or face), with **colleague vouching** as the fallback, gated by a six-digit code the requester must read out in person

### 🚨 **Break the Glass**
- One action grants the caller's **full role ceiling** — bypassing the gate, the band and assignment matching, but never the ceiling itself
- A reason category **and** written justification are mandatory, stored permanently, and editable by nobody
- **Withheld and hidden** in the one combination where the system has already concluded there is no legitimate reason to be looking
- **Disaster / Mass Casualty Mode** suspends duty-based denials hospital-wide, audited in its own history table

### 📒 **The Security Ledger**
- **Hash-chained**: every entry carries a SHA-256 hash of itself and its predecessor, so altering any historical row breaks every hash after it
- **Physically separate database**, so a compromise of the application cannot rewrite its own trail
- **Append-only at every level** — individual saves/deletes blocked, and so are bulk queryset updates that would otherwise slip past instance guards
- **One-click verification** reporting either an intact chain or the exact entry where tampering begins

### 📡 **Offline mode**
- Decisioning and Break the Glass keep working with **no network at all** — the scoring engine runs on the device against the last synced cache
- **Two kinds of cache**: full records for patients already opened online, plus a **minimal emergency summary** (blood type, allergies, medication, diagnoses, next of kin) for every patient on that clinician's own ward
- **A session must already exist** — verifying a login needs the server, so the device can never approve one by itself
- Events queue in a **local hash chain**, signed with a non-extractable per-device key, and merge only after the server verifies both

### 🫆 **MedGuard Identity (fingerprint lookup)**
- Identifies an **unconscious or unidentified patient** — identification mode, not authentication: the fingerprint is a pointer to a record, never a password
- Real minutiae extraction (ridge skeletonisation + crossing-number detection) and rigid-alignment matching with strict one-to-one pairing
- **Encrypted templates only** — raw images are processed in memory and never persisted
- Works offline against an encrypted on-device roster

### 📱 **Patient notification**
- A real **SMS via Twilio** whenever a record is accessed in a way the scoring bands already treat as noteworthy — clean access stays silent, so the signal never becomes noise
- Every attempt is recorded whether or not it could be sent, and a notification failure can never break the clinician's own access decision

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  React 19 + Vite frontend                   │
├─────────────────────────────────────────────────────────────┤
│  Clinical  │  Admin  │  Security   dashboards, one login    │
│  behavioural + contextual capture · offline engine (IndexedDB)│
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                Django REST Framework API                    │
├─────────────────────────────────────────────────────────────┤
│  staff     roles, wards, duty status, admin audit           │
│  patients  patients, assignments, 13 category records       │
│  access    sessions, devices, login attempts, WebAuthn      │
│  captures  behavioural + contextual signals (capture only)  │
│  scoring   THE ENGINE: gate, weights, bands, role rules,BTG │
│  alerts    security alerts + acknowledgement workflow       │
│  identity  fingerprint enrolment + matching                 │
│  offline_sync / notifications                               │
└─────────────────────────────────────────────────────────────┘
          │                                    │
┌───────────────────────┐        ┌─────────────────────────────┐
│  Application database │        │  LEDGER DATABASE (separate) │
│  PostgreSQL / SQLite  │        │  hash-chained, append-only  │
└───────────────────────┘        └─────────────────────────────┘
```

Three role-routed dashboards share one login page: **Clinical** (find patient →
decision → records), **Admin** (staff, patients, assignments, disaster mode),
and **Security** (ledger feed, alerts, staff/patient activity).

## 🎯 How a decision is made

A doctor is on duty, on a recognised device, at a normal hour, on the hospital
network, typing normally — but opens a patient they are **not** assigned to and
who is **not** on their ward:

| Factor | Weight | Result |
|---|---|---|
| Keystroke / touch dynamics match | 30% | ✅ 30 |
| On-duty status | 20% | ✅ 20 |
| **Ward assignment** | 15% | ❌ **0** |
| Mouse dynamics match | 15% | ✅ 15 |
| Device recognition | 10% | ✅ 10 |
| Login-time normalcy | 7% | ✅ 7 |
| Location / network match | 3% | ✅ 3 |
| | | **= 85%** |

That lands in the 70–89% band:

| Score | Outcome |
|---|---|
| 90–100% | Full role-permitted access, silent |
| **70–89%** | **Full access, logged as an audited deviation** |
| 40–69% | Reduced access — sensitive categories withheld **and nothing opens** until step-up verification |
| Below 40% | Access denied, security alert raised |

So the doctor gets the full record they need for care, and the system files it
as an audited deviation for the Security Officer to review. **Care is never
blocked by a technicality — but it is never invisible either.**

### Role ceilings

| Role | Categories | Condition |
|---|---|---|
| Doctor | 1–13 | Subject to the Doctor rule |
| Nurse | 1–13 | Subject to the Nurse rule |
| Pharmacist | 1, 4, 5, 6, 7 | Identity, diagnoses, medication, allergies, labs |
| Lab technician | 1 only | Identity only — enough to label a sample |
| Clerk | 1, 2 only | Identity and administrative/billing |

## 🚀 Quick Start

### Prerequisites

- Python 3.12+ (on Windows use the `py` launcher)
- Node.js LTS
- A Google Gemini API key (optional — enables AI ledger explanations)
- A Twilio account (optional — enables patient SMS)

### Backend

```bash
cd backend
py -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
pip install fingerprint-feature-extractor==0.0.10 --no-deps
cp .env.example .env           # then edit it — see below
python manage.py migrate
python manage.py migrate --database=ledger
python manage.py runserver
```

> ⚠️ Note the **two** migrate commands. The Security Ledger lives on its own
> database connection by design — `migrate` alone leaves its tables missing.

Create the first admin account (there is no dashboard to create one from):

```bash
python manage.py create_staff_account --username <name> --staff-id <id> \
  --full-name "<full name>" --role admin
```

It reads the password from `STAFF_LOGIN_PASSWORD` in your environment, so no
password is ever typed on a command line or committed.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open the printed URL — usually `http://localhost:5173`.

## 📋 Environment Variables

See `backend/.env.example` for the full list. The essentials:

```env
# Core
SECRET_KEY=generate_a_fresh_one_never_reuse
DEBUG=True
DATABASE_URL=                       # Render sets this automatically
LEDGER_DATABASE_URL=                # ideally a DIFFERENT provider

# Account bootstrap
STAFF_LOGIN_PASSWORD=used_by_create_staff_account

# Optional integrations
GEMINI_API_KEY=                     # AI ledger explanations
TWILIO_ACCOUNT_SID=                 # patient SMS
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
FINGERPRINT_TEMPLATE_KEY=           # Fernet key for fingerprint templates

# WebAuthn — must match the FRONTEND's domain, not the backend's
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGIN=http://localhost:5173

# Lockout tuning
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
```

> 🔑 **Never commit `.env`.** It is gitignored.

## 🛠️ Development

### Project structure

```
medguard/
├── backend/
│   ├── config/              # settings, urls, database router
│   ├── staff/               # roles, wards, duty, admin audit log
│   ├── patients/            # patients, assignments, 13 categories
│   ├── access/              # sessions, devices, lockout, WebAuthn
│   ├── captures/            # behavioural + contextual capture
│   ├── scoring/             # the engine, Break the Glass, disaster mode
│   ├── ledger/              # hash-chained audit trail (own database)
│   ├── alerts/              # security alerts + acknowledgement
│   ├── identity/            # fingerprint extraction + matching
│   ├── offline_sync/        # signed offline batch merge
│   └── notifications/       # patient SMS via Twilio
├── frontend/src/
│   ├── pages/               # Clinical / Admin / Security dashboards
│   ├── capture/             # behavioural + contextual capture
│   ├── offline/             # IndexedDB, crypto, local ledger, JS engine
│   └── api/                 # typed API client per backend app
├── render.yaml              # backend + both databases
└── CLAUDE.md                # full design record and decision history
```

### Key components

- `scoring/engine.py` — the hard gate, the seven weighted factors, the bands, and the Nurse/Doctor rules
- `ledger/services.py` — the **only** write path into the Security Ledger
- `ledger/verification.py` — walks and re-validates the whole hash chain
- `offline/scoringEngine.js` — the JS port that keeps decisions working offline
- `identity/matching.py` — hand-written minutiae rigid-alignment matching

### Running tests

```bash
cd backend
python manage.py test              # whole suite (312 tests)
python manage.py test scoring      # one app
```

```bash
cd frontend
npm run lint
npm run build
```

The suite runs against Django's throwaway test databases and never touches the
real one. Every external service (Gemini, Twilio, WebAuthn) is mocked, so tests
never make a network call or send a real message.

## 🎬 Suggested demo path

1. **Normal access** — a doctor on duty opens an assigned patient. Full access, silently logged.
2. **Audited deviation** — same doctor, a patient on another ward. Granted, but permanently flagged.
3. **Reduced access** — a session scoring 40–69%. Sensitive categories withheld, and *nothing opens at all* until step-up verification.
4. **Hard denial** — a nurse neither assigned to nor sharing a ward with the patient. Denied regardless of score; a security alert is raised.
5. **Break the Glass** — the same nurse overrides with a logged justification, and gets exactly her role ceiling, nothing more.
6. **The patient finds out** — an SMS arrives on the patient's phone naming who accessed their record and how it was classified.
7. **The Security Dashboard** — every one of the above appears in the live feed. Open a deviation, read the factor breakdown, translate it with AI, acknowledge the alert.
8. **Prove the trail** — click **Verify ledger integrity**. Then edit a ledger row directly in the database and click it again: it names the exact entry that was altered.

## 🚢 Deployment

`render.yaml` (backend) and `frontend/vercel.json` (frontend) are included.

On **Render**, the blueprint provisions the web service and both databases, runs
migrations for each, and collects static files. Set `SECRET_KEY`,
`STAFF_LOGIN_PASSWORD`, and any optional integration keys in the dashboard.

On **Vercel**, set `VITE_API_BASE_URL` to your Render backend's `/api` URL.

> ⚠️ **Two deployment details that are easy to get wrong:**
> - `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` must match the **frontend's** domain, not the backend's — WebAuthn ties a credential to the origin the *browser* believes it's on.
> - Uploaded staff photos are stored on local disk, and Render's free tier has an ephemeral filesystem. Swap in object storage if that matters.

## 🔒 Privacy & Security

- **Keystroke capture never stores key identity** — timing only, indexed by position rather than character
- **The ledger cannot rewrite itself** — separate database, hash-chained, append-only at every level
- **Audit trails hold no foreign keys to the people they describe** — deleting a staff member removes the account, never the evidence of what they did
- **Enforced at the API, never only in the interface** — hiding a button is a convenience, not a control
- **Fail closed** — when a check cannot complete, access is withheld, with Break the Glass as the deliberate, logged exception
- **Encrypted at rest offline** — cached records, summaries and templates, under a non-extractable per-device key

## 📈 Roadmap

- [x] Behavioural + contextual capture
- [x] Scoring engine with role rules and access bands
- [x] Hash-chained Security Ledger with integrity verification
- [x] Three role-routed dashboards
- [x] Break the Glass + Disaster Mode
- [x] Device binding, lockout, WebAuthn step-up, colleague vouching
- [x] Offline mode with signed sync
- [x] MedGuard Identity — fingerprint patient lookup
- [x] Patient SMS notification
- [ ] Live-verify fingerprint matching against a second photo of the same finger
- [ ] Object storage for staff photos in production
- [ ] Integration adapters for existing hospital record systems

## 📄 License

No licence has been chosen yet — this is a hackathon submission. Treat the code
as all-rights-reserved until a `LICENSE` file is added.

## 🙏 Acknowledgments

- **Django / Django REST Framework** — the API layer
- **py_webauthn + @simplewebauthn/browser** — biometric step-up verification
- **OpenCV + scikit-image + fingerprint-feature-extractor** — minutiae extraction
- **Google Gemini** — plain-English explanations of ledger entries
- **Twilio** — patient SMS notification
- **three.js** — the login shield and the ledger event-breakdown chart

## ⚠️ Disclaimer

MedGuard is an access-control layer, not a clinical system. It does not provide
medical advice, diagnosis or treatment, and it is not a substitute for a
hospital's own clinical governance. Deploying it against real patient data
requires a data-protection assessment under the Nigeria Data Protection Act
2023 and the approval of the health establishment's own management.

---

<div align="center">

**Built for the patients whose records are the thing worth protecting**

Team Al Ansar · ICSC 2026 Universities Hackathon · Track C

</div>
